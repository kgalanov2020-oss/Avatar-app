from fastapi.responses import HTMLResponse
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from moviepy import ImageClip, TextClip, CompositeVideoClip
import edge_tts
import asyncio
from moviepy import AudioFileClip
from moviepy import VideoFileClip, CompositeVideoClip, ColorClip
from deep_translator import GoogleTranslator

import shutil
import uuid
import os
import requests
from PIL import Image, ImageOps
import base64
import time
import json
COMFY_URL = "https://rc7m4ppm0a2rzs-8188.proxy.runpod.net"

print("SERVER VERSION UPDATED")

app = FastAPI()

BANNED_WORDS = [
    # nsfw
    "nude", "naked", "porn", "sex", "xxx", "nsfw",
    "boobs", "breasts", "nipples", "lingerie",
    "erotic", "fetish", "bdsm", "onlyfans",

    # minors / incest
    "child", "kid", "teen sex", "incest",

    # religion
    "allah", "jesus", "muhammad", "prophet",
    "christ", "quran", "bible", "church",
    "mosque", "satanic",

    # terrorism/extremism
    "isis", "terrorist", "terrorism",
    "nazi", "hitler", "extremist",
    "execution", "beheading",

    # violence
    "gore", "blood", "murder", "dead body"
]

def is_prompt_safe(text: str):
    text = text.lower()

    for word in BANNED_WORDS:
        if word in text:
            return False

    return True

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

    if custom_theme and not is_prompt_safe(custom_theme):
        return {"error": "Unsafe content is not allowed"}

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, "input.jpg")
    output_path = os.path.join(job_dir, "avatar.png")

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    with open(input_path, "rb") as f:
        upload_response = requests.post(
            f"{COMFY_URL}/upload/image",
            files={"image": f}
        )

    if upload_response.status_code != 200:
        return {"error": upload_response.text}

    comfy_image = upload_response.json()["name"]

    theme_prompts = {
        "default": "3D cartoon avatar portrait",
        "astronaut": "3D cartoon astronaut suit, cosmic background",
        "cowboy": "3D cartoon cowboy outfit, western desert background",
        "royal": "3D cartoon king or queen outfit, royal palace background",
        "sport": "3D cartoon athlete uniform, stadium background",
        "sailor": "3D cartoon sailor outfit, sea background",
        "samurai": "3D cartoon samurai armor, japanese temple background",
        "cyberpunk": "3D cartoon cyberpunk style, neon futuristic city background",
        "superhero": "3D cartoon superhero costume, cinematic action background",
        "rockstar": "3D cartoon rock star outfit, concert stage background",
        "gangster": "3D cartoon mafia gangster suit, luxury background",
        "pirate": "3D cartoon pirate captain outfit, pirate ship background",
        "wizard": "3D cartoon wizard robe, magical fantasy background",
        "viking": "3D cartoon viking warrior armor, nordic background",
        "ninja": "3D cartoon ninja outfit, dark japanese background",
        "luxury": "3D cartoon billionaire outfit, private jet background",
        "angel": "3D cartoon angel wings, heavenly clouds background",
        "demon": "3D cartoon dark demon style, fantasy fire background",
        "pharaoh": "3D cartoon egyptian pharaoh outfit, pyramid background",
        "knight": "3D cartoon medieval knight armor, castle background",
        "racer": "3D cartoon formula one racing suit, racetrack background"
    }

    if theme == "custom" and custom_theme.strip():
        theme_prompt = (
            f"high quality 3D cartoon avatar inspired by {custom_theme.strip()}, "
            f"preserve exact facial identity, same gender, same age, same face structure"
        )
    else:
        theme_prompt = theme_prompts.get(theme, theme_prompts["default"])

    with open("instantid_cartoon_workflow_api.json", "r", encoding="utf-8") as f:
        workflow = json.load(f)

    workflow["13"]["inputs"]["image"] = comfy_image

    workflow["2"]["inputs"]["text"] = (
        "high quality 3D cartoon avatar of the exact same person, "
        "preserve facial identity, same gender, same age, same face shape, "
        "same eyes, same nose, same lips, same hairstyle, "
        "animated movie character, stylized 3D portrait, cinematic lighting, "
        + theme_prompt
    )

    workflow["3"]["inputs"]["text"] = (
        "nsfw, nude, naked, breasts, nipples, porn, erotic, "
        "wrong gender, different person, deformed face, bad anatomy, ugly, blurry, "
        "realistic photo, horror, creepy, artifacts, glitch, text, watermark"
    )

    workflow["5"]["inputs"]["seed"] = int(time.time())

    response = requests.post(
        f"{COMFY_URL}/prompt",
        json={
            "prompt": workflow,
            "client_id": str(uuid.uuid4())
        }
    )

    if response.status_code != 200:
        return {"error": response.text}

    prompt_id = response.json()["prompt_id"]

    while True:
        history = requests.get(f"{COMFY_URL}/history/{prompt_id}").json()

        if prompt_id in history:
            outputs = history[prompt_id]["outputs"]

            for node_output in outputs.values():
                if "images" in node_output:
                    image_data = node_output["images"][0]

                    image_url = (
                        f"{COMFY_URL}/view?"
                        f"filename={image_data['filename']}"
                        f"&subfolder={image_data.get('subfolder', '')}"
                        f"&type={image_data.get('type', 'output')}"
                    )

                    img = requests.get(image_url)

                    with open(output_path, "wb") as f:
                        f.write(img.content)

                    return {
                        "job_id": job_id,
                        "avatar_url": f"https://avatar-app-vcer.onrender.com/files/{job_id}/avatar.png"
                    }

        time.sleep(1)

