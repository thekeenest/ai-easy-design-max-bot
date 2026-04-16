"""
Flux Kontext handler: edit an image with text instructions.
"""
import os
import aiohttp

from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_cancel_kb, get_flux_kontext_count_kb, get_photo_menu_kb
from state_manager import state_mgr

db = AsyncDatabase()

STATES = {
    "count": "flux:count",
    "photos": "flux:photos",
    "prompt": "flux:prompt",
}


async def show_flux_start(chat_id: int, user_id: int, bot: Bot):
    balance = await db.get_balance(user_id)
    cost = config.FLUX_KONTEXT_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            attachments=get_photo_menu_kb(), format="markdown",
        )
        return
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🌀 *Flux Kontext*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Редактирование фото с помощью текстового описания.\n"
            "Сколько фотографий хотите загрузить?"
        ),
        attachments=get_flux_kontext_count_kb(), format="markdown",
    )


async def handle_flux_count(chat_id: int, user_id: int, count: int, bot: Bot):
    state_mgr.set(user_id, STATES["photos"])
    state_mgr.update_data(user_id, flux_count=count, flux_photos=[])
    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ Будет {count} фото.\n\nОтправьте фото 1 из {count}:",
        attachments=get_cancel_kb(),
    )


async def handle_flux_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    data = state_mgr.get_data(user_id)
    photos = data.get("flux_photos", [])
    count = data.get("flux_count", 1)

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"flux_{user_id}_{len(photos)}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return

    photos.append(img_path)
    state_mgr.update_data(user_id, flux_photos=photos)

    if len(photos) >= count:
        state_mgr.set(user_id, STATES["prompt"])
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Все {count} фото загружены!\n\nОпишите, что нужно изменить:",
            attachments=get_cancel_kb(),
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Фото {len(photos)}/{count} добавлено. Отправьте следующее:",
            attachments=get_cancel_kb(),
        )


async def handle_flux_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    photos = data.get("flux_photos", [])
    if not photos:
        await bot.send_message(chat_id=chat_id, text="❌ Фото не найдены.")
        return
    cost = config.FLUX_KONTEXT_COST
    if not await db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    await db.add_flux_kontext_job(
        user_id=user_id, username=username,
        prompt=prompt, image_paths=",".join(photos),
    )
    balance_after = await db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *Flux Kontext запущен*\n\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Результат придёт через 30–90 секунд."
        ),
        format="markdown",
    )
