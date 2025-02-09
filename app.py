import random
import time
import os
import logging
from flask import Flask, redirect, url_for, session, render_template, request, jsonify
from datetime import timedelta, datetime
from authlib.integrations.flask_client import OAuth
from functools import wraps
from huggingface_hub import InferenceClient
from dotenv import load_dotenv  # Import dotenv

# Load environment variables
load_dotenv()
HF_CLIENT_ID=os.getenv("HF_CLIENT_ID")
HF_CLIENT_SECRET=os.getenv("HF_CLIENT_SECRET")
SECRET_KEY=os.getenv("SECRET_KEY")


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# App config
app = Flask(__name__)
app.secret_key = SECRET_KEY  # Load secret key from .env
app.config['SESSION_COOKIE_NAME'] = 'huggingface-login-session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=9999)

# OAuth configuration
oauth = OAuth(app)
oauth.register(
    name='huggingface',
    client_id=HF_CLIENT_ID,  # Load from .env
    client_secret=HF_CLIENT_SECRET,  # Load from .env
    access_token_url='https://huggingface.co/oauth/token',
    access_token_params=None,
    authorize_url=f'https://huggingface.co/oauth/authorize',
    client_kwargs={'scope': 'inference-api'},
    server_metadata_url='https://huggingface.co/.well-known/openid-configuration'
)


# check for session
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user_token')
        if  not user or 'access_token' not in user:
            logger.info("No valid user token, redirecting to login.")
            return redirect(url_for("login"))
        if int(time.time()) > user.get("expires_at",0) - 5:
            logger.info("Token expired, forcing re-login.")
            session.pop("user_token", None)
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
@login_required
def home():
    tasks = session.get('tasks', [])
    return render_template('index.html', tasks=tasks)

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    task_name = request.form.get('task')
    deadline = request.form.get('deadline')

    if not task_name or not deadline:
        return jsonify({"error": "Task and deadline required"}), 400

    tasks = session.get('tasks', [])
    tasks.append({'task': task_name, 'deadline': deadline})
    session['tasks'] = tasks

    return redirect(url_for('home'))

@app.route('/delete_task/<int:index>')
@login_required
def delete_task(index):
    tasks = session.get('tasks', [])
    if 0 <= index < len(tasks):
        del tasks[index]
        session['tasks'] = tasks
    return redirect(url_for('home'))

@app.route('/motivation')
@login_required
def motivation():
    tasks = session.get('tasks', [])
    if not tasks:
        return jsonify({"message": "No tasks to motivate you for!"})
    # Find the nearest upcoming task
    now = datetime.now()
    nearest_task = min(tasks, key=lambda t: abs((datetime.strptime(t['deadline'], "%Y-%m-%d %H:%M") - now).total_seconds()))

    deadline = datetime.strptime(nearest_task['deadline'], "%Y-%m-%dT%H:%M")
    time_left = deadline - now
    hours_left = time_left.total_seconds() / 3600

    # Random variations in AI prompt
    prompts = [
        f"I have {nearest_task['task']} due in {int(hours_left)} hours. Discourage me in a fun way!",
        f"I am feeling lazy. Can you demotivate me from completing {nearest_task['task']} in {int(hours_left)} hours?",
        f"Demotivate me like a task manager for my task: {nearest_task['task']} due in {int(hours_left)} hours.",
        f"Why should I not complete {nearest_task['task']} within {int(hours_left)} hours?"
        f"You are my task manager who will prevent me from completing the tasks."
        f"I will provide the task name and deadline date,"
        f"your job is to make me procrast the task."
        f"Don't say that you cannot procrast"
    ]

    client = InferenceClient(
        model="NousResearch/Hermes-3-Llama-3.1-8B",
        token=session['user_token']['access_token'],
        timeout=60.0,
    )

    response = client.chat_completion(
        messages=[{"role": "user", "content": random.choice(prompts)}],
        max_tokens=200,
        stream=False,
    )

    motivation_message = response.choices[0].message.content

    return jsonify({"task": nearest_task['task'], "motivation": motivation_message})

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/confirm_login')
def confirm_login():
    redirect_uri = url_for('authorize', _external=True)
    return oauth.huggingface.authorize_redirect(redirect_uri, prompt="login")


@app.route('/authorize')
def authorize():
    token = oauth.huggingface.authorize_access_token()  # Access token from hugginface (needed to get user info)
    # user = oauth.huggingface.userinfo()  # uses openid endpoint to fetch user info
    session['user_token'] = token
    session.permanent = True  # make the session permanant so it keeps existing after broweser gets closed
    logger.info(f"User logged in with token: {token}")
    return redirect('/')


@app.route('/logout')
def logout():
    for key in list(session.keys()):
        session.pop(key)
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    app.run()