@app.post("/create-realistic-avatar/")
async def create_realistic_avatar(
    file: UploadFile = File(...),
    theme: str = Form("default"),
    custom_theme: str = Form("")
):

    if custom_theme and not is_prompt_safe(custom_theme):
        return {"error": "Unsafe content is not allowed"}

    job_id = str(uuid.uuid4())
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, "input.jpg")
    output_path = os.path.join(job_dir, "avatar.png")

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    with open(input_path, "rb") as f:
        upload_response = requests.post(
            f"{COMFY_URL}/upload/image",
            files={"image": f}
        )

    if upload_response.status_code != 200:
        return {"error": upload_response.text}

    comfy_image = upload_response.json()["name"]

    theme_prompts = {
        "default": "ultra realistic cinematic portrait",
        "astronaut": "ultra realistic astronaut portrait, cinematic sci-fi lighting",
        "cowboy": "ultra realistic cowboy portrait, western desert background",
        "royal": "ultra realistic king or queen portrait, royal palace background",
        "sport": "ultra realistic athlete portrait, stadium background",
        "sailor": "ultra realistic sailor portrait, ocean background",
        "samurai": "ultra realistic samurai portrait",
        "cyberpunk": "ultra realistic cyberpunk portrait, neon city background",
        "superhero": "ultra realistic superhero portrait",
        "rockstar": "ultra realistic rockstar portrait",
        "gangster": "ultra realistic mafia portrait",
        "pirate": "ultra realistic pirate captain portrait",
        "wizard": "ultra realistic wizard portrait",
        "viking": "ultra realistic viking warrior portrait",
        "ninja": "ultra realistic ninja portrait",
        "luxury": "ultra realistic billionaire portrait",
        "angel": "ultra realistic angel portrait",
        "demon": "ultra realistic dark demon portrait",
        "pharaoh": "ultra realistic egyptian pharaoh portrait",
        "knight": "ultra realistic medieval knight portrait",
        "racer": "ultra realistic formula 1 racer portrait"
    }

    if theme == "custom" and custom_theme.strip():
        theme_prompt = (
            f"ultra realistic portrait inspired by {custom_theme.strip()}, "
            f"preserve exact facial identity, same gender, same age, same facial structure"
        )
    else:
        theme_prompt = theme_prompts.get(theme, theme_prompts["default"])

    with open("instantid_workflow_api.json", "r", encoding="utf-8") as f:
        workflow = json.load(f)

    workflow["13"]["inputs"]["image"] = comfy_image

    workflow["2"]["inputs"]["text"] = (
        "realistic portrait photo of the exact same person from the uploaded image, "
        "preserve facial identity, same gender, same age, same face shape, "
        "same eyes, same nose, same lips, same skin tone, same hairstyle, "
        "natural human face, realistic skin texture, sharp focus, cinematic lighting, "
        + theme_prompt
    )

    workflow["3"]["inputs"]["text"] = (
        "nsfw, nude, naked, breasts, nipples, porn, erotic, wrong gender, "
        "different person, different face, deformed face, bad anatomy, ugly, blurry, "
        "artifacts, glitch, pixel noise, scanlines, dots, watermark, text"
    )

    workflow["20"]["inputs"]["weight"] = 0.85
    workflow["20"]["inputs"]["start_at"] = 0
    workflow["20"]["inputs"]["end_at"] = 1

    workflow["5"]["inputs"]["seed"] = int(time.time())
    workflow["5"]["inputs"]["steps"] = 30
    workflow["5"]["inputs"]["cfg"] = 3.5
    workflow["5"]["inputs"]["sampler_name"] = "dpmpp_2m"
    workflow["5"]["inputs"]["scheduler"] = "karras"

    response = requests.post(
        f"{COMFY_URL}/prompt",
        json={
            "prompt": workflow,
            "client_id": str(uuid.uuid4())
        }
    )

    if response.status_code != 200:
        return {"error": response.text}

    prompt_id = response.json()["prompt_id"]

    while True:
        history = requests.get(f"{COMFY_URL}/history/{prompt_id}").json()

        if prompt_id in history:
            outputs = history[prompt_id]["outputs"]

            for node_output in outputs.values():
                if "images" in node_output:
                    image_data = node_output["images"][0]

                    image_url = (
                        f"{COMFY_URL}/view?"
                        f"filename={image_data['filename']}"
                        f"&subfolder={image_data.get('subfolder', '')}"
                        f"&type={image_data.get('type', 'output')}"
                    )

                    img = requests.get(image_url)

                    with open(output_path, "wb") as f:
                        f.write(img.content)

                    return {
                        "job_id": job_id,
                        "avatar_url": f"https://avatar-app-vcer.onrender.com/files/{job_id}/avatar.png"
                    }

        time.sleep(1)

