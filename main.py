from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from moviepy import AudioFileClip, VideoFileClip, CompositeVideoClip, ColorClip
from PIL import Image, ImageOps
from deep_translator import GoogleTranslator

import edge_tts
import shutil
import uuid
import os
import requests
import time
import json

# =============================
# CONFIG
# =============================

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://avatar-app-vcer.onrender.com")
COMFY_URL = os.getenv("COMFY_URL", "https://rc7m4ppm0a2rzs-8188.proxy.runpod.net")
DID_API_KEY = os.getenv("DID_API_KEY")

UPLOAD_DIR = "uploads"
CARTOON_WORKFLOW_PATH = "instantid_cartoon_workflow_api.json"
REALISTIC_WORKFLOW_PATH = "instantid_workflow_api.json"

MAX_TEXT_LENGTH = 250
MAX_AUDIO_DURATION = 15

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")


# =============================
# SAFETY
# =============================

BANNED_WORDS = [
    "nude", "naked", "porn", "sex", "xxx", "nsfw",
    "boobs", "breasts", "nipples", "lingerie", "erotic",
    "fetish", "bdsm", "onlyfans", "child", "kid", "teen sex",
    "incest", "isis", "terrorist", "terrorism", "nazi",
    "hitler", "extremist", "execution", "beheading",
    "gore", "blood", "murder", "dead body"
]


def is_prompt_safe(text: str) -> bool:
    text = text.lower()
    return not any(word in text for word in BANNED_WORDS)


# =============================
# HELPERS
# =============================


def public_file_url(job_id: str, filename: str) -> str:
    return f"{APP_BASE_URL}/files/{job_id}/{filename}"


def prepare_input_image(input_path: str, output_path: str, max_size: int = 1024):
    image = ImageOps.exif_transpose(Image.open(input_path)).convert("RGB")
    image.thumbnail((max_size, max_size))
    image.save(output_path, format="JPEG", quality=95, optimize=True)


def optimize_image_for_did(input_path: str, output_path: str):
    image = ImageOps.exif_transpose(Image.open(input_path)).convert("RGB")
    image.thumbnail((1024, 1024))
    image.save(output_path, format="JPEG", quality=94, optimize=True)


def upload_image_to_comfy(image_path: str) -> str:
    with open(image_path, "rb") as file:
        response = requests.post(
            f"{COMFY_URL}/upload/image",
            files={"image": file},
            timeout=120
        )

    if response.status_code != 200:
        raise RuntimeError(response.text)

    return response.json()["name"]


def run_comfy_workflow(workflow: dict) -> dict:
    response = requests.post(
        f"{COMFY_URL}/prompt",
        json={
            "prompt": workflow,
            "client_id": str(uuid.uuid4())
        },
        timeout=120
    )

    if response.status_code != 200:
        raise RuntimeError(response.text)

    prompt_id = response.json()["prompt_id"]

    for _ in range(180):
        history = requests.get(
            f"{COMFY_URL}/history/{prompt_id}",
            timeout=60
        ).json()

        if prompt_id in history:
            return history[prompt_id]

        time.sleep(1)

    raise TimeoutError("ComfyUI generation timeout")


def download_first_comfy_image(history: dict, output_path: str):
    outputs = history.get("outputs", {})

    for node_output in outputs.values():
        if "images" not in node_output:
            continue

        image_data = node_output["images"][0]

        image_url = (
            f"{COMFY_URL}/view?"
            f"filename={image_data['filename']}"
            f"&subfolder={image_data.get('subfolder', '')}"
            f"&type={image_data.get('type', 'output')}"
        )

        response = requests.get(image_url, timeout=120)

        if response.status_code != 200:
            raise RuntimeError("Failed to download avatar from ComfyUI")

        with open(output_path, "wb") as file:
            file.write(response.content)

        return

    raise RuntimeError("No image output from ComfyUI")


# =============================
# PROMPTS
# =============================

CARTOON_THEMES = {
    "default": "high quality 3D cartoon avatar portrait",
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
    "demon": "3D cartoon dark fantasy demon style, fantasy fire background",
    "pharaoh": "3D cartoon egyptian pharaoh outfit, pyramid background",
    "knight": "3D cartoon medieval knight armor, castle background",
    "racer": "3D cartoon formula one racing suit, racetrack background",
}

