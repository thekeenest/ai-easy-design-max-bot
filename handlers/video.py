"""
Video generation handlers: Kling (via fal), Runway, VEO3.
"""
import os
import aiohttp

from maxapi import Bot

from config import config
from database import Database
from keyboards.menu import get_cancel_kb, get_video_menu_kb, get_kling_duration_kb, get_runway_aspect_kb
from state_manager import state_mgr

db = Database()

STATES = {
    "kling_photo": "video:kling_photo",
    "kling_prompt": "video:kling_prompt",
    "runway_photo": "video:runway_photo",
    "runway_prompt": "video:runway_prompt",
    "veo3_prompt": "video:veo3_prompt",
}


# ── Kling ──────────────────────────────────────────────────────────────────────

async def show_kling_start(chat_id: int, user_id: int, bot: Bot):
    balance = db.get_balance(user_id)
    min_cost = config.GENERATE_VIDEO_COST_5_SEC
    if balance < min_cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно минимум *{min_cost}* | У вас: *{balance}*",
            attachments=get_video_menu_kb(), format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["kling_photo"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🎞 *KLING v2.1 — видео из фото*\n\n"
            f"5 сек — {config.GENERATE_VIDEO_COST_5_SEC} токенов\n"
            f"10 сек — {config.GENERATE_VIDEO_COST_10_SEC} токенов\n\n"
            "Шаг 1: Отправьте фото, которое оживить."
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_kling_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"kling_{user_id}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return
    state_mgr.set(user_id, STATES["kling_prompt"])
    state_mgr.update_data(user_id, kling_photo_path=img_path)
    await bot.send_message(
        chat_id=chat_id,
        text="✅ Фото получено!\n\nШаг 2: Опишите, что должно происходить в видео:",
        attachments=get_cancel_kb(),
    )


async def handle_kling_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.set(user_id, "video:kling_duration")
    state_mgr.update_data(user_id, kling_prompt=prompt)
    await bot.send_message(
        chat_id=chat_id,
        text="⏱ Выберите длительность видео:",
        attachments=get_kling_duration_kb(),
    )


async def handle_kling_duration(chat_id: int, user_id: int, username: str, duration: int, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    prompt = data.get("kling_prompt", "")
    photo_path = data.get("kling_photo_path", "")
    cost = config.GENERATE_VIDEO_COST_5_SEC if duration == 5 else config.GENERATE_VIDEO_COST_10_SEC
    balance = db.get_balance(user_id)
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            format="markdown",
        )
        return
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text="❌ Ошибка списания токенов.")
        return
    db.add_video_job(
        user_id=user_id, username=username, prompt=prompt,
        duration=duration, image_path=photo_path,
    )
    balance_after = db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *Видео в очереди*\n\n"
            f"Продолжительность: {duration} сек\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Видео будет готово через 3–7 минут."
        ),
        format="markdown",
    )


# ── Runway ─────────────────────────────────────────────────────────────────────

async def show_runway_start(chat_id: int, user_id: int, bot: Bot):
    balance = db.get_balance(user_id)
    cost = config.RUNWAY_VIDEO_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            attachments=get_video_menu_kb(), format="markdown",
        )
        return
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎬 *RUNWAY Gen-4 Turbo*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Выберите соотношение сторон:"
        ),
        attachments=get_runway_aspect_kb(), format="markdown",
    )


async def handle_runway_aspect(chat_id: int, user_id: int, aspect: str, bot: Bot):
    state_mgr.set(user_id, STATES["runway_photo"])
    state_mgr.update_data(user_id, runway_aspect=aspect)
    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ Соотношение: *{aspect}*\n\nОтправьте фото для трансформации:",
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_runway_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"runway_{user_id}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return
    state_mgr.set(user_id, STATES["runway_prompt"])
    state_mgr.update_data(user_id, runway_photo_path=img_path)
    await bot.send_message(
        chat_id=chat_id,
        text="✅ Фото получено!\n\nОпишите, что должно происходить в видео (на английском):",
        attachments=get_cancel_kb(),
    )


async def handle_runway_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    photo_path = data.get("runway_photo_path", "")
    aspect = data.get("runway_aspect", "16:9")
    cost = config.RUNWAY_VIDEO_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    db.add_runway_video_job(
        user_id=user_id, username=username, prompt=prompt,
        image_path=photo_path, aspect_ratio=aspect,
    )
    balance_after = db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *Runway видео в очереди*\n\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Готово через 3–10 минут."
        ),
        format="markdown",
    )


# ── VEO3 ───────────────────────────────────────────────────────────────────────

async def show_veo3_start(chat_id: int, user_id: int, bot: Bot):
    balance = db.get_balance(user_id)
    cost = config.VEO3_VIDEO_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            attachments=get_video_menu_kb(), format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["veo3_prompt"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🌟 *VEO3 — генерация видео (Google)*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Опишите видео подробно (желательно на английском):"
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_veo3_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    cost = config.VEO3_VIDEO_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    db.add_veo3_video_job(user_id=user_id, username=username, prompt=prompt)
    balance_after = db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *VEO3 видео в очереди*\n\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Видео генерируется 5–15 минут."
        ),
        format="markdown",
    )
