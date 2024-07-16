from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models.models import db, User, Voice
from forms.forms import LoginForm, RegisterForm
from sqlalchemy.exc import IntegrityError

def index():
    voices = [
        {"voice_id": "1", "name": "Voice 1"},
        {"voice_id": "2", "name": "Voice 2"}
    ]
    return render_template('index.html', voices=voices)

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
        flash('Invalid email or password', 'danger')
    return render_template('login.html', form=form)

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

def logout():
    logout_user()
    return redirect(url_for('index'))


def get_voices():
    voices = Voice.query.all()
    voice_list = [{"id": voice.id, "name": voice.name, "description": voice.description, "voice_id": voice.voice_id} for voice in voices]
    return jsonify(voice_list)

def voice_chat():
    voices = Voice.query.all()
    return render_template('voice_chat.html', voices=voices)