REALISTIC_THEMES = {
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
    "demon": "ultra realistic dark fantasy portrait",
    "pharaoh": "ultra realistic egyptian pharaoh portrait",
    "knight": "ultra realistic medieval knight portrait",
    "racer": "ultra realistic formula 1 racer portrait",
}

NEGATIVE_FRAMING = (
    "close-up face, cropped head, giant face, zoomed face, cut forehead, "
    "cut chin, extreme close-up, head out of frame, face out of frame, "
    "wrong gender, different person, different face, deformed face, bad anatomy, "
    "asymmetrical face, blurry, low quality, low resolution, artifacts, glitch, "
    "watermark, text"
)


def get_theme_prompt(theme: str, custom_theme: str, mode: str) -> str:
    if custom_theme and not is_prompt_safe(custom_theme):
        raise ValueError("Unsafe content is not allowed")

    if theme == "custom" and custom_theme.strip():
        if mode == "cartoon":
            return (
                f"high quality 3D cartoon avatar inspired by {custom_theme.strip()}, "
                "preserve exact facial identity, same gender, same age, same face structure"
            )

        return (
            f"ultra realistic portrait inspired by {custom_theme.strip()}, "
            "preserve exact facial identity, same gender, same age, same facial structure"
        )

    if mode == "cartoon":
        return CARTOON_THEMES.get(theme, CARTOON_THEMES["default"])

    return REALISTIC_THEMES.get(theme, REALISTIC_THEMES["default"])


# =============================
# ROUTES
# =============================

@app.get("/")
def root():
    return {"status": "AI Avatar Video server is running"}


