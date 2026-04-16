"""
AI Photo Session handler: collect photos → pick style → generate.
"""
import os
import aiohttp

from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_cancel_kb, get_photosession_style_kb, get_photo_menu_kb
from state_manager import state_mgr

db = AsyncDatabase()

MAX_PHOTOS = 10
STATES = {
    "collecting": "photosession:collecting",
    "style": "photosession:style",
}


async def show_photosession_start(chat_id: int, user_id: int, bot: Bot):
    balance = await db.get_balance(user_id)
    cost = config.PHOTOSESSION_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* за фото | У вас: *{balance}*",
            attachments=get_photo_menu_kb(), format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["collecting"])
    state_mgr.update_data(user_id, session_photos=[])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "📷 *AI Фотосессия*\n\n"
            f"Стоимость: *{cost} токенов/фото*\n\n"
            f"Отправьте 3–{MAX_PHOTOS} своих фото для создания аватара.\n"
            "Лучший результат — разные ракурсы, хорошее освещение, без очков."
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_session_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    data = state_mgr.get_data(user_id)
    photos = data.get("session_photos", [])

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"session_{user_id}_{len(photos)}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return

    photos.append(img_path)
    state_mgr.update_data(user_id, session_photos=photos)

    if len(photos) >= MAX_PHOTOS:
        # Max reached — go to style selection
        state_mgr.set(user_id, STATES["style"])
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Максимум {MAX_PHOTOS} фото загружено!\n\nВыберите стиль фотосессии:",
            attachments=get_photosession_style_kb(),
        )
    else:
        from keyboards.menu import build, cb
        kb = build(
            [cb(f"✅ Выбрать стиль ({len(photos)} фото)", "session:choose_style")],
            [cb("❌ Отмена", "cancel")],
        )
        await bot.send_message(
            chat_id=chat_id,
            text=f"Фото {len(photos)} добавлено. Добавьте ещё или выберите стиль.",
            attachments=kb,
        )


async def handle_choose_style_callback(chat_id: int, user_id: int, bot: Bot):
    data = state_mgr.get_data(user_id)
    photos = data.get("session_photos", [])
    if len(photos) < 3:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Минимум 3 фото. Сейчас загружено: {len(photos)}",
        )
        return
    state_mgr.set(user_id, STATES["style"])
    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ {len(photos)} фото готово.\n\nВыберите стиль фотосессии:",
        attachments=get_photosession_style_kb(),
    )


async def handle_style_selected(chat_id: int, user_id: int, username: str, style_idx: int, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    photos = data.get("session_photos", [])
    if not photos:
        await bot.send_message(chat_id=chat_id, text="❌ Фотографии не найдены.")
        return

    styles = list(config.STYLES.keys())
    if style_idx >= len(styles):
        await bot.send_message(chat_id=chat_id, text="❌ Неверный стиль.")
        return
    style_name = styles[style_idx]
    style_prompt = config.STYLES[style_name]
    cost = config.PHOTOSESSION_COST

    if not await db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return

    await db.add_photosession_job(
        user_id=user_id, username=username,
        style_name=style_name, style_prompt=style_prompt,
        photo_paths=",".join(photos),
    )
    balance_after = await db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *Фотосессия запущена!*\n\n"
            f"Стиль: *{style_name}*\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Результат придёт через 2–5 минут."
        ),
        format="markdown",
    )
