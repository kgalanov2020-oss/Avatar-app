from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.responses import FileResponse, Response
from fastapi import Header
from supabase import create_client

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
from fastapi.responses import HTMLResponse

# =============================
# CONFIG
# =============================

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://avatar-app-vcer.onrender.com")
COMFY_URL = os.getenv("COMFY_URL", "https://rc7m4ppm0a2rzs-8188.proxy.runpod.net")
DID_API_KEY = os.getenv("DID_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

UPLOAD_DIR = "uploads"
CARTOON_WORKFLOW_PATH = "instantid_cartoon_workflow_api.json"
REALISTIC_WORKFLOW_PATH = "instantid_workflow_api.json"

MAX_TEXT_LENGTH = 250
MAX_AUDIO_DURATION = 15

supabase_admin = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/files/{job_id}/{filename}")
def get_file(job_id: str, filename: str):
    file_path = os.path.join(UPLOAD_DIR, job_id, filename)

    if not os.path.exists(file_path):
        return {"error": "file not found", "path": file_path}

    return FileResponse(file_path)

@app.post("/use-credit/")
def use_credit(authorization: str = Header(None)):
    if not authorization:
        return {"error": "Missing authorization header"}

    token = authorization.replace("Bearer ", "")

    user_response = supabase_admin.auth.get_user(token)

    if not user_response.user:
        return {"error": "Invalid user"}

    user_id = user_response.user.id

    profile_response = (
        supabase_admin
        .table("profiles")
        .select("credits")
        .eq("id", user_id)
        .single()
        .execute()
    )

    credits = profile_response.data["credits"]

    if credits <= 0:
        return {"error": "Not enough credits"}

    new_credits = credits - 1

    (
        supabase_admin
        .table("profiles")
        .update({"credits": new_credits})
        .eq("id", user_id)
        .execute()
    )

    return {
        "success": True,
        "credits": new_credits
    }

@app.head("/files/{job_id}/{filename}")
def head_file(job_id: str, filename: str):
    file_path = os.path.join(UPLOAD_DIR, job_id, filename)

    if not os.path.exists(file_path):
        return Response(status_code=404)

    return Response(status_code=200)

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
    "default": (
        "high quality colorful 3D cartoon avatar portrait, "
        "detailed outfit, cinematic background, vibrant lighting, "
        "pixar style, stylized character, beautiful composition"
    ),

    "astronaut": (
        "3D cartoon astronaut wearing a detailed white space suit with patches, "
        "NASA style details, helmet collar, cosmic background, stars, planets, "
        "cinematic sci-fi lighting, vibrant colors, pixar style"
    ),

    "cowboy": (
        "3D cartoon cowboy wearing leather jacket, cowboy hat, "
        "western shirt, desert background, sunset lighting, "
        "cinematic western style, detailed costume"
    ),

    "royal": (
        "3D cartoon king or queen wearing royal crown, luxury robe, "
        "gold embroidery, palace background, elegant cinematic lighting, "
        "rich details, luxury atmosphere"
    ),

    "sport": (
        "3D cartoon professional athlete wearing detailed sports uniform, "
        "stadium background, dramatic lights, energetic pose, "
        "colorful cinematic sports style"
    ),

    "sailor": (
        "3D cartoon sailor wearing navy sailor uniform, captain hat, "
        "ocean background, sunset sea, detailed nautical symbols, "
        "cinematic lighting, anime inspired style"
    ),

    "samurai": (
        "3D cartoon samurai wearing detailed armor, japanese temple background, "
        "cherry blossoms, dramatic cinematic lighting"
    ),

    "cyberpunk": (
        "3D cartoon cyberpunk character wearing futuristic jacket, "
        "neon city background, glowing lights, high tech details, "
        "colorful cinematic bladerunner style"
    ),

    "superhero": (
        "3D cartoon superhero wearing heroic costume, cape, chest emblem, "
        "detailed suit armor, dramatic city skyline background, "
        "action movie lighting, powerful heroic pose, marvel inspired"
    ),

    "rockstar": (
        "3D cartoon rock star wearing leather jacket, sunglasses, "
        "concert stage background, colorful spotlights, microphone, "
        "energetic cinematic lighting"
    ),

    "gangster": (
        "3D cartoon 1920s mafia gangster wearing pinstripe suit, "
        "fedora hat, luxury vintage background, cinematic noir lighting"
    ),

    "pirate": (
        "3D cartoon pirate captain wearing pirate coat, hat, gold accessories, "
        "pirate ship background, ocean adventure lighting"
    ),

    "wizard": (
        "3D cartoon wizard wearing magical robe, glowing staff, "
        "fantasy castle background, magical particles, cinematic fantasy lighting"
    ),

    "viking": (
        "3D cartoon viking warrior wearing fur armor, nordic symbols, "
        "snowy mountain background, dramatic cinematic lighting"
    ),

    "ninja": (
        "3D cartoon ninja wearing dark ninja outfit, japanese night background, "
        "moonlight, cinematic action pose"
    ),

    "luxury": (
        "3D cartoon billionaire wearing luxury suit, private jet background, "
        "gold accents, cinematic premium lighting"
    ),

    "angel": (
        "3D cartoon angel with white wings, glowing halo, "
        "heavenly clouds background, soft cinematic lighting"
    ),

    "demon": (
        "3D cartoon dark fantasy demon style, horns, fantasy armor, "
        "fire background, dramatic cinematic lighting"
    ),

    "pharaoh": (
        "3D cartoon egyptian pharaoh wearing gold headdress, "
        "ancient egypt jewelry, pyramid background, desert sunset lighting"
    ),

    "knight": (
        "3D cartoon medieval knight wearing shiny armor, "
        "castle background, heroic cinematic lighting"
    ),

    "racer": (
        "3D cartoon formula one racer wearing detailed racing suit, "
        "helmet under arm, racetrack background, cinematic speed lighting"
    ),
}


