from fastapi.responses import HTMLResponse
from fastapi import FastAPI, UploadFile, File, Form
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

STABILITY_API_KEY = "sk-Ywdje9DGNRKwbjvgdP4v42AhL6KtCJT1GVOHcH784Vr1u2ma"

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
    side = int(min(w, h) * 0.9)
    left = (w - side) // 2
    top = int((h - side) * 0.2)

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
                    "pixar style 3D avatar, centered face, symmetrical face, "
                    "clean background, preserve identity, realistic mouth"
                ),
                "negative_prompt": (
                    "two heads, duplicate face, cropped face, zoomed face, deformed mouth"
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
    shutil.copy(output_path, os.path.join(UPLOAD_DIR, "latest_avatar.png"))

    # 6. вернуть результат
    return {
        "message": "3D avatar generated",
        "avatar_url": f"https://avatar-app-vcer.onrender.com/files/{file_id}_avatar.png"
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
            "Authorization": "Basic ay5nYWxhbm92LjIwMjBAZ21haWwuY29t:3DXWaFXSOEzNJpzNJibCP",
            "Content-Type": "application/json"
        },
        json={
            "source_url": "https://avatar-app-vcer.onrender.com/files/latest_avatar.png",
            "script": {
                "type": "audio",
                "audio_url": "https://avatar-app-vcer.onrender.com/files/audio.mp3"
            },
            "config": {
                "stitch": True,
                "show_watermark": False
            }
        }
    )

    return response.json()

@app.get("/talking-video-status/{talk_id}")
def talking_video_status(talk_id: str):
    response = requests.get(
        f"https://api.d-id.com/talks/{talk_id}",
        headers={
            "Authorization": "Basic ay5nYWxhbm92LjIwMjBAZ21haWwuY29t:3DXWaFXSOEzNJpzNJibCP"
        }
    )

    data = response.json()

    return {
        "status": data.get("status"),
        "video_url": data.get("result_url")
    }

@app.post("/generate-final-video/")
async def generate_final_video(
    file: UploadFile = File(...),
    text: str = Form("С днём рождения! Желаю счастья и здоровья!")
):
    try:
        avatar_result = await create_3d_avatar(file)

        if "error" in avatar_result:
            return avatar_result

        audio_path = os.path.join(UPLOAD_DIR, "audio.mp3")
        tts = gTTS(text=text, lang="ru")
        tts.save(audio_path)

        response = requests.post(
            "https://api.d-id.com/talks",
            headers={
                "Authorization": "Basic ay5nYWxhbm92LjIwMjBAZ21haWwuY29t:3DXWaFXSOEzNJpzNJibCP",
                "Content-Type": "application/json"
            },
            json={
                "source_url": "https://avatar-app-vcer.onrender.com/files/latest_avatar.png",
                "script": {
                    "type": "audio",
                    "audio_url": "https://avatar-app-vcer.onrender.com/files/audio.mp3"
                },
                "config": {
                    "stitch": True,
                    "show_watermark": False
                }
            }
        )

        return response.json()

    except Exception as e:
        return {
            "error": "generate-final-video failed",
            "details": str(e)
        }

@app.get("/app", response_class=HTMLResponse)
def app_page():
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>AI Avatar Video</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 700px;
            margin: 40px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .card {
            background: white;
            padding: 24px;
            border-radius: 18px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        }
        input, textarea, button {
            width: 100%;
            margin-top: 12px;
            padding: 12px;
            font-size: 16px;
            border-radius: 10px;
            border: 1px solid #ccc;
        }
        button {
            background: black;
            color: white;
            cursor: pointer;
            font-weight: bold;
        }
        video {
            width: 100%;
            margin-top: 20px;
            border-radius: 14px;
        }
        #status {
            margin-top: 16px;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>AI Avatar Video</h1>
        <p>Загрузи фото, напиши текст — получи говорящее видео.</p>

        <input type="file" id="photo" accept="image/*">

        <textarea id="text" rows="4">С днём рождения! Желаю счастья и здоровья!</textarea>

        <button onclick="generateVideo()">Generate Video</button>

        <div id="status"></div>

        <video id="video" controls style="display:none;"></video>
    </div>

<script>
let currentTalkId = null;

async function generateVideo() {
    const fileInput = document.getElementById("photo");
    const text = document.getElementById("text").value;
    const status = document.getElementById("status");
    const video = document.getElementById("video");

    if (!fileInput.files.length) {
        alert("Выбери фото");
        return;
    }

    status.innerText = "Генерируем аватар и запускаем видео... Это может занять 1-2 минуты.";
    video.style.display = "none";

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("text", text);

    const response = await fetch("/generate-final-video/", {
        method: "POST",
        body: formData
    });

    const data = await response.json();

    if (data.error) {
        status.innerText = "Ошибка: " + data.details;
        return;
    }

    currentTalkId = data.talk_id || data.id;

if (!currentTalkId) {
    status.innerText = "Ошибка: не получили talk_id. Ответ сервера: " + JSON.stringify(data);
    return;
}

    status.innerText = "Видео создаётся. ID: " + currentTalkId;

    checkStatus();
}

async function checkStatus() {
    const status = document.getElementById("status");
    const video = document.getElementById("video");

    const response = await fetch("/talking-video-status/" + currentTalkId);
    const data = await response.json();

    if (data.status === "done" && data.video_url) {
        status.innerText = "Готово!";
        video.src = data.video_url;
        video.style.display = "block";
        return;
    }

    status.innerText = "Статус: " + data.status + ". Ждём...";
    setTimeout(checkStatus, 5000);
}
</script>
</body>
</html>
"""
