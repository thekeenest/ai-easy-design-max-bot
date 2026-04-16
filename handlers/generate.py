"""
Image generation handlers: Seedream text→image and GPT Images (product photography).
Jobs are queued in DB; background workers in main.py send the results.
"""
from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_cancel_kb, get_photo_menu_kb
from state_manager import state_mgr

db = AsyncDatabase()

STATES = {
    "seedream_prompt": "generate:seedream_prompt",
    "gpt_prompt": "generate:gpt_prompt",
}


async def show_seedream_start(chat_id: int, user_id: int, bot: Bot):
    balance = await db.get_balance(user_id)
    cost = config.GENERATE_IMAGE_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"❌ Недостаточно токенов.\n"
                f"Требуется: *{cost}* | Ваш баланс: *{balance}*\n\n"
                "Пополните баланс в разделе профиля."
            ),
            attachments=get_photo_menu_kb(),
            format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["seedream_prompt"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✨ *Seedream — текст в изображение*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Напишите подробный промпт на русском или английском.\n"
            "_Пример: красивый закат над морем, фотореализм, 4K_"
        ),
        attachments=get_cancel_kb(),
        format="markdown",
    )


async def process_seedream_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    cost = config.GENERATE_IMAGE_COST
    if not await db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов (нужно {cost}).",
            attachments=get_photo_menu_kb(),
        )
        return
    job_id = await db.add_seedream_job(user_id=user_id, username=username, prompt=prompt)
    balance = await db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ *Запрос принят!*\n\n"
            f"Промпт: _{prompt[:150]}{'...' if len(prompt) > 150 else ''}_\n\n"
            f"🪙 Списано: *{cost} токенов* | Остаток: *{balance}*\n\n"
            "Изображение будет готово через 20–60 секунд."
        ),
        format="markdown",
    )


async def show_gpt_image_start(chat_id: int, user_id: int, bot: Bot):
    balance = await db.get_balance(user_id)
    cost = config.GENERATE_IMAGE_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно: *{cost}*, у вас: *{balance}*",
            attachments=get_photo_menu_kb(),
            format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["gpt_prompt"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🖼 *GPT Images*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Опишите изображение, которое хотите создать:"
        ),
        attachments=get_cancel_kb(),
        format="markdown",
    )


async def process_gpt_image_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    cost = config.GENERATE_IMAGE_COST
    if not await db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    await db.add_openai_image_job(
        user_id=user_id, username=username, prompt=prompt,
        num_images=1, job_type="general"
    )
    balance = await db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"⏳ Генерирую изображение...\n\n"
            f"_Промпт: {prompt[:150]}_\n\n"
            f"🪙 Списано: {cost} | Остаток: {balance}"
        ),
        format="markdown",
    )