REALISTIC_THEMES = {
    "default": (
        "ultra realistic cinematic portrait, highly detailed face, "
        "professional photography, dramatic lighting, depth of field, "
        "luxury background, realistic skin texture, cinematic movie still, "
        "85mm lens, volumetric lighting"
    ),

    "astronaut": (
        "ultra realistic astronaut portrait, detailed white NASA style space suit, "
        "realistic fabric textures, cinematic sci-fi lighting, stars and space background, "
        "professional photography, cinematic movie still, 85mm lens, ultra detailed"
    ),

    "cowboy": (
        "ultra realistic cowboy portrait, leather jacket, cowboy hat, "
        "western desert background, sunset cinematic lighting, "
        "rugged realistic style, cinematic movie still"
    ),

    "royal": (
        "ultra realistic king or queen portrait, luxury royal outfit, "
        "gold embroidery, crown, palace interior, cinematic luxury lighting, "
        "professional photography"
    ),

    "sport": (
        "ultra realistic athlete portrait, detailed sports uniform, "
        "stadium lights, energetic cinematic sports photography"
    ),

    "sailor": (
        "ultra realistic sailor portrait, detailed navy uniform, "
        "ocean sunset background, cinematic maritime photography"
    ),

    "samurai": (
        "ultra realistic samurai warrior portrait, detailed armor, "
        "japanese temple background, cinematic dramatic lighting"
    ),

    "cyberpunk": (
        "ultra realistic cyberpunk portrait, futuristic neon jacket, "
        "glowing city lights, cinematic bladerunner atmosphere"
    ),

    "superhero": (
        "ultra realistic superhero portrait, cinematic superhero suit, "
        "cape, chest emblem, dramatic city skyline background, "
        "marvel movie lighting, cinematic movie still, "
        "professional photography, 85mm lens, depth of field, "
        "high detail, volumetric lighting"
    ),

    "rockstar": (
        "ultra realistic rockstar portrait, leather jacket, "
        "concert stage lights, cinematic music video atmosphere"
    ),

    "gangster": (
        "ultra realistic mafia gangster portrait, luxury italian suit, "
        "fedora hat, vintage noir cinematic lighting"
    ),

    "pirate": (
        "ultra realistic pirate captain portrait, detailed pirate coat, "
        "ocean ship background, cinematic adventure lighting"
    ),

    "wizard": (
        "ultra realistic fantasy wizard portrait, magical robe, "
        "glowing staff, cinematic fantasy environment"
    ),

    "viking": (
        "ultra realistic viking warrior portrait, fur armor, "
        "nordic style, snowy cinematic background"
    ),

    "ninja": (
        "ultra realistic ninja portrait, dark tactical ninja suit, "
        "moonlight cinematic action lighting"
    ),

    "luxury": (
        "ultra realistic billionaire portrait, luxury suit, "
        "private jet background, cinematic premium photography"
    ),

    "angel": (
        "ultra realistic angel portrait, glowing wings, "
        "heavenly clouds, soft cinematic lighting"
    ),

    "demon": (
        "ultra realistic dark fantasy demon portrait, "
        "cinematic fire background, dramatic shadows"
    ),

    "pharaoh": (
        "ultra realistic egyptian pharaoh portrait, gold jewelry, "
        "pyramids background, cinematic desert sunset"
    ),

    "knight": (
        "ultra realistic medieval knight portrait, steel armor, "
        "castle background, dramatic cinematic lighting"
    ),

    "racer": (
        "ultra realistic formula one racer portrait, "
        "detailed racing suit, racetrack lights, cinematic speed atmosphere"
    ),
}


