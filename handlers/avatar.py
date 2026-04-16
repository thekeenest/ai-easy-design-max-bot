"""
Avatar (Flux LoRA) training handler.
"""
import os
import aiohttp

from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_cancel_kb, get_avatar_menu_kb, get_main_menu_kb
from state_manager import state_mgr

db = AsyncDatabase()

MIN_PHOTOS = 5
MAX_PHOTOS = 20
STATES = {
    "photos": "avatar:photos",
    "trigger": "avatar:trigger",
}


async def show_avatar_start(chat_id: int, user_id: int, bot: Bot):
    balance = await db.get_balance(user_id)
    cost = config.AVATAR_TRAINING_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            attachments=get_avatar_menu_kb(), format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["photos"])
    state_mgr.update_data(user_id, avatar_photos=[])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🧑‍🎨 *Создание AI-аватара (Flux LoRA)*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            f"Отправьте {MIN_PHOTOS}–{MAX_PHOTOS} фото:\n"
            "• Чёткие, хорошего качества\n"
            "• Разные ракурсы и выражения\n"
            "• Только одно лицо на фото\n"
            "• Без очков, масок, аксессуаров\n\n"
            "Начните отправлять фото:"
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_avatar_photo(chat_id: int, user_id: int, photo_url: str, bot: Bot):
    data = state_mgr.get_data(user_id)
    photos = data.get("avatar_photos", [])

    os.makedirs(config.TEMP_DIR, exist_ok=True)
    img_path = os.path.join(config.TEMP_DIR, f"avatar_{user_id}_{len(photos)}.jpg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url) as resp:
                with open(img_path, "wb") as f:
                    f.write(await resp.read())
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Не удалось загрузить фото: {e}")
        return

    photos.append(img_path)
    state_mgr.update_data(user_id, avatar_photos=photos)

    if len(photos) >= MAX_PHOTOS:
        state_mgr.set(user_id, STATES["trigger"])
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Максимум {MAX_PHOTOS} фото загружено!\n\nВведите имя аватара (trigger phrase), например: *Masha*",
            attachments=get_cancel_kb(), format="markdown",
        )
    else:
        from keyboards.menu import build, cb
        kb_rows = []
        if len(photos) >= MIN_PHOTOS:
            kb_rows.append([cb(f"✅ Далее ({len(photos)} фото)", "avatar:next")])
        kb_rows.append([cb("❌ Отмена", "cancel")])
        from maxapi.types import ButtonsPayload
        kb = [ButtonsPayload(buttons=kb_rows).pack()]
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"Фото {len(photos)}/{MAX_PHOTOS} загружено.\n"
                + ("Добавьте ещё или нажмите «Далее»." if len(photos) >= MIN_PHOTOS
                   else f"Нужно ещё минимум {MIN_PHOTOS - len(photos)} фото.")
            ),
            attachments=kb,
        )


async def handle_avatar_next_callback(chat_id: int, user_id: int, bot: Bot):
    data = state_mgr.get_data(user_id)
    photos = data.get("avatar_photos", [])
    if len(photos) < MIN_PHOTOS:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Нужно минимум {MIN_PHOTOS} фото. Сейчас: {len(photos)}",
        )
        return
    state_mgr.set(user_id, STATES["trigger"])
    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ {len(photos)} фото готово.\n\nВведите имя аватара (trigger phrase), например: *Anna*:",
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_trigger_phrase(chat_id: int, user_id: int, username: str, trigger: str, bot: Bot):
    state_mgr.clear(user_id)
    data = state_mgr.get_data(user_id)
    photos = data.get("avatar_photos", [])
    if not photos:
        await bot.send_message(chat_id=chat_id, text="❌ Фото не найдены.")
        return
    cost = config.AVATAR_TRAINING_COST
    if not await db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return

    user_dir = os.path.join(config.TEMP_DIR, f"avatar_{user_id}")
    os.makedirs(user_dir, exist_ok=True)
    for i, path in enumerate(photos):
        dest = os.path.join(user_dir, f"photo_{i}.jpg")
        if path != dest:
            import shutil
            shutil.copy2(path, dest)

    await db.add_avatar_training_job(
        user_id=user_id, username=username,
        trigger_phrase=trigger.strip(),
        user_dir=user_dir,
    )
    balance_after = await db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🧑‍🎨 *Обучение аватара запущено!*\n\n"
            f"Имя: *{trigger}*\n"
            f"Фото: {len(photos)}\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Обучение занимает 15–30 минут. Уведомление придёт по готовности."
        ),
        attachments=get_main_menu_kb(), format="markdown",
    )