@app.post("/create-video/")
async def create_video(
    text: str = Form("С днём рождения!"),
    voice: str = Form("ru_female_1"),
    format: str = Form("square"),
    job_id: str = Form("")
):

    if not job_id:
        job_id = str(uuid.uuid4())

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    audio_path = os.path.join(job_dir, "audio.mp3")
    audio_url = f"https://avatar-app-vcer.onrender.com/files/{job_id}/audio.mp3"

    voice_profiles = {
        "ru_female_1": {"voice": "ru-RU-SvetlanaNeural", "rate": "+0%", "pitch": "+0Hz"},
        "ru_female_2": {"voice": "ru-RU-SvetlanaNeural", "rate": "-5%", "pitch": "+2Hz"},
        "ru_male_1": {"voice": "ru-RU-DmitryNeural", "rate": "+0%", "pitch": "+0Hz"},
        "ru_male_2": {"voice": "ru-RU-DmitryNeural", "rate": "-8%", "pitch": "-2Hz"},
        "girl": {"voice": "ru-RU-SvetlanaNeural", "rate": "+15%", "pitch": "+8Hz"},
        "boy": {"voice": "ru-RU-DmitryNeural", "rate": "+12%", "pitch": "+6Hz"},
        "grandma": {"voice": "ru-RU-SvetlanaNeural", "rate": "-18%", "pitch": "-6Hz"},
        "grandpa": {"voice": "ru-RU-DmitryNeural", "rate": "-20%", "pitch": "-8Hz"},
        "en_female": {"voice": "en-US-JennyNeural", "rate": "+0%", "pitch": "+0Hz"},
        "en_male": {"voice": "en-US-GuyNeural", "rate": "+0%", "pitch": "+0Hz"},
        "es_female": {"voice": "es-ES-ElviraNeural", "rate": "+0%", "pitch": "+0Hz"},
        "pt_female": {"voice": "pt-BR-FranciscaNeural", "rate": "+0%", "pitch": "+0Hz"}
    }

    profile = voice_profiles.get(voice, voice_profiles["ru_female_1"])

    if voice in ["en_female", "en_male"]:
        text = GoogleTranslator(source="auto", target="en").translate(text)
    elif voice == "es_female":
        text = GoogleTranslator(source="auto", target="es").translate(text)
    elif voice == "pt_female":
        text = GoogleTranslator(source="auto", target="pt").translate(text)

    communicate = edge_tts.Communicate(
        text=text,
        voice=profile["voice"],
        rate=profile["rate"],
        pitch=profile["pitch"]
    )

    try:
        await communicate.save(audio_path)
    except Exception:
        communicate = edge_tts.Communicate(
            text=text,
            voice="ru-RU-SvetlanaNeural"
        )
        await communicate.save(audio_path)

    return {
        "job_id": job_id,
        "audio_url": audio_url,
        "format": format
    }

TALKING_API_URL = "https://9rwq73ke4rr9fe-8000.proxy.runpod.net/generate-video"

@app.post("/talking-video/")
def talking_video(
    avatar_url: str = Form(...),
    audio_url: str = Form(...)
):
    response = requests.post(
        TALKING_API_URL,
        json={
            "avatar_url": avatar_url,
            "audio_url": audio_url
        },
        timeout=600
    )

    return response.json()

