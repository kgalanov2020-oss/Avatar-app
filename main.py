from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from moviepy import ImageClip, TextClip, CompositeVideoClip
from gtts import gTTS
from moviepy import AudioFileClip

import shutil
import uuid
import os
import requests
from PIL import Image, ImageOps
import requests
import base64

print("SERVER VERSION UPDATED")

app = FastAPI()

STABILITY_API_KEY = "sk-FFV9CyR3ZOW7ca7YKr6TkjfBy8VJpQwPe6HgzGHuE1lZqggD"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")


@app.get("/")
def root():
    return {"status": "Server is running 🚀"}


@app.post("/create-3d-avatar/")
async def create_3d_avatar(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{file_id}.jpg")
    output_path = os.path.join(UPLOAD_DIR, f"{file_id}_avatar.png")

    # 1. сохранить файл
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 2. обработка изображения
    img = Image.open(input_path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")

    w, h = img.size
    side = int(min(w, h) * 0.75)
    left = (w - side) // 2
    top = int((h - side) * 0.35)

    img = img.crop((left, top, left + side, top + side))
    img = img.resize((640, 640))
    img.save(input_path)

    # 3. запрос к AI
    with open(input_path, "rb") as image_file:
        response = requests.post(
            "https://api.stability.ai/v2beta/stable-image/control/sketch",
            headers={
                "authorization": f"Bearer {STABILITY_API_KEY}",
                "accept": "image/*"
            },
            files={"image": image_file},
            data={
                "prompt": (
                    "one person only, single face only, front-facing portrait, "
                    "3D cartoon avatar of the same person, preserve identity"
                ),
                "negative_prompt": (
                    "two heads, extra head, duplicate face, multiple people"
                ),
                "control_strength": 0.5,
                "output_format": "png"
            }
        )

    if response.status_code != 200:
        return {"error": response.text}

    # 4. сохранить результат
    with open(output_path, "wb") as f:
        f.write(response.content)

    # 5. сохранить как последний аватар
    shutil.copy(output_path, "uploads/latest_avatar.png")

    # 6. вернуть результат
    return {
        "message": "3D avatar generated",
        "avatar_url": f"http://127.0.0.1:8000/files/{file_id}_avatar.png"
    }

@app.get("/create-video/")
def create_video():
    avatar_path = "uploads/latest_avatar.png"
    output_video = "uploads/result.mp4"

    text = "С днём рождения! Желаю счастья и здоровья!"

    tts = gTTS(text=text, lang="ru")
    audio_path = "uploads/audio.mp3"
    tts.save(audio_path)

    clip = ImageClip(avatar_path).with_duration(5)
    clip = clip.resized(lambda t: 1 + 0.03 * t)

    audio = AudioFileClip(audio_path)
    clip = clip.with_audio(audio)

    video = CompositeVideoClip([clip])
    video.write_videofile(output_video, fps=24)

    return {
        "video_url": "https://avatar-app-vcer.onrender.com/files/result.mp4"
    }

@app.get("/talking-video/")
def talking_video():
    response = requests.post(
        "https://api.d-id.com/talks",
        headers={
            "Authorization": "Basic ay5nYWxhbm92LjIwMjBAZ21haWwuY29t:zWojEupYS9BIPJWs7Jv9U",
            "Content-Type": "application/json"
        },
        json={
            "source_url": "https://avatar-app-vcer.onrender.com/files/latest_avatar.png",
            "script": {
                "type": "audio",
                "audio_url": "https://avatar-app-vcer.onrender.com/files/audio.mp3"
            }
        }
    )

    return response.json()

@app.get("/talking-video-status/{talk_id}")
def talking_video_status(talk_id: str):
    response = requests.get(
        f"https://api.d-id.com/talks/{talk_id}",
        headers={
            "Authorization": "Basic ay5nYWxhbm92LjIwMjBAZ21haWwuY29t:zWojEupYS9BIPJWs7Jv9U"
        }
    )

    data = response.json()

    return {
        "status": data.get("status"),
        "video_url": data.get("result_url")
    }
