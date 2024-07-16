import os, asyncio, logging, click
from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager, current_user
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash
from handlers.log_reg import index, login, register, logout, get_voices, voice_chat
from models.models import db, User, Voice
from handlers.handlres import process_audio_stream, handle_openai_response

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'svo67ad39c9b5e6679a86d1a2c97d92a')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(app, async_mode='eventlet')

login_manager = LoginManager(app)
login_manager.login_view = 'login'

logging.basicConfig(level=logging.DEBUG)

ffmpeg_path = os.getenv('FFMPEG_PATH', '/usr/bin/ffmpeg')
os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_path)

AUDIO_FILES_DIR = 'audio_files'
os.makedirs(AUDIO_FILES_DIR, exist_ok=True)

openai_api_key = os.getenv('OPENAI_API_KEY')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

app.add_url_rule('/', 'index', index)
app.add_url_rule('/login', 'login', login, methods=['GET', 'POST'])
app.add_url_rule('/register', 'register', register, methods=['GET', 'POST'])
app.add_url_rule('/logout', 'logout', logout)
app.add_url_rule('/voices', 'get_voices', get_voices, methods=['GET'])
app.add_url_rule('/voice_chat', 'voice_chat', voice_chat)

class AdminModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

admin = Admin(app, name='Admin Panel', template_mode='bootstrap3')
admin.add_view(AdminModelView(User, db.session))
admin.add_view(AdminModelView(Voice, db.session))

@socketio.on("audio_stream")
def handle_audio_stream(data):
    asyncio.run(process_audio_stream(data))

@socketio.on("audio_response")
def handle_audio_response_event(data):
    handle_openai_response(data)

@app.cli.command('create_admin')
@click.argument('username')
@click.argument('email')
@click.argument('password')
def create_admin(username, email, password):
    hashed_password = generate_password_hash(password)
    user = User(username=username, email=email, password=hashed_password, is_admin=True)
    db.session.add(user)
    db.session.commit()
    print(f'Admin {username} created successfully.')

if __name__ == '__main__':
    host = '127.0.0.1'
    port = 8000
    print(f"Starting server on http://{host}:{port}")
    with app.app_context():
        db.create_all()
    socketio.run(app, host=host, port=port, debug=True)
