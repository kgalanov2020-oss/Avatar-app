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
    <html>
        <body style="font-family: Arial; padding: 40px;">
            <h1>AI Avatar Video</h1>
            <p>Backend is clean. Reinsert the current frontend HTML here after testing backend endpoints.</p>
        </body>
    </html>
    """
