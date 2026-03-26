"""
AI Assistant handler: text (free), voice, vision, calorie analysis.
"""
import logging
import os
import aiohttp

from maxapi import Bot

from config import config
from database import Database
from keyboards.menu import get_ai_mode_kb, get_cancel_kb, get_ai_ask_again_kb, get_main_menu_kb
from state_manager import state_mgr

logger = logging.getLogger(__name__)
db = Database()

STATES = {
    "text": "ai:text",
    "voice": "ai:voice",
    "vision_photos": "ai:vision_photos",
    "vision_prompt": "ai:vision_prompt",
    "calorie": "ai:calorie",
}

MAX_VISION_IMAGES = 3


async def show_ai_menu(chat_id: int, user_id: int, bot: Bot):
    state_mgr.clear(user_id)
    text = (
        "🤖 *AI Assistant*\n\n"
        "Ваш умный помощник на базе ChatGPT!\n\n"
        "💬 *Возможности:*\n"
        f"• Текстовые вопросы — бесплатно 🆓\n"
        f"• Голосовые вопросы — {config.AI_ASSISTANT_VOICE_COST} токенов\n"
        f"• Анализ фото — {config.AI_ASSISTANT_VISION_COST} токенов\n"
        f"• Анализ калорий — {config.AI_ASSISTANT_CALORIE_COST} токенов\n\n"
        "Выберите режим:"
    )
    await bot.send_message(
        chat_id=chat_id, text=text,
        attachments=get_ai_mode_kb(),
        format="markdown",
    )


async def handle_ai_mode(chat_id: int, user_id: int, mode: str, bot: Bot):
    balance = db.get_balance(user_id)
    costs = {
        "text": config.AI_ASSISTANT_TEXT_COST,
        "voice": config.AI_ASSISTANT_VOICE_COST,
        "vision": config.AI_ASSISTANT_VISION_COST,
        "calorie": config.AI_ASSISTANT_CALORIE_COST,
    }
    cost = costs.get(mode, 0)
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно: *{cost}*, у вас: *{balance}*",
            attachments=get_ai_mode_kb(),
            format="markdown",
        )
        return

    if mode == "text":
        state_mgr.set(user_id, STATES["text"])
        await bot.send_message(
            chat_id=chat_id,
            text="💬 *Текстовый режим*\n\nЗадайте любой вопрос — и AI даст ответ.",
            attachments=get_cancel_kb(),
            format="markdown",
        )
    elif mode == "voice":
        state_mgr.set(user_id, STATES["voice"])
        await bot.send_message(
            chat_id=chat_id,
            text="🎤 *Голосовой режим*\n\nОтправьте голосовое сообщение.",
            attachments=get_cancel_kb(),
            format="markdown",
        )
    elif mode == "vision":
        state_mgr.set(user_id, STATES["vision_photos"])
        state_mgr.update_data(user_id, vision_photos=[])
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🖼 *Анализ фото*\n\n"
                f"Отправьте до {MAX_VISION_IMAGES} фото для анализа.\n"
                "Когда загрузите все фото — нажмите «Анализировать»."
            ),
            attachments=get_cancel_kb(),
            format="markdown",
        )
    elif mode == "calorie":
        state_mgr.set(user_id, STATES["calorie"])
        await bot.send_message(
            chat_id=chat_id,
            text="🍽 *Анализ калорий*\n\nОтправьте фото блюда.",
            attachments=get_cancel_kb(),
            format="markdown",
        )


async def process_text_question(chat_id: int, user_id: int, username: str, question: str, bot: Bot):
    state_mgr.clear(user_id)
    if len(question) < 3:
        await bot.send_message(chat_id=chat_id, text="Вопрос слишком короткий. Минимум 3 символа.")
        return
    if len(question) > 4000:
        await bot.send_message(chat_id=chat_id, text="Вопрос слишком длинный. Максимум 4000 символов.")
        return
    cost = config.AI_ASSISTANT_TEXT_COST  # 0 — free
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text="❌ Недостаточно токенов.")
        return
    db.add_ai_assistant_job(user_id=user_id, username=username, question=question, mode="text")
    await bot.send_message(
        chat_id=chat_id,
        text="⏳ Обрабатываю вопрос... Ответ придёт через несколько секунд.",
    )


