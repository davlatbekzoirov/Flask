import logging,asyncio, base64
from io import BytesIO
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from pydub import AudioSegment
from gtts import gTTS
from flask_socketio import emit
from aiohttp import ClientSession
import speech_recognition as sr
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
from models.models import db, User, Voice
from forms.forms import LoginForm, RegisterForm
from sqlalchemy.exc import IntegrityError
from data.config import OPENAI_API_KEY, ELEVENLABS_API_KEY

logging.basicConfig(level=logging.DEBUG)

async def handle_tts(response_text, voice_id):
    tts_audio = await text_to_speech(response_text, voice_id)
    return tts_audio

async def process_audio_stream(data):
    try:
        logging.debug("Receiving audio data")
        audio_data = base64.b64decode(data["audio"])
        logging.debug("Converting audio data to WAV format")
        wav_data = await asyncio.to_thread(convert_to_wav, audio_data)
        logging.debug("Transcribing audio data")
        
        transcribed_text = await transcribe_and_emit(wav_data)
        emit("partial_response", {"sender": "user", "text": transcribed_text})
        
        logging.debug("Getting response from OpenAI")
        response_text = await handle_openai_response(transcribed_text)
        emit("partial_response", {"sender": "ai", "text": response_text})
        
        logging.debug("Converting text to speech")
        tts_audio = await handle_tts(response_text, data["voice"])
        emit("audio_response", {"audio": tts_audio})
    except Exception as e:
        logging.error(f"Error processing audio stream: {e}")
        logging.debug(f"Error details: {e.__class__.__name__}, {e.args}")
        emit("error", {"message": str(e)})

async def handle_openai_response(transcribed_text):
    return await get_openai_response(transcribed_text)

async def transcribe_and_emit(wav_data):
    transcribed_text = await transcribe_audio(wav_data)
    emit("transcription", {"text": transcribed_text})
    return transcribed_text

def convert_to_wav(audio_data):
    try:
        webm_audio = BytesIO(audio_data)
        webm_audio.name = 'input.webm'
        webm_audio.seek(0)

        logging.debug("Converting audio using pydub")
        audio = AudioSegment.from_file(webm_audio, format="webm")
        wav_io = BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        logging.debug("Conversion complete")
        return wav_io.read()
    except Exception as e:
        logging.error(f"Error converting audio: {e}")
        logging.debug(f"Error details: {e.__class__.__name__}, {e.args}")
        raise e
    
async def text_to_speech(text, voice_id):
    try:
        logging.debug("Converting text to speech using gTTS")
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
        logging.error(f"Error converting text to speech: {e}")
        raise e

async def transcribe_audio(audio_data):
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(BytesIO(audio_data)) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language="ru-RU")
    except sr.UnknownValueError:
        logging.error("Google Speech Recognition could not understand the audio")
        text = ""
    except sr.RequestError as e:
        logging.error(f"Could not request results from Google Speech Recognition service; {e}")
        text = ""
    return text

async def get_openai_response(prompt):
    async with ClientSession() as session:
        logging.debug(f"Sending to GPT: {prompt}")
        async with session.post(
                'https://api.openai.com/v1/chat/completions',
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": "You are a voice assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.9,
                },
        ) as response:
            result = await response.json()
            logging.debug(f"OpenAI response: {result}")
            
            if response.status != 200:
                error_message = result.get("error", {}).get("message", "Unknown error")
                logging.error(f"OpenAI API error: {error_message}")
                raise Exception(f"OpenAI API error: {error_message}")
            
            try:
                return result["choices"][0]["message"]["content"]
            except KeyError:
                logging.error("OpenAI response does not contain 'choices'")
                raise Exception("OpenAI API response does not contain 'choices'")

async def text_to_speech_stream(text, voice_id):
    client = ElevenLabs(ELEVENLABS_API_KEY)
    response = client.text_to_speech.convert(
        voice_id=voice_id,
        optimize_streaming_latency="0",
        output_format="mp3_22050_32",
        text=text,
        model_id="eleven_multilingual_v2",
        voice_settings=VoiceSettings(
            stability=0.5,
            similarity_boost=0.5,
            style=0.0,
            use_speaker_boost=True,
        ),
    )

    for chunk in response:
        if chunk:
            yield chunk
