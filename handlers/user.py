"""
User profile, promo codes.
"""
from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_profile_kb, get_packages_kb, get_main_menu_kb
from state_manager import state_mgr

db = AsyncDatabase()

STATES = {
    "waiting_for_promo": "user:waiting_for_promo",
}


async def show_profile(chat_id: int, user_id: int, bot: Bot):
    await db.add_user(user_id, str(user_id))
    balance = await db.get_balance(user_id)
    text = (
        "👤 *Профиль*\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"🪙 Баланс: *{balance} токенов*\n\n"
        "💳 Нажмите «Пополнить токены» для покупки пакета.\n"
        "🎁 Нажмите «Промокод» для ввода промокода."
    )
    await bot.send_message(
        chat_id=chat_id, text=text,
        attachments=get_profile_kb(),
        format="markdown",
    )


async def handle_enter_promo(chat_id: int, user_id: int, bot: Bot):
    state_mgr.set(user_id, STATES["waiting_for_promo"])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🔑 *Ввод промокода*\n\n"
            "Введите промокод ниже — токены начислятся автоматически."
        ),
        format="markdown",
    )


async def process_promo_code(chat_id: int, user_id: int, text: str, bot: Bot):
    state_mgr.clear(user_id)
    promo_code = text.strip().upper()
    promo_data = await db.get_promo_code(promo_code)
    if not promo_data:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Неверный промокод. Проверьте правильность ввода и попробуйте снова.",
            attachments=get_packages_kb(),
        )
        return
    credit_amount = promo_data["amount"]
    await db.update_balance(user_id, credit_amount)
    await db.mark_promo_used(promo_code, user_id)
    balance = await db.get_balance(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"✅ *Промокод активирован!*\n\n"
            f"🪙 Начислено: *{credit_amount} токенов*\n"
            f"💰 Ваш баланс: *{balance} токенов*"
        ),
        attachments=get_main_menu_kb(),
        format="markdown",
    )