@app.post("/make-vertical/")
async def make_vertical(
    video_url: str = Form(...),
    job_id: str = Form("")
):

    if not job_id:
        job_id = str(uuid.uuid4())

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, "input_video.mp4")
    output_path = os.path.join(job_dir, "vertical.mp4")

    video_response = requests.get(video_url)

    with open(input_path, "wb") as f:
        f.write(video_response.content)

    clip = VideoFileClip(input_path)

    background = ColorClip(
        size=(540, 960),
        color=(15, 15, 15)
    ).with_duration(clip.duration)

    foreground = (
        clip.resized(width=540)
        .with_position(("center", "center"))
    )

    final = CompositeVideoClip(
        [background, foreground],
        size=(540, 960)
    )

    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        fps=24,
        threads=2
    )

    clip.close()
    final.close()

    return {
        "job_id": job_id,
        "vertical_video_url": f"https://avatar-app-vcer.onrender.com/files/{job_id}/vertical.mp4"
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

    <label>Стиль</label>

    <select id="styleMode">
        <option value="cartoon">Cartoon</option>
        <option value="realistic">Realistic</option>
    </select>

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

    <option value="ru_female_1">
        🇷🇺 Женский 1
    </option>

    <option value="ru_female_2">
        🇷🇺 Женский 2
    </option>

    <option value="ru_male_1">
        🇷🇺 Мужской 1
    </option>

    <option value="ru_male_2">
        🇷🇺 Мужской 2
    </option>

    <option value="girl">
        👧 Девочка
    </option>

    <option value="boy">
        👦 Мальчик
    </option>

    <option value="grandma">
        👵 Бабушка
    </option>

    <option value="grandpa">
        👴 Дедушка
    </option>

    <option value="en_female">
        🇺🇸 English Female
    </option>

    <option value="en_male">
        🇺🇸 English Male
    </option>

    <option value="es_female">
        🇪🇸 Español Female
    </option>

    <option value="pt_female">
        🇧🇷 Português Female
    </option>

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
    const styleMode = document.getElementById("styleMode").value;
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

        let avatarEndpoint = "/create-3d-avatar/";

        if (styleMode === "realistic") {
            avatarEndpoint = "/create-realistic-avatar/";
        }

        const avatarResponse = await fetch(avatarEndpoint, {
            method: "POST",
            body: avatarForm
        });

        const avatarData = await avatarResponse.json();

        if (avatarData.error || !avatarData.avatar_url) {
            throw new Error("Ошибка аватара: " + JSON.stringify(avatarData));
        }

        const jobId = avatarData.job_id;

        status.innerText = "✅ Аватар готов";
        avatarPreview.src = avatarData.avatar_url;
        avatarPreview.style.display = "block";

        setStep(2);
        status.innerText = "⏳ Создаём голос...";

        const textForm = new FormData();
        textForm.append("text", text);
        textForm.append("voice", voice);
        textForm.append("format", format);
        textForm.append("job_id", jobId);

        const voiceResponse = await fetch("/create-video/", {
            method: "POST",
            body: textForm
        });

        const voiceData = await voiceResponse.json();

        if (voiceData.error || !voiceData.audio_url) {
            throw new Error("Ошибка голоса: " + JSON.stringify(voiceData));
        }

        setStep(3);
        status.innerText = "⏳ Запускаем говорящую анимацию...";

        const talkForm = new FormData();
        talkForm.append("avatar_url", avatarData.avatar_url);
        talkForm.append("audio_url", voiceData.audio_url);

        const talkResponse = await fetch("/talking-video/", {
            method: "POST",
            body: talkForm
        });

        const talkData = await talkResponse.json();

if (!talkData.video_url) {
    throw new Error("Не получили video_url. Ответ сервера: " + JSON.stringify(talkData));
}

finalVideoUrl = talkData.video_url;

if (format === "vertical") {
    const verticalForm = new FormData();
    verticalForm.append("video_url", finalVideoUrl);
    verticalForm.append("job_id", jobId);

    const verticalResponse = await fetch("/make-vertical/", {
        method: "POST",
        body: verticalForm
    });

    const verticalData = await verticalResponse.json();
    finalVideoUrl = verticalData.vertical_video_url;
}

setStep(4);
status.innerText = "✅ Готово!";
video.src = finalVideoUrl;
video.style.display = "block";
document.getElementById("downloadLink").href = finalVideoUrl;
actions.className = "actions show";
btn.disabled = false;

    } catch (error) {
        status.innerText = error.message;
        btn.disabled = false;
    }
}

toggleCustomTheme();

function resetApp() {

    finalVideoUrl = null;

    document.getElementById("photo").value = "";
    document.getElementById("video").style.display = "none";
    document.getElementById("video").src = "";
    document.getElementById("avatarPreview").style.display = "none";
    document.getElementById("status").innerText = "";
    document.getElementById("actions").className = "actions";
    document.getElementById("generateBtn").disabled = false;

    setStep(0);
}

</script>
</body>
</html>
"""
