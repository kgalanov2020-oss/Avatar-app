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

@app.post("/create-video/")
def create_video(text: str = Form("С днём рождения! Желаю счастья и здоровья!")):
    avatar_path = "uploads/latest_avatar.png"
    output_video = "uploads/result.mp4"

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
    * {
        box-sizing: border-box;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
        margin: 0;
        padding: 18px;
        background: linear-gradient(135deg, #f2f4f8, #e9ecf3);
        color: #111;
    }

    .card {
        width: 100%;
        max-width: 720px;
        margin: 24px auto;
        background: white;
        padding: 28px;
        border-radius: 24px;
        box-shadow: 0 12px 40px rgba(0,0,0,0.08);
    }

    h1 {
        font-size: 42px;
        margin: 0 0 12px;
    }

    p {
        font-size: 18px;
        color: #444;
    }

    input, textarea, button {
        width: 100%;
        margin-top: 14px;
        padding: 14px;
        font-size: 17px;
        border-radius: 14px;
        border: 1px solid #d0d0d0;
    }

    textarea {
        min-height: 120px;
        resize: vertical;
    }

    button {
        border: none;
        background: #000;
        color: white;
        cursor: pointer;
        font-weight: 700;
        transition: 0.2s;
    }

    button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .secondary {
        background: #f1f1f1;
        color: #111;
    }

    .steps {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
        margin-top: 20px;
    }

    .step {
        padding: 14px 10px;
        border-radius: 14px;
        background: #f2f2f2;
        text-align: center;
        font-weight: 700;
        font-size: 14px;
    }

    .step.active {
        background: #111;
        color: white;
    }

    .step.done {
        background: #d9f7df;
        color: #0b6b24;
    }

    #status {
        margin-top: 18px;
        font-weight: 700;
        line-height: 1.4;
    }

    video {
        width: 100%;
        margin-top: 20px;
        border-radius: 18px;
        background: #000;
    }

    .actions {
        display: none;
        gap: 12px;
        margin-top: 14px;
    }

    .actions.show {
        display: grid;
        grid-template-columns: 1fr 1fr;
    }

    @media (max-width: 600px) {
        body {
            padding: 10px;
        }

        .card {
            padding: 22px;
            margin: 10px auto;
            border-radius: 22px;
        }

        h1 {
            font-size: 34px;
        }

        p {
            font-size: 16px;
        }

        .steps {
            grid-template-columns: 1fr;
        }

        .actions.show {
            grid-template-columns: 1fr;
        }
    }
</style>
</head>
<body>
    <div class="card">
        <h1>AI Avatar Video</h1>
        <p>Загрузи фото, напиши текст — получи говорящее видео.</p>

        <input type="file" id="photo" accept="image/*">

        <textarea id="text" rows="4">С днём рождения! Желаю счастья и здоровья!</textarea>

        <button id="generateBtn" onclick="generateVideo()">Generate Video</button>

        <div class="steps">
            <div id="stepAvatar" class="step">1. Аватар</div>
            <div id="stepVoice" class="step">2. Голос</div>
            <div id="stepVideo" class="step">3. Видео</div>
        </div>

        <div id="status"></div>

        <video id="video" controls style="display:none;"></video>

        <div id="actions" class="actions">
            <a id="downloadLink" href="#" download="avatar-video.mp4">
                <button>Скачать видео</button>
            </a>
            <button class="secondary" onclick="resetApp()">Создать ещё</button>
        </div>
    </div>

<script>
let currentTalkId = null;
let finalVideoUrl = null;

function setStep(step) {
    const avatar = document.getElementById("stepAvatar");
    const voice = document.getElementById("stepVoice");
    const video = document.getElementById("stepVideo");

    avatar.className = "step";
    voice.className = "step";
    video.className = "step";

    if (step === 1) {
        avatar.className = "step active";
    }

    if (step === 2) {
        avatar.className = "step done";
        voice.className = "step active";
    }

    if (step === 3) {
        avatar.className = "step done";
        voice.className = "step done";
        video.className = "step active";
    }

    if (step === 4) {
        avatar.className = "step done";
        voice.className = "step done";
        video.className = "step done";
    }
}

async function generateVideo() {
    const fileInput = document.getElementById("photo");
    const text = document.getElementById("text").value;
    const status = document.getElementById("status");
    const video = document.getElementById("video");
    const btn = document.getElementById("generateBtn");
    const actions = document.getElementById("actions");

    if (!fileInput.files.length) {
        alert("Выбери фото");
        return;
    }

    btn.disabled = true;
    actions.className = "actions";
    video.style.display = "none";
    status.innerText = "";

    try {
        setStep(1);
        status.innerText = "Создаём 3D аватар...";

        const avatarForm = new FormData();
        avatarForm.append("file", fileInput.files[0]);

        const avatarResponse = await fetch("/create-3d-avatar/", {
            method: "POST",
            body: avatarForm
        });

        const avatarData = await avatarResponse.json();

        if (avatarData.error) {
            throw new Error("Ошибка аватара: " + JSON.stringify(avatarData));
        }

        setStep(2);
        status.innerText = "Создаём голос...";

        const textForm = new FormData();
        textForm.append("text", text);

        const voiceResponse = await fetch("/create-video/", {
            method: "POST",
            body: textForm
        });

        const voiceData = await voiceResponse.json();

        if (voiceData.error) {
            throw new Error("Ошибка голоса: " + JSON.stringify(voiceData));
        }

        setStep(3);
        status.innerText = "Запускаем говорящую анимацию...";

        const talkResponse = await fetch("/talking-video/");
        const talkData = await talkResponse.json();

        currentTalkId = talkData.id;

        if (!currentTalkId) {
            throw new Error("Не получили talk_id. Ответ сервера: " + JSON.stringify(talkData));
        }

        status.innerText = "Видео создаётся. Это может занять 30–90 секунд.";
        checkStatus();

    } catch (error) {
        status.innerText = error.message;
        btn.disabled = false;
    }
}

async function checkStatus() {
    const status = document.getElementById("status");
    const video = document.getElementById("video");
    const btn = document.getElementById("generateBtn");
    const actions = document.getElementById("actions");
    const downloadLink = document.getElementById("downloadLink");

    const response = await fetch("/talking-video-status/" + currentTalkId);
    const data = await response.json();

    if (data.status === "done" && data.video_url) {
        setStep(4);
        finalVideoUrl = data.video_url;

        status.innerText = "Готово!";
        video.src = finalVideoUrl;
        video.style.display = "block";

        downloadLink.href = finalVideoUrl;
        actions.className = "actions show";
        btn.disabled = false;
        return;
    }

    status.innerText = "Статус: " + data.status + ". Ждём...";
    setTimeout(checkStatus, 5000);
}

function resetApp() {
    currentTalkId = null;
    finalVideoUrl = null;

    document.getElementById("photo").value = "";
    document.getElementById("video").style.display = "none";
    document.getElementById("video").src = "";
    document.getElementById("status").innerText = "";
    document.getElementById("actions").className = "actions";

    setStep(0);
}
</script>
</body>
</html>
