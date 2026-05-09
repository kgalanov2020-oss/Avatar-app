from fastapi.responses import HTMLResponse
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from moviepy import ImageClip, TextClip, CompositeVideoClip
import edge_tts
import asyncio
from moviepy import AudioFileClip
from moviepy import VideoFileClip, CompositeVideoClip, ColorClip

import shutil
import uuid
import os
import requests
from PIL import Image, ImageOps
import base64

print("SERVER VERSION UPDATED")

app = FastAPI()

STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")
DID_API_KEY = os.getenv("DID_API_KEY")

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
async def create_3d_avatar(
    file: UploadFile = File(...),
    theme: str = Form("default"),
    custom_theme: str = Form("")
):
    file_id = str(uuid.uuid4())
    input_path = os.path.join(UPLOAD_DIR, f"{file_id}.jpg")
    output_path = os.path.join(UPLOAD_DIR, f"{file_id}_avatar.png")

    theme_prompts = {
        "default": "3D cartoon avatar portrait, clean background",
        "astronaut": "3D cartoon astronaut suit, cosmic background",
        "cowboy": "3D cartoon cowboy outfit, western desert background",
        "royal": "3D cartoon king or queen outfit, royal palace background",
        "sport": "3D cartoon athlete uniform, stadium background",
        "sailor": "3D cartoon sailor outfit, sea background",
        "samurai": "3D cartoon samurai armor, japanese temple background",
        "cyberpunk": "3D cartoon cyberpunk style, neon futuristic city background",
        "superhero": "3D cartoon superhero costume, cinematic action background",
        "rockstar": "3D cartoon rock star outfit, concert stage background",
        "gangster": "3D cartoon mafia gangster suit, 1920s luxury background",
        "pirate": "3D cartoon pirate captain outfit, pirate ship background",
        "wizard": "3D cartoon wizard robe, magical fantasy background",
        "viking": "3D cartoon viking warrior armor, nordic background",
        "ninja": "3D cartoon ninja outfit, dark japanese background",
        "luxury": "3D cartoon luxury billionaire outfit, private jet background",
        "angel": "3D cartoon angel wings, heavenly clouds background",
        "demon": "3D cartoon dark demon style, fire fantasy background",
        "pharaoh": "3D cartoon egyptian pharaoh outfit, pyramid background",
        "knight": "3D cartoon medieval knight armor, castle background",
        "racer": "3D cartoon formula one racing suit, racetrack background"
    }

    theme_prompt = theme_prompts.get(theme, theme_prompts["default"])

    if theme == "custom" and custom_theme.strip():
        theme_prompt = (
    f"highly detailed 3D cartoon avatar inspired by {custom_theme.strip()}, "
    f"maintain same facial identity of uploaded person, "
    f"cinematic lighting, matching outfit, themed environment, "
    f"professional character design, stylized background, "
    f"high quality animated movie style"
)

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

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
                    "high quality 3D cartoon avatar of the same person, "
                    "preserve identity, same face shape, same eyes, same nose, "
                    "same lips, same hairstyle, same gender, same skin tone, "
                    "front-facing portrait, centered face, realistic mouth, "
                    + theme_prompt
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

    with open(output_path, "wb") as f:
        f.write(response.content)

    shutil.copy(output_path, os.path.join(UPLOAD_DIR, "latest_avatar.png"))

    return {
        "message": "3D avatar generated",
        "avatar_url": f"https://avatar-app-vcer.onrender.com/files/{file_id}_avatar.png"
    }

@app.post("/create-video/")
async def create_video(
    text: str = Form("С днём рождения!"),
    voice: str = Form("female"),
    format: str = Form("square")
):
    audio_path = "uploads/audio.mp3"

    if voice == "male":
        voice_name = "ru-RU-DmitryNeural"
    else:
        voice_name = "ru-RU-SvetlanaNeural"

    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(audio_path)

    return {
        "audio_url": "https://avatar-app-vcer.onrender.com/files/audio.mp3",
        "format": format
    }

