import os, logging, asyncio, base64, openai, click
from io import BytesIO
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit
from pydub import AudioSegment
from models.models import db, User, Voice
from forms.forms import LoginForm, RegisterForm
from sqlalchemy.exc import IntegrityError
from gtts import gTTS
from sqlalchemy.orm import Session
from flask import current_app

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'svo67ad39c9b5e6679a86d1a2c97d92a')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Disable modification tracking

db.init_app(app)
socketio = SocketIO(app, async_mode='eventlet')
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Ensure ffmpeg and ffprobe paths are set correctly
ffmpeg_path = os.getenv('FFMPEG_PATH', '/usr/bin/ffmpeg')
ffprobe_path = os.getenv('FFPROBE_PATH', '/usr/bin/ffprobe')
AudioSegment.converter = ffmpeg_path
AudioSegment.ffprobe = ffprobe_path

# Add ffmpeg path to environment PATH
os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_path)

# Ensure audio files directory exists
AUDIO_FILES_DIR = 'audio_files'
os.makedirs(AUDIO_FILES_DIR, exist_ok=True)
socketio = SocketIO(app, async_mode='eventlet')

# Set API keys (ensure these are managed securely)
openai.api_key = os.getenv('OPENAI_API_KEY', 'your_openai_api_key')
elevenlabs_api_key = os.getenv('ELEVENLABS_API_KEY', 'your_elevenlabs_api_key')

# Flask-Login user loader
def load_user(user_id):
    session = Session()
    user = session.query(User).get(int(user_id))
    session.close()
    return user

def convert_to_wav(audio_data):
    try:
        webm_audio = BytesIO(audio_data)
        webm_audio.name = 'input.webm'
        webm_audio.seek(0)

        logging.debug("Преобразование аудио через pydub")
        audio = AudioSegment.from_file(webm_audio, format="webm")
        wav_io = BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        logging.debug("Конвертация завершена")
        return wav_io.read()
    except Exception as e:
        logging.error(f"Ошибка при конвертации аудио: {e}")
        logging.debug(f"Подробности ошибки: {e.__class__.__name__}, {e.args}")
        raise e
    
async def text_to_speech(text, voice_id):
    try:
        logging.debug("Преобразование текста в речь через gTTS")
        tts = gTTS(text, lang='ru')
        tts_io = BytesIO()
        tts.write_to_fp(tts_io)
        tts_io.seek(0)

        audio = AudioSegment.from_file(tts_io, format="mp3")
        wav_io = BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        return base64.b64encode(wav_io.read()).decode('utf-8')
    except Exception as e:
        logging.error(f"Ошибка при преобразовании текста в речь: {e}")
        raise e

# Routes
@app.route('/')
def index():
    voices = [
        {"voice_id": "1", "name": "Voice 1"},
        {"voice_id": "2", "name": "Voice 2"}
    ]
    return render_template('index.html', voices=voices)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember_me.data)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, email=form.email.data, password=hashed_password)
        try:
            db.session.add(user)
            db.session.commit()
            flash('Your account has been created! You can now log in.', 'success')
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            flash('User with that email already exists', 'danger')
    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/voices', methods=['GET'])
def get_voices():
    voices = Voice.query.all()
    voice_list = [{"id": voice.id, "name": voice.name, "description": voice.description, "voice_id": voice.voice_id} for voice in voices]
    return jsonify(voice_list)

@app.route('/voice_chat')
@login_required
def voice_chat():
    voices = Voice.query.all()
    return render_template('voice_chat.html', voices=voices)

# Admin panel setup
class AdminModelView(ModelView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

admin = Admin(app, name='Admin Panel', template_mode='bootstrap3')
admin.add_view(AdminModelView(User, db.session))
admin.add_view(AdminModelView(Voice, db.session))

# Async functions for processing audio stream
async def transcribe_audio(audio_data):
    return "Transcribed text"

async def get_openai_response(text):
    return "OpenAI response text"

async def text_to_speech_stream(text, voice_id):
    yield base64.b64encode(b'Fake audio data').decode('utf-8')

@socketio.on("audio_stream")
def handle_audio_stream(data):
    async def process_audio_stream(data):
        try:
            logging.debug("Получение аудиоданных")
            audio_data = base64.b64decode(data["audio"])
            logging.debug("Конвертация аудиоданных в WAV формат")
            wav_data = await asyncio.to_thread(convert_to_wav, audio_data)
            logging.debug("Транскрипция аудиоданных")
            transcribed_text = await transcribe_audio(wav_data)
            emit("partial_response", {"sender": "user", "text": transcribed_text})
            logging.debug("Получение ответа от OpenAI")
            response_text = await get_openai_response(transcribed_text)
            emit("partial_response", {"sender": "ai", "text": response_text})
            logging.debug("Преобразование текста в речь")
            tts_audio = await text_to_speech(response_text, data["voice"])
            emit("audio_response", {"audio": tts_audio})
        except Exception as e:
            logging.error(f"Ошибка при обработке аудиопотока: {e}")
            logging.debug(f"Подробности ошибки: {e.__class__.__name__}, {e.args}")
            emit("error", {"message": str(e)})

@socketio.on("audio_response")
def handle_audio_response(data):
    emit("audio_response", data, broadcast=True)  # Отправляем голосовой ответ всем подключенным клиентам

# CLI command to create admin user
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

# Run the Flask app with SocketIO
if __name__ == '__main__':
    host = '127.0.0.1'
    port = 8000
    print(f"Starting server on http://{host}:{port}")
    with app.app_context():
        db.create_all()  # Create all database tables
    socketio.run(app, host=host, port=port, debug=True)
