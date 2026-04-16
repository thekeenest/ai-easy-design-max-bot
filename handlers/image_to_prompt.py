"""
Image → Prompt handler: analyze an image and generate a text prompt.
"""
import os
import aiohttp

from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_cancel_kb, get_photo_menu_kb
from state_manager import state_mgr

db = AsyncDatabase()

STATES = {"photo": "img2prompt:photo"}


async def show_img2prompt_start(chat_id: int, user_id: int, bot: Bot):
    balance = await db.get_balance(user_id)
    cost = config.IMAGE_TO_PROMPT_COST
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
            f"🔍 *Фото → Промпт*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Отправьте любое изображение — получите готовый промпт для AI генерации."
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_img2prompt_photo(chat_id: int, user_id: int, username: str, photo_url: str, bot: Bot):
    state_mgr.clear(user_id)
    cost = config.IMAGE_TO_PROMPT_COST
    if not await db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"i2p_{user_id}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await db.update_balance(user_id, cost)
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return

    # Process synchronously using GPT-4 Vision
    try:
        from utils_ai_assistant import analyze_images_with_gpt4_vision
        answer, error = await analyze_images_with_gpt4_vision(
            [img_path],
            "Analyze this image and generate a detailed, creative text-to-image prompt in English. "
            "Describe: subject, style, lighting, colors, composition, mood, technical details. "
            "Format: ready-to-use prompt for Midjourney/DALL-E/Flux."
        )
        if error or not answer:
            raise Exception(error or "Empty response")
        balance_after = await db.get_balance(user_id)
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔍 *Промпт по вашему изображению:*\n\n"
                f"`{answer}`\n\n"
                f"🪙 Списано: {cost} | Остаток: {balance_after}"
            ),
            format="markdown",
        )
    except Exception as e:
        await db.update_balance(user_id, cost)
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Ошибка анализа: {e}")