@app.get("/talking-video/")
def talking_video():
    response = requests.post(
        "https://api.d-id.com/talks",
        headers={
            "Authorization": DID_API_KEY,
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
        "Authorization": DID_API_KEY
        }
    )

    data = response.json()

    return {
        "status": data.get("status"),
        "video_url": data.get("result_url")
    }

@app.post("/make-vertical/")
async def make_vertical(video_url: str = Form(...)):

    input_path = "uploads/input.mp4"
    output_path = "uploads/vertical.mp4"

    video_response = requests.get(video_url)

    with open(input_path, "wb") as f:
        f.write(video_response.content)

    clip = VideoFileClip(input_path)

    background = (
        clip.resized(height=1280)
        .cropped(x_center=clip.w / 2, width=720, height=1280)
        .with_opacity(0.35)
    )

    foreground = (
        clip.resized(width=720)
        .with_position(("center", "center"))
    )

    final = CompositeVideoClip(
        [background, foreground],
        size=(720, 1280)
    )

    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac"
    )

    return {
        "vertical_video_url": "https://avatar-app-vcer.onrender.com/files/vertical.mp4"
    }

@app.post("/generate-final-video/")
async def generate_final_video(
    file: UploadFile = File(...),
    text: str = Form("С днём рождения! Желаю счастья и здоровья!"),
    voice: str = Form("female")
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
                "Authorization": DID_API_KEY,
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Avatar Video</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif;
    background:
        radial-gradient(circle at top left, #ffe8f0, transparent 35%),
        radial-gradient(circle at bottom right, #dff3ff, transparent 35%),
        #f5f6fa;
    color: #111;
    padding: 18px;
}

.card {
    width: 100%;
    max-width: 760px;
    margin: 18px auto;
    background: rgba(255,255,255,0.92);
    backdrop-filter: blur(12px);
    border-radius: 28px;
    padding: 28px;
    box-shadow: 0 18px 50px rgba(0,0,0,0.10);
}

.badge {
    display: inline-block;
    padding: 8px 12px;
    background: #111;
    color: white;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 16px;
}

h1 {
    font-size: 44px;
    margin: 0;
    letter-spacing: -1px;
}

.subtitle {
    font-size: 18px;
    color: #555;
    line-height: 1.45;
    margin-bottom: 24px;
}

label {
    display: block;
    margin-top: 16px;
    margin-bottom: 8px;
    font-weight: 700;
}

input, textarea, select, button {
    width: 100%;
    padding: 15px;
    font-size: 17px;
    border-radius: 16px;
    border: 1px solid #d6d6d6;
    background: white;
}

textarea {
    min-height: 130px;
    resize: vertical;
}

button {
    border: none;
    margin-top: 20px;
    background: linear-gradient(135deg, #111, #444);
    color: white;
    font-weight: 800;
    cursor: pointer;
    transition: transform 0.15s ease, opacity 0.15s ease;
}

button:hover {
    transform: translateY(-1px);
}

button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

.secondary {
    background: #f0f0f0;
    color: #111;
}

.steps {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin-top: 22px;
}

.step {
    padding: 14px 10px;
    border-radius: 16px;
    background: #f1f1f1;
    text-align: center;
    font-size: 14px;
    font-weight: 800;
    color: #777;
}

.step.active {
    background: #111;
    color: white;
}

.step.done {
    background: #dff8e7;
    color: #0f7a35;
}

.progress-wrap {
    width: 100%;
    height: 10px;
    background: #ececec;
    border-radius: 999px;
    margin-top: 18px;
    overflow: hidden;
}

#progressBar {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, #111, #777);
    transition: width 0.4s ease;
}

#status {
    margin-top: 18px;
    font-weight: 800;
    line-height: 1.45;
}

.hint {
    font-size: 14px;
    color: #777;
    margin-top: 8px;
}

video {
    width: 100%;
    margin-top: 22px;
    border-radius: 20px;
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

.footer-note {
    margin-top: 18px;
    font-size: 13px;
    color: #777;
    text-align: center;
}

@media (max-width: 640px) {
    body {
        padding: 10px;
    }

    .card {
        padding: 22px;
        border-radius: 24px;
        margin: 8px auto;
    }

    h1 {
        font-size: 34px;
    }

    .subtitle {
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
    <div class="badge">AI Greeting Video</div>

    <h1>AI Avatar Video</h1>
    <p class="subtitle">Загрузи фото, напиши поздравление — получи говорящее видео с AI-аватаром.</p>

    <label>Фото</label>
    <input type="file" id="photo" accept="image/*">

    <label>Текст поздравления</label>
    <textarea id="text">С днём рождения! Желаю счастья, здоровья и исполнения всех желаний!</textarea>
    <div class="hint">Лучше писать 1–2 коротких предложения.</div>

    <label>Тема</label>

<select id="theme" onchange="toggleCustomTheme()">
    <option value="custom">Собственная тема</option>
    <option value="default">Обычный</option>
    <option value="astronaut">Космонавт</option>
    <option value="cowboy">Ковбой</option>
    <option value="royal">Король / Королева</option>
    <option value="sport">Спортсмен</option>
    <option value="sailor">Моряк</option>
    <option value="samurai">Самурай</option>
    <option value="cyberpunk">Киберпанк</option>
    <option value="superhero">Супергерой</option>
    <option value="rockstar">Рок-звезда</option>
    <option value="gangster">Гангстер 1920s</option>
    <option value="pirate">Пират</option>
    <option value="wizard">Маг / Волшебник</option>
    <option value="viking">Викинг</option>
    <option value="ninja">Ниндзя</option>
    <option value="luxury">Luxury бизнесмен</option>
    <option value="angel">Ангел</option>
    <option value="demon">Демон</option>
    <option value="pharaoh">Фараон</option>
    <option value="knight">Рыцарь</option>
    <option value="racer">Гонщик Formula 1</option>
</select>

<input 
    type="text" 
    id="customTheme" 
    placeholder="Например: врач, футболист, принцесса, робот..." 
    style="display:none;"
>

    <label>Голос</label>
    <select id="voice">
        <option value="female">Женский голос</option>
        <option value="male">Мужской голос</option>
    </select>

    <label>Формат видео</label>

    <select id="format">
        <option value="square">Квадрат (1:1)</option>
        <option value="vertical">TikTok / Reels (9:16)</option>
    </select>

    <button id="generateBtn" onclick="generateVideo()">Создать видео</button>

    <div class="steps">
        <div id="stepAvatar" class="step">1. Аватар</div>
        <div id="stepVoice" class="step">2. Голос</div>
        <div id="stepVideo" class="step">3. Видео</div>
    </div>

    <div class="progress-wrap">
        <div id="progressBar"></div>
    </div>

    <div id="status"></div>

    <video id="video" controls style="display:none;"></video>
    <img id="avatarPreview" style="display:none; width:100%; border-radius:20px; margin-top:20px;">

    <div id="actions" class="actions">
        <a id="downloadLink" href="#" download="avatar-video.mp4">
            <button>Скачать видео</button>
        </a>
        <button class="secondary" onclick="resetApp()">Создать ещё</button>
    </div>

    <div class="footer-note">Генерация обычно занимает 1–3 минуты.</div>
</div>

<script>
let currentTalkId = null;
let finalVideoUrl = null;

function setProgress(percent) {
    document.getElementById("progressBar").style.width = percent + "%";
}

function setStep(step) {
    const avatar = document.getElementById("stepAvatar");
    const voice = document.getElementById("stepVoice");
    const video = document.getElementById("stepVideo");

    avatar.className = "step";
    voice.className = "step";
    video.className = "step";

    if (step === 1) {
        avatar.className = "step active";
        setProgress(20);
    }

    if (step === 2) {
        avatar.className = "step done";
        voice.className = "step active";
        setProgress(45);
    }

    if (step === 3) {
        avatar.className = "step done";
        voice.className = "step done";
        video.className = "step active";
        setProgress(70);
    }

    if (step === 4) {
        avatar.className = "step done";
        voice.className = "step done";
        video.className = "step done";
        setProgress(100);
    }

    if (step === 0) {
        setProgress(0);
    }
}

function toggleCustomTheme() {
    const theme = document.getElementById("theme").value;
    const customTheme = document.getElementById("customTheme");

    if (theme === "custom") {
        customTheme.style.display = "block";
    } else {
        customTheme.style.display = "none";
    }
}

async function generateVideo() {
    const customTheme = document.getElementById("customTheme").value;
    const fileInput = document.getElementById("photo");
    const text = document.getElementById("text").value;
    const voice = document.getElementById("voice").value;
    const format = document.getElementById("format").value;
    const theme = document.getElementById("theme").value;
    const status = document.getElementById("status");
    const video = document.getElementById("video");
    const avatarPreview = document.getElementById("avatarPreview");
    const btn = document.getElementById("generateBtn");
    const actions = document.getElementById("actions");

    if (!fileInput.files.length) {
        alert("Выбери фото");
        return;
    }

    btn.disabled = true;
    actions.className = "actions";
    video.style.display = "none";
    avatarPreview.style.display = "none";
    status.innerText = "";

    try {
        setStep(1);
        status.innerText = "⏳ Создаём AI-аватар...";

        const avatarForm = new FormData();
        avatarForm.append("file", fileInput.files[0]);
        avatarForm.append("theme", theme);
        avatarForm.append("custom_theme", customTheme);

        const avatarResponse = await fetch("/create-3d-avatar/", {
            method: "POST",
            body: avatarForm
        });

        const avatarData = await avatarResponse.json();
        avatarPreview.src = avatarData.avatar_url;
        avatarPreview.style.display = "block";

        if (avatarData.error) {
            throw new Error("Ошибка аватара: " + JSON.stringify(avatarData));
        }

        setStep(2);
        status.innerText = "⏳ Создаём talking video...";
        
        const textForm = new FormData();
        textForm.append("text", text);
        textForm.append("voice", voice);
        textForm.append("format", format);

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

    status.innerText = "⏳ Подготавливаем TikTok/Reels формат...";

    let finalVideoUrl = data.video_url;

    if (document.getElementById("format").value === "vertical") {

        const verticalForm = new FormData();
        verticalForm.append("video_url", data.video_url);

        const verticalResponse = await fetch("/make-vertical/", {
            method: "POST",
            body: verticalForm
        });

        const verticalData = await verticalResponse.json();

        finalVideoUrl = verticalData.vertical_video_url;
    }

    status.innerText = "✅ Готово!";

    video.src = finalVideoUrl;
    video.style.display = "block";

    document.getElementById("downloadLink").href = finalVideoUrl;

    actions.className = "actions show";

    btn.disabled = false;

    return;
}

    status.innerText = "Статус: " + data.status + ". Ждём...";
    setTimeout(checkStatus, 5000);
}

toggleCustomTheme();

function resetApp() {
    currentTalkId = null;
    finalVideoUrl = null;

    document.getElementById("photo").value = "";
    document.getElementById("video").style.display = "none";
    document.getElementById("video").src = "";
    document.getElementById("status").innerText = "";
    document.getElementById("actions").className = "actions";
    document.getElementById("generateBtn").disabled = false;

    setStep(0);
}

function resetApp() {
    document.getElementById("video").style.display = "none";
    document.getElementById("avatarPreview").style.display = "none";
    document.getElementById("status").innerText = "";
    document.getElementById("actions").className = "actions";
    document.getElementById("photo").value = "";
}

</script>
</body>
</html>
"""
