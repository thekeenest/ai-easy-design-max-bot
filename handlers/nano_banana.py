"""
NanoBanana handler: AI image editing via NanoBanana API.
"""
import os
import aiohttp

from maxapi import Bot

from config import config
from database import Database
from keyboards.menu import get_cancel_kb, get_photo_menu_kb
from state_manager import state_mgr

db = Database()

STATES = {
    "photo": "nano:photo",
    "prompt": "nano:prompt",
}


async def show_nano_start(chat_id: int, user_id: int, bot: Bot):
    balance = db.get_balance(user_id)
    cost = config.NANO_BANANA_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            attachments=get_photo_menu_kb(), format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["photo"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎭 *NanoBanana — AI редактор*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Отправьте фото для редактирования:"
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_nano_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"nano_{user_id}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return
    state_mgr.set(user_id, STATES["prompt"])
    state_mgr.update_data(user_id, nano_photo_path=img_path)
    await bot.send_message(
        chat_id=chat_id,
        text="✅ Фото получено!\n\nОпишите изменение (на английском):\n\n_Пример: make the background a beach_",
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_nano_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    photo_path = data.get("nano_photo_path", "")
    if not photo_path:
        await bot.send_message(chat_id=chat_id, text="❌ Фото не найдено.")
        return
    cost = config.NANO_BANANA_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    db.add_nano_banana_job(
        user_id=user_id, username=username,
        prompt=prompt, image_path=photo_path,
    )
    balance_after = db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *NanoBanana обрабатывает фото...*\n\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Готово через 20–60 секунд."
        ),
        format="markdown",
    )