async def process_voice_message(chat_id: int, user_id: int, username: str, audio_url: str, bot: Bot):
    """Download voice from MAX, save, queue job."""
    state_mgr.clear(user_id)
    cost = config.AI_ASSISTANT_VOICE_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    voice_path = os.path.join(config.TEMP_DIR, f"voice_{user_id}_{chat_id}.ogg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(audio_url) as resp:
                if resp.status == 200:
                    with open(voice_path, "wb") as f:
                        f.write(await resp.read())
                else:
                    raise Exception(f"Download failed: {resp.status}")
    except Exception as e:
        db.update_balance(user_id, cost)  # refund
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить голосовое: {e}")
        return

    db.add_ai_assistant_job(
        user_id=user_id, username=username, question="[voice]",
        mode="voice", voice_path=voice_path,
    )
    await bot.send_message(
        chat_id=chat_id,
        text=f"🎤 Голосовое принято! Транскрибирую и отвечаю... ({cost} токенов)",
    )


async def process_vision_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    """Add a photo to the vision photo list."""
    data = state_mgr.get_data(user_id)
    photos = data.get("vision_photos", [])

    # Download and save
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"vision_{user_id}_{len(photos)}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return

    photos.append(img_path)
    state_mgr.update_data(user_id, vision_photos=photos)

    if len(photos) >= MAX_VISION_IMAGES:
        state_mgr.set(user_id, STATES["vision_prompt"])
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ {len(photos)} фото загружено. Введите вопрос к фото:",
            attachments=get_cancel_kb(),
        )
    else:
        from keyboards.menu import build, cb
        kb = build(
            [cb(f"✅ Анализировать ({len(photos)} фото)", "ai:vision_analyze")],
            [cb("❌ Отмена", "cancel")],
        )
        await bot.send_message(
            chat_id=chat_id,
            text=f"Фото {len(photos)}/{MAX_VISION_IMAGES} добавлено. Добавьте ещё или нажмите «Анализировать».",
            attachments=kb,
        )


async def handle_vision_analyze_callback(chat_id: int, user_id: int, bot: Bot):
    """User clicked 'Analyze' — switch to prompt input."""
    data = state_mgr.get_data(user_id)
    photos = data.get("vision_photos", [])
    if not photos:
        await bot.send_message(chat_id=chat_id, text="Сначала отправьте хотя бы одно фото.")
        return
    state_mgr.set(user_id, STATES["vision_prompt"])
    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ {len(photos)} фото готово. Введите вопрос к изображениям:",
        attachments=get_cancel_kb(),
    )


async def process_vision_prompt(chat_id: int, user_id: int, username: str, question: str, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    photos = data.get("vision_photos", [])
    cost = config.AI_ASSISTANT_VISION_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    image_paths_str = ",".join(photos)
    db.add_ai_assistant_job(
        user_id=user_id, username=username, question=question,
        mode="vision", image_paths=image_paths_str,
    )
    await bot.send_message(
        chat_id=chat_id,
        text=f"🖼 Анализирую {len(photos)} фото... ({cost} токенов)",
    )


async def process_calorie_photo(chat_id: int, user_id: int, username: str, photo_url: str, bot: Bot):
    state_mgr.clear(user_id)
    cost = config.AI_ASSISTANT_CALORIE_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"calorie_{user_id}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        db.update_balance(user_id, cost)
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return

    db.add_ai_assistant_job(
        user_id=user_id, username=username, question="[calorie]",
        mode="calorie", image_paths=img_path,
    )
    await bot.send_message(
        chat_id=chat_id,
        text=f"🍽 Анализирую блюдо... ({cost} токенов). Ответ придёт через несколько секунд.",
    )
