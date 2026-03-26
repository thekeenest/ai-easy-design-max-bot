"""
Suno AI music generation handler.
"""
from maxapi import Bot

from config import config
from database import Database
from keyboards.menu import get_cancel_kb, get_main_menu_kb
from state_manager import state_mgr

db = Database()

STATES = {
    "prompt": "suno:prompt",
}


async def show_suno_menu(chat_id: int, user_id: int, bot: Bot):
    balance = db.get_balance(user_id)
    cost = config.SUNO_MUSIC_COST
    if balance < cost:
        await bot.send_message(
            chat_id=chat_id,
            text=f"❌ Недостаточно токенов. Нужно *{cost}* | У вас *{balance}*",
            attachments=get_main_menu_kb(), format="markdown",
        )
        return
    state_mgr.set(user_id, STATES["prompt"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎵 *Suno AI — генерация музыки*\n\n"
            f"Стоимость: *{cost} токенов*\n\n"
            "Опишите музыку, которую хотите создать:\n\n"
            "_Пример: upbeat electronic music with piano, happy mood, 120 BPM_\n"
            "_Или: грустная русская баллада с гитарой и женским вокалом_"
        ),
        attachments=get_cancel_kb(), format="markdown",
    )


async def handle_suno_prompt(chat_id: int, user_id: int, username: str, prompt: str, bot: Bot):
    state_mgr.clear(user_id)
    cost = config.SUNO_MUSIC_COST
    if not db.check_and_deduct(user_id, cost, config.ADMIN_ID):
        await bot.send_message(chat_id=chat_id, text=f"❌ Недостаточно токенов (нужно {cost}).")
        return
    db.add_suno_job(user_id=user_id, username=username, prompt=prompt)
    balance_after = db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🎵 *Генерирую музыку...*\n\n"
            f"Промпт: _{prompt[:150]}_\n\n"
            f"🪙 Списано: {cost} | Остаток: {balance_after}\n\n"
            "Трек будет готов через 1–3 минуты."
        ),
        format="markdown",
    )