NEGATIVE_FRAMING = (
    "close-up face, cropped head, giant face, zoomed face, cut forehead, "
    "cut chin, extreme close-up, head out of frame, face out of frame, "
    "wrong gender, different person, different face, deformed face, "
    "bad anatomy, asymmetrical face, blurry, low quality, "
    "low resolution, artifacts, glitch, watermark, "
    "random letters, unreadable text"
)


REALISTIC_NEGATIVE = (
    "low quality, blurry, deformed face, bad anatomy, cartoon, anime, "
    "extra fingers, ugly eyes, distorted mouth, unrealistic skin, "
    "watermark, text artifacts"
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

@app.get("/oferta", response_class=HTMLResponse)
async def oferta():
    return """
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Пользовательское соглашение</title>
        <style>
            body{max-width:900px;margin:40px auto;padding:20px;font-family:Arial,sans-serif;line-height:1.7;color:#111;}
            h1,h2{margin-top:34px;}
        </style>
    </head>
    <body>

    <h1>Пользовательское соглашение</h1>

    <p>
        Настоящее Пользовательское соглашение регулирует порядок использования сервиса
        AI Avatar Video, расположенного по адресу https://avatar-app-vcer.onrender.com.
    </p>

    <p>
        Используя сервис, проходя регистрацию, загружая изображения, вводя текст,
        оплачивая услуги или нажимая кнопки согласия, Пользователь подтверждает,
        что полностью ознакомился с настоящим Пользовательским соглашением
        и Политикой конфиденциальности, понимает их содержание и принимает их условия.
    </p>

    <p>
        Если Пользователь не согласен с настоящим Пользовательским соглашением
        или Политикой конфиденциальности, он обязан немедленно прекратить
        использование сервиса.
    </p>

    <h2>1. Исполнитель</h2>

    <p>
        Исполнитель: Индивидуальный предприниматель Галанов Константин Николаевич<br>
        ИНН: 563901816803<br>
        Электронная почта: galanovkn@yandex.ru
    </p>

    <h2>2. Описание сервиса</h2>

    <p>
        Сервис AI Avatar Video предоставляет Пользователю возможность создавать
        изображения, аватары, аудиозаписи и видеоролики с использованием
        программных средств автоматической генерации.
    </p>

    <p>
        Результат работы сервиса зависит от исходных данных Пользователя,
        технического состояния внешних сервисов, качества изображения,
        текста, выбранных настроек и иных факторов.
    </p>

    <h2>3. Кредиты и оплата</h2>

    <p>
        Кредиты являются внутренней виртуальной единицей сервиса
        и используются для генерации контента.
    </p>

    <p>
        1 генерация = 1 кредит, если иное прямо не указано на сайте.
    </p>

    <p>
        Кредиты не являются денежными средствами, не являются электронными
        денежными средствами, не подлежат обмену, выводу или передаче третьим лицам.
    </p>

    <p>
        После успешной оплаты кредиты автоматически начисляются
        на аккаунт Пользователя.
    </p>

    <h2>4. Порядок получения услуги</h2>

    <p>
        После оплаты и начисления кредитов Пользователь может использовать их
        для создания AI-видео и AI-аватаров внутри сервиса.
    </p>

    <p>
        Результат генерации предоставляется в цифровом виде через интерфейс сайта.
        Физическая доставка не осуществляется.
    </p>

    <h2>5. Права и обязанности Пользователя</h2>

    <p>
        Пользователь обязуется предоставлять только те изображения, тексты
        и иные материалы, на использование которых у него есть необходимые права
        и согласия.
    </p>

    <p>
        Пользователь несёт полную ответственность за содержание загружаемых
        материалов и за последствия их использования.
    </p>

    <p>
        Запрещается использовать сервис для:
    </p>

    <ul>
        <li>нарушения законодательства Российской Федерации;</li>
        <li>нарушения прав третьих лиц;</li>
        <li>создания незаконного, оскорбительного или вредоносного контента;</li>
        <li>выдачи себя за другое лицо без его согласия;</li>
        <li>мошенничества или введения других лиц в заблуждение;</li>
        <li>создания материалов сексуального, экстремистского или насильственного характера;</li>
        <li>обработки изображений несовершеннолетних без законных оснований.</li>
    </ul>

    <h2>6. Искусственный интеллект и результат генерации</h2>

    <p>
        Пользователь понимает, что результат генерации создаётся автоматически
        и может отличаться от ожиданий Пользователя.
    </p>

    <p>
        Исполнитель не гарантирует точное сходство изображения,
        идеальное качество, отсутствие ошибок, дефектов, искажений,
        неточностей или нежелательных элементов.
    </p>

    <h2>7. Передача данных внешним сервисам</h2>

    <p>
        Пользователь понимает и соглашается, что для работы сервиса
        загруженные изображения, тексты, аудиоданные и иные технические данные
        могут передаваться внешним сервисам, подрядчикам и платформам обработки данных.
    </p>

    <p>
        Без такой передачи данных сервис не может функционировать.
        Если Пользователь не согласен с передачей данных, он обязан
        не использовать сервис.
    </p>

    <h2>8. Ограничение ответственности</h2>

    <p>
        Сервис предоставляется по принципу «как есть».
    </p>

    <p>
        Исполнитель не гарантирует бесперебойную работу сервиса,
        отсутствие ошибок, постоянную доступность сайта, сохранность всех файлов
        и соответствие результата ожиданиям Пользователя.
    </p>

    <p>
        Исполнитель не несёт ответственности за сбои внешних сервисов,
        платёжных систем, хостинга, сетей связи, сервисов генерации изображений,
        речи или видео.
    </p>

    <p>
        Максимальная ответственность Исполнителя ограничивается суммой,
        фактически уплаченной Пользователем за услуги сервиса за последние 30 дней.
    </p>

    <h2>9. Блокировка доступа</h2>

    <p>
        Исполнитель вправе ограничить или заблокировать доступ Пользователя
        к сервису при нарушении настоящего соглашения, подозрении на злоупотребление,
        незаконное использование или нарушение прав третьих лиц.
    </p>

    <h2>10. Возвраты</h2>

    <p>
        Возврат денежных средств возможен в случаях, предусмотренных
        законодательством Российской Федерации.
    </p>

    <p>
        Если кредиты были использованы для генерации контента,
        услуга считается оказанной в соответствующей части.
    </p>

    <h2>11. Изменение условий</h2>

    <p>
        Исполнитель вправе изменять настоящее соглашение.
        Новая редакция вступает в силу с момента публикации на сайте.
    </p>

    <h2>12. Контакты</h2>

    <p>
        ИП Галанов Константин Николаевич<br>
        ИНН: 563901816803<br>
        Электронная почта: galanovkn@yandex.ru
    </p>

    </body>
    </html>
    """

@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return """
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Политика конфиденциальности</title>
        <style>
            body{max-width:900px;margin:40px auto;padding:20px;font-family:Arial,sans-serif;line-height:1.7;color:#111;}
            h1,h2{margin-top:34px;}
        </style>
    </head>
    <body>

    <h1>Политика конфиденциальности</h1>

    <p>
        Настоящая Политика конфиденциальности определяет порядок сбора,
        хранения, использования, передачи и защиты персональных данных
        пользователей сервиса AI Avatar Video.
    </p>

    <p>
        Используя сервис, проходя регистрацию, загружая изображения,
        вводя текст, оплачивая услуги или ставя отметку о согласии,
        Пользователь подтверждает, что ознакомлен и согласен
        с настоящей Политикой конфиденциальности и Пользовательским соглашением.
    </p>

    <p>
        Если Пользователь не согласен с настоящей Политикой конфиденциальности,
        он обязан прекратить использование сервиса.
    </p>

    <h2>1. Оператор персональных данных</h2>

    <p>
        Оператор: Индивидуальный предприниматель Галанов Константин Николаевич<br>
        ИНН: 563901816803<br>
        Электронная почта: galanovkn@yandex.ru
    </p>

    <h2>2. Какие данные обрабатываются</h2>

    <p>
        Сервис может собирать и обрабатывать следующие данные:
    </p>

    <ul>
        <li>адрес электронной почты;</li>
        <li>идентификатор аккаунта пользователя;</li>
        <li>загруженные изображения;</li>
        <li>тексты, введённые пользователем для генерации;</li>
        <li>созданные изображения, аудиозаписи и видеоролики;</li>
        <li>сведения о количестве кредитов;</li>
        <li>сведения об оплатах;</li>
        <li>IP-адрес;</li>
        <li>технические данные устройства, браузера и соединения;</li>
        <li>действия пользователя внутри сервиса.</li>
    </ul>

    <h2>3. Цели обработки данных</h2>

    <p>
        Данные обрабатываются для:
    </p>

    <ul>
        <li>регистрации и входа пользователя;</li>
        <li>работы аккаунта пользователя;</li>
        <li>создания AI-аватаров и AI-видео;</li>
        <li>начисления и списания кредитов;</li>
        <li>приёма платежей;</li>
        <li>технической поддержки;</li>
        <li>предотвращения злоупотреблений;</li>
        <li>улучшения работы сервиса;</li>
        <li>исполнения требований законодательства.</li>
    </ul>

    <h2>4. Передача данных третьим лицам</h2>

    <p>
        Пользователь понимает и соглашается, что для функционирования сервиса
        персональные данные и пользовательские материалы могут передаваться
        третьим лицам и внешним сервисам обработки данных.
    </p>

    <p>
        К таким сервисам могут относиться:
    </p>

    <ul>
        <li>сервисы регистрации и авторизации пользователей;</li>
        <li>сервисы хранения данных;</li>
        <li>сервисы генерации изображений;</li>
        <li>сервисы генерации речи;</li>
        <li>сервисы генерации видео;</li>
        <li>платёжные системы;</li>
        <li>хостинг-провайдеры;</li>
        <li>сервисы технической аналитики и безопасности.</li>
    </ul>

    <p>
        Без передачи данных таким сервисам работа AI Avatar Video невозможна.
        Если Пользователь не согласен с такой передачей данных,
        он обязан не использовать сервис.
    </p>

    <h2>5. Согласие на обработку персональных данных</h2>

    <p>
        При регистрации Пользователь ставит отдельную отметку,
        подтверждающую согласие с Пользовательским соглашением,
        Политикой конфиденциальности, обработкой персональных данных
        и передачей данных третьим лицам для работы сервиса.
    </p>

    <p>
        Пользователь вправе отозвать согласие,
        направив обращение на электронную почту Оператора.
        При отзыве согласия дальнейшее использование сервиса может стать невозможным.
    </p>

    <h2>6. Хранение данных</h2>

    <p>
        Данные хранятся в течение срока, необходимого для работы сервиса,
        исполнения обязательств перед Пользователем, соблюдения требований закона
        и защиты прав Оператора.
    </p>

    <p>
        Загруженные и созданные файлы могут храниться временно
        и могут быть удалены автоматически или вручную.
    </p>

    <h2>7. Безопасность данных</h2>

    <p>
        Оператор принимает разумные организационные и технические меры
        для защиты данных от неправомерного доступа, изменения, раскрытия
        или уничтожения.
    </p>

    <p>
        При этом Пользователь понимает, что ни один способ передачи данных
        через сеть Интернет не может быть абсолютно безопасным.
    </p>

    <h2>8. Права пользователя</h2>

    <p>
        Пользователь вправе запросить информацию о своих данных,
        потребовать уточнения, ограничения обработки или удаления данных
        в случаях, предусмотренных законодательством Российской Федерации.
    </p>

    <h2>9. Файлы cookie и технические данные</h2>

    <p>
        Сервис может использовать файлы cookie и аналогичные технологии
        для авторизации, сохранения сессии, обеспечения безопасности
        и улучшения работы сайта.
    </p>

    <h2>10. Изменение политики</h2>

    <p>
        Оператор вправе изменять настоящую Политику конфиденциальности.
        Новая редакция вступает в силу с момента публикации на сайте.
    </p>

    <h2>11. Контакты</h2>

    <p>
        ИП Галанов Константин Николаевич<br>
        ИНН: 563901816803<br>
        Электронная почта: galanovkn@yandex.ru
    </p>

    </body>
    </html>
    """

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
        import traceback

        full_error = traceback.format_exc()
        print("CREATE AVATAR ERROR:")
        print(full_error)

        return {
            "error": repr(error),
            "traceback": full_error
        }


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
        import traceback

        full_error = traceback.format_exc()
        print("CREATE AVATAR ERROR:")
        print(full_error)

        return {
            "error": repr(error),
            "traceback": full_error
        }


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

@app.post("/make-square/")
async def make_square(
    video_url: str = Form(...),
    job_id: str = Form("")
):
    import subprocess
    import imageio_ffmpeg

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    if not job_id:
        job_id = str(uuid.uuid4())

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, "input_square.mp4")
    output_path = os.path.join(job_dir, "square.mp4")

    response = requests.get(video_url, timeout=180)

    if response.status_code != 200:
        return {
            "error": "Failed to download video",
            "details": response.text[:500]
        }

    with open(input_path, "wb") as file:
        file.write(response.content)

    command = [
        ffmpeg_path,
        "-y",
        "-i", input_path,
        "-vf",
        "scale=1024:1024:force_original_aspect_ratio=decrease,"
        "pad=1024:1024:(ow-iw)/2:(oh-ih)/2:color=black",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "24",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        return {
            "error": "ffmpeg square failed",
            "details": result.stderr[-1000:]
        }

    return {
        "job_id": job_id,
        "square_video_url": public_file_url(job_id, "square.mp4")
    }

@app.post("/make-vertical/")
async def make_vertical(
    video_url: str = Form(...),
    job_id: str = Form("")
):
    import subprocess
    import imageio_ffmpeg

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    if not job_id:
        job_id = str(uuid.uuid4())

    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    input_path = os.path.join(job_dir, "input_video.mp4")
    output_path = os.path.join(job_dir, "vertical.mp4")

    response = requests.get(video_url, timeout=180)

    if response.status_code != 200:
        return {
            "error": "Failed to download video",
            "details": response.text[:500]
        }

    with open(input_path, "wb") as file:
        file.write(response.content)

    command = [
        ffmpeg_path,
        "-y",
        "-i", input_path,
        "-vf",
        "scale=1080:-2:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        return {
            "error": "ffmpeg vertical failed",
            "details": result.stderr[-1000:]
        }

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

.actions.show button.secondary {
    grid-column: 1 / -1;
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

<div class="card" style="margin-top:20px;">
    <h2 style="margin-top:0;">Тарифы</h2>

    <div style="
        display:grid;
        grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
        gap:16px;
        margin-top:20px;
    ">

        <div style="
            padding:20px;
            border-radius:20px;
            background:#f7f7f7;
        ">
            <h3>Starter</h3>
            <div style="font-size:32px;font-weight:800;">249 ₽</div>
            <div style="margin-top:10px;">5 credits</div>
        </div>

        <div style="
            padding:20px;
            border-radius:20px;
            background:#111;
            color:white;
        ">
            <h3>Popular</h3>
            <div style="font-size:32px;font-weight:800;">399 ₽</div>
            <div style="margin-top:10px;">10 credits</div>
        </div>

        <div style="
            padding:20px;
            border-radius:20px;
            background:#f7f7f7;
        ">
            <h3>Pro</h3>
            <div style="font-size:32px;font-weight:800;">899 ₽</div>
            <div style="margin-top:10px;">30 credits</div>
        </div>

    </div>

    <p style="
        margin-top:20px;
        color:#666;
        line-height:1.6;
    ">
        Кредиты используются для генерации AI-видео и AI-аватаров. 
        1 генерация = 1 кредит.

            После оплаты кредиты автоматически начисляются на аккаунт пользователя.
    </p>
</div>

<div id="creditsBox" class="hint" style="margin-bottom:16px;">
    Кредиты: <b id="creditsCount">3</b>
</div>

<div class="hint" id="generationCostBox">
    Стоимость генерации: <b id="generationCost">1</b> кредит
</div>

<div style="margin-top:16px;">
    <label style="display:flex; gap:10px; align-items:flex-start; font-size:14px; line-height:1.5;">
            <input type="checkbox" id="agreeTerms" style="width:auto; margin-top:4px;">
    
            <span>
                Я ознакомлен и согласен с
                <a href="/oferta" target="_blank">
                    Пользовательским соглашением
                </a>
                и
                <a href="/privacy" target="_blank">
                    Политикой конфиденциальности,
                </a>
                даю согласие на обработку персональных данных,
                а также на передачу данных третьим лицам и внешним сервисам,
                необходимым для работы платформы.
            </span>
    </label>
</div>

<div id="authBox" style="margin-top:20px; margin-bottom:20px;">

    <div id="loggedOutBox">
        <input type="email" id="email" placeholder="Email" style="margin-bottom:10px;">
        <input type="password" id="password" placeholder="Пароль" style="margin-bottom:10px;">

        <button id="signUpBtn" type="button">Зарегистрироваться</button>

        <button id="loginBtn" type="button" class="secondary" style="margin-top:10px;">
            Войти
        </button>

        <div class="hint" style="margin-top:10px;">
            После регистрации подтверди email, затем войди.
        </div>
    </div>

    <div id="loggedInBox" style="display:none;">
        <div id="currentUser" class="hint" style="margin-top:10px;">
            Вы вошли
        </div>

        <button id="logoutBtn" type="button" class="secondary" style="margin-top:10px;">
            Выйти
        </button>
    </div>

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
            <button type="button">Скачать видео</button>
        </a>

        <a id="downloadImageLink" href="#" download="avatar-image.png">
            <button type="button">Скачать картинку</button>
        </a>

        <button type="button" class="secondary" onclick="resetApp()">
            Создать ещё
        </button>
    </div>

    <div class="footer-note">Генерация обычно занимает 1–3 минуты.</div>
</div>

<script src="https://unpkg.com/@supabase/supabase-js@2"></script>

<script>
let finalVideoUrl = null;
let finalAvatarUrl = null;
let creditsLeft = 3;
let isGenerated = false;

const supabaseClient = window.supabase.createClient(
    "https://yvynivfphhyqriqwpiic.supabase.co",
    "sb_publishable_MSlFLoKbU-DJhWcP5d3wbw_YZQbc-jb"
);

let currentUser = null;

async function ensureProfile() {
    if (!currentUser) return;

    const { data } = await supabaseClient
        .from("profiles")
        .select("*")
        .eq("id", currentUser.id)
        .single();

    if (!data) {
    const { error } = await supabaseClient
        .from("profiles")
        .insert({
            id: currentUser.id,
            email: currentUser.email,
            credits: 3
        });

    if (error) {
        console.error(error);
    }
}
    await loadCredits();
}

async function loadCredits() {
    if (!currentUser) return;

    const { data, error } = await supabaseClient
        .from("profiles")
        .select("credits")
        .eq("id", currentUser.id)
        .single();

    if (error) {
        console.error(error);
        return;
    }

    creditsLeft = data.credits;

    document.getElementById("creditsCount").innerText =
        creditsLeft;
}

function updateAuthUI() {
    const loggedOutBox = document.getElementById("loggedOutBox");
    const loggedInBox = document.getElementById("loggedInBox");
    const currentUserBox = document.getElementById("currentUser");

    if (currentUser) {
        loggedOutBox.style.display = "none";
        loggedInBox.style.display = "block";
        currentUserBox.innerText = "Вы вошли как: " + currentUser.email;
    } else {
        loggedOutBox.style.display = "block";
        loggedInBox.style.display = "none";
        currentUserBox.innerText = "Вы не вошли";
    }
}

async function signUp() {
    const agree =
    document.getElementById("agreeTerms").checked;

if (!agree) {
    alert("Необходимо согласиться с Пользовательским соглашением и Политикой конфиденциальности");
    return;
}
    
    if (!window.supabase) {
        alert("Supabase не загрузился");
        return;
    }

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value.trim();

    if (!email || !password) {
        alert("Введите email и пароль");
        return;
    }

    if (password.length < 6) {
        alert("Пароль должен быть минимум 6 символов");
        return;
    }

    const { data, error } = await supabaseClient.auth.signUp({
        email,
        password
    });

    if (error) {
        alert("Ошибка регистрации: " + error.message);
        return;
    }

    if (data.session) {
        currentUser = data.user;

        await ensureProfile();

        updateAuthUI();

        alert("Аккаунт создан, вход выполнен");
    } else {
        alert("Регистрация отправлена. Проверь email и подтверди аккаунт.");
    }
}

async function login() {
    const agree =
    document.getElementById("agreeTerms").checked;

if (!agree) {
    alert("Необходимо согласиться с Пользовательским соглашением и Политикой конфиденциальности");
    return;
}
    
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value.trim();

    if (!email || !password) {
        alert("Введите email и пароль");
        return;
    }

    const { data, error } = await supabaseClient.auth.signInWithPassword({
        email,
        password
    });

    if (error) {
        alert("Ошибка входа: " + error.message);
        return;
    }

    currentUser = data.user;
    updateAuthUI();
    await ensureProfile();
}

async function logout() {
    await supabaseClient.auth.signOut();
    currentUser = null;
    updateAuthUI();
}

async function loadUser() {
    const { data } = await supabaseClient.auth.getSession();
    currentUser = data.session?.user || null;
    updateAuthUI();
    await ensureProfile();
}

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
    return 1;
}

function updateGenerationCost() {
    document.getElementById("generationCost").innerText = 1;
}

function toggleCustomTheme() {
    const theme = document.getElementById("theme").value;
    const customTheme = document.getElementById("customTheme");

    customTheme.style.display = theme === "custom" ? "block" : "none";
}

function updateCharCount() {
    const text = document.getElementById("text").value;
    document.getElementById("charCount").innerText = text.length + " / 250";
}

function resetApp() {
    finalVideoUrl = null;
    finalAvatarUrl = null;
    isGenerated = false;

    const video = document.getElementById("video");
    const avatarPreview = document.getElementById("avatarPreview");
    const actions = document.getElementById("actions");
    const status = document.getElementById("status");
    const btn = document.getElementById("generateBtn");

    video.pause();
    video.removeAttribute("src");
    video.load();
    video.style.display = "none";

    avatarPreview.removeAttribute("src");
    avatarPreview.style.display = "none";

    document.getElementById("downloadLink").href = "#";
    document.getElementById("downloadImageLink").href = "#";

    actions.className = "actions";
    status.innerText = "";

    btn.disabled = false;
    btn.innerText = "Создать видео";

    setStep(0);
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

    const generationCost = 1;

    if (!currentUser) {
        alert("Сначала войди в аккаунт");
        return;
    }

    if (isGenerated) {
        alert("Видео уже создано. Нажми 'Создать ещё', чтобы начать заново.");
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
    btn.innerText = "Генерация...";
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

        avatarPreview.src = avatarData.avatar_url;
        avatarPreview.style.display = "block";

        finalAvatarUrl = avatarData.avatar_url;
        document.getElementById("downloadImageLink").href = finalAvatarUrl;

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
        status.innerText = "⏳ Создаём talking video...";

        const talkForm = new FormData();
        talkForm.append("avatar_url", avatarData.did_avatar_url || avatarData.avatar_url);
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

        if (format === "square") {
            status.innerText = "⏳ Создаём square video...";

            const squareForm = new FormData();
            squareForm.append("video_url", finalVideoUrl);
            squareForm.append("job_id", jobId);

            const squareResponse = await fetch("/make-square/", {
                method: "POST",
                body: squareForm
            });

            const squareData = await squareResponse.json();

            if (squareData.error || !squareData.square_video_url) {
                throw new Error("Ошибка square video: " + JSON.stringify(squareData));
            }

            finalVideoUrl = squareData.square_video_url;
        }

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

const { data: sessionData } = await supabaseClient.auth.getSession();

const creditResponse = await fetch("/use-credit/", {
    method: "POST",
    headers: {
        "Authorization": "Bearer " + sessionData.session.access_token
    }
});

const creditData = await creditResponse.json();

if (creditData.error) {
    throw new Error("Ошибка списания кредита: " + creditData.error);
}

creditsLeft = creditData.credits;
document.getElementById("creditsCount").innerText = creditsLeft;

        video.src = finalVideoUrl;
        video.style.display = "block";

        document.getElementById("downloadLink").href = finalVideoUrl;

        actions.className = "actions show";

        isGenerated = true;
            btn.disabled = true;
        btn.innerText = "Видео создано";

    } catch (error) {
        status.innerText = error.message;
        btn.disabled = false;
        btn.innerText = "Создать видео";
    }
}

document.getElementById("styleMode").addEventListener("change", updateGenerationCost);
document.getElementById("format").addEventListener("change", updateGenerationCost);
document.getElementById("theme").addEventListener("change", toggleCustomTheme);
document.getElementById("text").addEventListener("input", updateCharCount);

document.getElementById("signUpBtn").addEventListener("click", signUp);
document.getElementById("loginBtn").addEventListener("click", login);
document.getElementById("logoutBtn").addEventListener("click", logout);

loadUser();

toggleCustomTheme();
updateGenerationCost();
updateCharCount();
document.getElementById("creditsCount").innerText = creditsLeft;
setStep(0);
</script>
<footer style="
    max-width:760px;
    margin:30px auto 10px;
    padding:20px;
    text-align:center;
    color:#666;
    font-size:14px;
    line-height:1.8;
">
<div style="margin-top:14px; font-size:13px; color:#777;">
    Используя сайт, вы соглашаетесь с обработкой персональных данных
    и условиями Пользовательского соглашения.
</div>
    <div style="margin-bottom:10px;">
        <a href="/oferta" target="_blank">
            Пользовательское соглашение
        </a>
        —
        <a href="/privacy" target="_blank">
            Политика конфиденциальности
        </a>
    </div>

    <div>
        ИП Галанов Константин Николаевич
    </div>

    <div>
        ИНН: 563901816803
    </div>

    <div>
        Email: galanovkn@yandex.ru
    </div>

    <div>
        AI Avatar Video — сервис генерации AI-видео и AI-аватаров
    </div>
</footer>
</body>
</html>
"""