@app.post("/create-3d-avatar/")
async def create_3d_avatar(
    file: UploadFile = File(...),
    theme: str = Form("default"),
    custom_theme: str = Form("")
):
    try:
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(UPLOAD_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        raw_input = os.path.join(job_dir, "raw_input.jpg")
        input_path = os.path.join(job_dir, "input.jpg")
        output_path = os.path.join(job_dir, "avatar.png")
        did_output_path = os.path.join(job_dir, "did_avatar.jpg")

        with open(raw_input, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        prepare_input_image(raw_input, input_path)
        comfy_image = upload_image_to_comfy(input_path)
        theme_prompt = get_theme_prompt(theme, custom_theme, "cartoon")

        with open(CARTOON_WORKFLOW_PATH, "r", encoding="utf-8") as file:
            workflow = json.load(file)

        workflow["13"]["inputs"]["image"] = comfy_image
        workflow["2"]["inputs"]["text"] = (
            "high quality 3D cartoon avatar of the exact same person, "
            "preserve exact facial identity, same gender, same age, same face shape, "
            "same eyes, same nose, same lips, same hairstyle, "
            "head fully visible, upper body visible, centered portrait composition, "
            "safe margins around head, not zoomed in, cinematic lighting, "
            "animated movie character, stylized 3D portrait, "
            + theme_prompt
        )
        workflow["3"]["inputs"]["text"] = (
            "nsfw, nude, naked, porn, erotic, realistic photo, horror, creepy, "
            + NEGATIVE_FRAMING
        )
        workflow["5"]["inputs"]["seed"] = int(time.time())

        history = run_comfy_workflow(workflow)
        download_first_comfy_image(history, output_path)
        optimize_image_for_did(output_path, did_output_path)

        return {
            "job_id": job_id,
            "avatar_url": public_file_url(job_id, "avatar.png"),
            "did_avatar_url": public_file_url(job_id, "did_avatar.jpg")
        }

    except Exception as error:
        return {"error": str(error)}


@app.post("/create-realistic-avatar/")
async def create_realistic_avatar(
    file: UploadFile = File(...),
    theme: str = Form("default"),
    custom_theme: str = Form("")
):
    try:
        job_id = str(uuid.uuid4())
        job_dir = os.path.join(UPLOAD_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        raw_input = os.path.join(job_dir, "raw_input.jpg")
        input_path = os.path.join(job_dir, "input.jpg")
        output_path = os.path.join(job_dir, "avatar.png")
        did_output_path = os.path.join(job_dir, "did_avatar.jpg")

        with open(raw_input, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        prepare_input_image(raw_input, input_path)
        comfy_image = upload_image_to_comfy(input_path)
        theme_prompt = get_theme_prompt(theme, custom_theme, "realistic")

        with open(REALISTIC_WORKFLOW_PATH, "r", encoding="utf-8") as file:
            workflow = json.load(file)

        workflow["13"]["inputs"]["image"] = comfy_image
        workflow["2"]["inputs"]["text"] = (
            "ultra realistic cinematic portrait photo of the exact same person "
            "from the uploaded image, preserve exact facial identity, same gender, "
            "same age, same face structure, same eyes, same nose, same lips, "
            "same skin tone, same hairstyle, upper body visible, head fully visible, "
            "centered portrait composition, safe margins around head, professional cinematic framing, "
            "natural skin texture, sharp focus, studio lighting, high detail skin pores, "
            "8k portrait photography, not zoomed in, "
            + theme_prompt
        )
        workflow["3"]["inputs"]["text"] = (
            "nsfw, nude, naked, porn, erotic, "
            + NEGATIVE_FRAMING
        )

        if "20" in workflow:
            workflow["20"]["inputs"]["weight"] = 0.85
            workflow["20"]["inputs"]["start_at"] = 0
            workflow["20"]["inputs"]["end_at"] = 1

        workflow["5"]["inputs"]["seed"] = int(time.time())
        workflow["5"]["inputs"]["steps"] = 40
        workflow["5"]["inputs"]["cfg"] = 5.5
        workflow["5"]["inputs"]["sampler_name"] = "dpmpp_2m"
        workflow["5"]["inputs"]["scheduler"] = "karras"

        history = run_comfy_workflow(workflow)
        download_first_comfy_image(history, output_path)
        optimize_image_for_did(output_path, did_output_path)

        return {
            "job_id": job_id,
            "avatar_url": public_file_url(job_id, "avatar.png"),
            "did_avatar_url": public_file_url(job_id, "did_avatar.jpg")
        }

    except Exception as error:
        return {"error": str(error)}


@app.post("/create-video/")
async def create_video(
    text: str = Form("С днём рождения!"),
    voice: str = Form("ru_female_1"),
    format: str = Form("square"),
    job_id: str = Form("")
):
    if len(text) > MAX_TEXT_LENGTH:
        return {"error": f"Text is too long. Maximum {MAX_TEXT_LENGTH} characters."}

    if len(text.strip()) < 3:
        return {"error": "Text is too short."}

    if not job_id:
        job_id = str(uuid.uuid4())

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    audio_path = os.path.join(job_dir, "audio.mp3")
    audio_url = public_file_url(job_id, "audio.mp3")

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
        "pt_female": {"voice": "pt-BR-FranciscaNeural", "rate": "+0%", "pitch": "+0Hz"},
    }

    profile = voice_profiles.get(voice, voice_profiles["ru_female_1"])

    try:
        if voice in ["en_female", "en_male"]:
            text = GoogleTranslator(source="auto", target="en").translate(text)
        elif voice == "es_female":
            text = GoogleTranslator(source="auto", target="es").translate(text)
        elif voice == "pt_female":
            text = GoogleTranslator(source="auto", target="pt").translate(text)
    except Exception:
        pass

    communicate = edge_tts.Communicate(
        text=text,
        voice=profile["voice"],
        rate=profile["rate"],
        pitch=profile["pitch"]
    )

    try:
        await communicate.save(audio_path)
    except Exception:
        fallback = edge_tts.Communicate(text=text, voice="ru-RU-SvetlanaNeural")
        await fallback.save(audio_path)

    audio_clip = AudioFileClip(audio_path)

    if audio_clip.duration > MAX_AUDIO_DURATION:
        audio_clip.close()
        return {"error": f"Audio is too long. Maximum {MAX_AUDIO_DURATION} seconds."}

    audio_clip.close()

    return {
        "job_id": job_id,
        "audio_url": audio_url,
        "format": format
    }


@app.post("/did-video/")
def did_video(
    avatar_url: str = Form(...),
    audio_url: str = Form(...)
):
    if not DID_API_KEY:
        return {"error": "DID_API_KEY is not set"}

    headers = {
        "Authorization": f"Basic {DID_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "source_url": avatar_url,
        "script": {
            "type": "audio",
            "audio_url": audio_url
        },
        "config": {
            "fluent": True,
            "pad_audio": 0.0,
            "stitch": True
        }
    }

    create_response = requests.post(
        "https://api.d-id.com/talks",
        headers=headers,
        json=payload,
        timeout=60
    )

    if create_response.status_code not in [200, 201]:
        return {
            "error": "D-ID create failed",
            "details": create_response.text
        }

    talk_id = create_response.json().get("id")

    if not talk_id:
        return {
            "error": "No talk_id from D-ID",
            "details": create_response.json()
        }

    for _ in range(120):
        status_response = requests.get(
            f"https://api.d-id.com/talks/{talk_id}",
            headers=headers,
            timeout=60
        )

        data = status_response.json()

        if data.get("status") == "done":
            return {
                "video_url": data.get("result_url"),
                "talk_id": talk_id
            }

        if data.get("status") == "error":
            return {
                "error": "D-ID generation error",
                "details": data
            }

        time.sleep(2)

    return {
        "error": "D-ID timeout",
        "talk_id": talk_id
    }


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

    response = requests.get(video_url, timeout=180)

    if response.status_code != 200:
        return {
            "error": "Failed to download D-ID video",
            "details": response.text
        }

    with open(input_path, "wb") as file:
        file.write(response.content)

    clip = VideoFileClip(input_path)

    background = ColorClip(
        size=(1080, 1920),
        color=(15, 15, 15)
    ).with_duration(clip.duration)

    scale = min(1080 / clip.w, 1920 / clip.h)

    foreground = (
        clip.resized(scale)
        .with_position(("center", "center"))
    )

    final = CompositeVideoClip(
        [background, foreground],
        size=(1080, 1920)
    )

    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        fps=30,
        threads=2,
        bitrate="6000k"
    )

    clip.close()
    final.close()

    return {
        "job_id": job_id,
        "vertical_video_url": public_file_url(job_id, "vertical.mp4")
    }


# =============================
# FRONTEND PLACEHOLDER
# =============================

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

<p class="subtitle">
    Загрузи фото, напиши поздравление — получи говорящее видео с AI-аватаром.
</p>

<div id="creditsBox" class="hint" style="margin-bottom:16px;">
    Credits: <b id="creditsCount">3</b>
</div>

<div class="hint" id="generationCostBox">
    This video will cost: <b id="generationCost">1</b> credit
</div>

<div id="authBox" style="margin-bottom:20px;">

    <div id="loggedOutBox">
        <input type="email" id="email" placeholder="Email" style="margin-bottom:10px;">
        <input type="password" id="password" placeholder="Password" style="margin-bottom:10px;">

        <button id="signUpBtn">Create account</button>

        <button id="loginBtn" class="secondary" style="margin-top:10px;">
            Login
        </button>

        <div class="hint" style="margin-top:10px;">
            New user? Create account. Already registered? Login.
        </div>
    </div>

    <div id="loggedInBox" style="display:none;">
        <div id="currentUser" class="hint" style="margin-top:10px;">
            Logged in
        </div>

        <button id="logoutBtn" class="secondary" style="margin-top:10px;">
            Logout
        </button>
    </div>

<label>Фото</label>

    <input type="file" id="photo" accept="image/*">

    <label>Текст поздравления</label>
    <textarea id="text" maxlength="250">С днём рождения! Желаю счастья, здоровья и исполнения всех желаний!</textarea>
<div class="hint">
    Максимум 250 символов. Лучше 1–2 коротких предложения.
</div>
<div id="charCount">0 / 250</div>
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

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>

<script>

const supabaseClient = window.supabase.createClient(
    "https://yvynivfphhyqriqwpiic.supabase.co",
    "sb_publishable_MSlFLoKbU-DJhWcP5d3wbw_YZQbc-jb"
);

let finalVideoUrl = null;

let creditsLeft = 3;

let currentUser = null;

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

function calculateGenerationCost(styleMode, format) {

    let cost = 1;

    if (styleMode === "realistic") {
        cost += 1;
    }

    if (format === "vertical") {
        cost += 1;
    }

    return cost;
}

function updateGenerationCost() {

    const styleMode =
        document.getElementById("styleMode").value;

    const format =
        document.getElementById("format").value;

    const cost =
        calculateGenerationCost(styleMode, format);

    document.getElementById("generationCost").innerText =
        cost;
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

function updateAuthUI() {
    const loggedOutBox = document.getElementById("loggedOutBox");
    const loggedInBox = document.getElementById("loggedInBox");
    const currentUserBox = document.getElementById("currentUser");

    if (currentUser) {
        loggedOutBox.style.display = "none";
        loggedInBox.style.display = "block";

        currentUserBox.innerText =
            "Logged in as: " + currentUser.email;
    } else {
        loggedOutBox.style.display = "block";
        loggedInBox.style.display = "none";

        currentUserBox.innerText = "Not logged in";
    }
}

async function signUp() {

    const email =
        document.getElementById("email").value;

    const password =
        document.getElementById("password").value;

    const { data, error } =
        await supabaseClient.auth.signUp({
            email,
            password
        });

    if (error) {
        console.error("Sign up error:", error);
        alert("Sign up error: " + error.message);
        return;
    }

    console.log("Sign up data:", data);

    if (data.user) {
        alert("Account created. Now click Login.");
    }

} // ← ВОТ ЭТОГО НЕ ХВАТАЛО

async function login() {

    const email =
        document.getElementById("email").value;

    const password =
        document.getElementById("password").value;

    const { data, error } =
        await supabaseClient.auth.signInWithPassword({
            email,
            password
        });

    if (error) {
        alert(error.message);
        return;
    }

   currentUser = data.user;
   updateAuthUI();
}

async function logout() {

    await supabaseClient.auth.signOut();

    currentUser = null;
    updateAuthUI();
}

async function loadUser() {
    const {
        data: { session }
    } = await supabaseClient.auth.getSession();

    if (session?.user) {
        currentUser = session.user;
    } else {
        currentUser = null;
    }

    updateAuthUI();
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

    const generationCost =
        calculateGenerationCost(styleMode, format);

    if (!currentUser) {
        alert("Please login first");
        return;
    }

    if (text.length > 250) {
        alert("Текст слишком длинный. Максимум 250 символов.");
        return;
    }

    if (text.trim().length < 3) {
        alert("Введите текст поздравления.");
        return;
    }

    if (!fileInput.files.length) {
        alert("Выбери фото");
        return;
    }

    if (creditsLeft < generationCost) {
        alert("Недостаточно credits");
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
        talkForm.append(
            "avatar_url",
            avatarData.did_avatar_url || avatarData.avatar_url
        );
        talkForm.append("audio_url", voiceData.audio_url);

        const talkResponse = await fetch("/did-video/", {
            method: "POST",
            body: talkForm
        });

        const talkData = await talkResponse.json();

        if (!talkData.video_url) {
            throw new Error("Ошибка D-ID: " + JSON.stringify(talkData));
        }

        finalVideoUrl = talkData.video_url;

        if (format === "vertical") {
            status.innerText = "⏳ Создаём vertical video...";

            const verticalForm = new FormData();
            verticalForm.append("video_url", finalVideoUrl);
            verticalForm.append("job_id", jobId);

            const verticalResponse = await fetch("/make-vertical/", {
                method: "POST",
                body: verticalForm
            });

            const verticalData = await verticalResponse.json();

            if (verticalData.error || !verticalData.vertical_video_url) {
                throw new Error("Ошибка vertical video: " + JSON.stringify(verticalData));
            }

            finalVideoUrl = verticalData.vertical_video_url;
        }

        setStep(4);
        status.innerText = "✅ Готово!";

        creditsLeft -= generationCost;

        document.getElementById("creditsCount").innerText =
            creditsLeft;

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

document
    .getElementById("signUpBtn")
    .addEventListener("click", signUp);

document
    .getElementById("loginBtn")
    .addEventListener("click", login);

document
    .getElementById("logoutBtn")
    .addEventListener("click", logout);

document
    .getElementById("styleMode")
    .addEventListener("change", updateGenerationCost);

document
    .getElementById("format")
    .addEventListener("change", updateGenerationCost);

toggleCustomTheme();

updateGenerationCost();

loadUser();

</script>
</body>
</html>
"""
