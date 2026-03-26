"""
Admin commands for MAX bot.
"""
from maxapi import Bot

from config import config
from database import Database
from state_manager import state_mgr

db = Database()

STATES = {
    "promo_code": "admin:promo_code",
    "promo_amount": "admin:promo_amount",
    "broadcast_text": "admin:broadcast_text",
    "add_balance_id": "admin:add_balance_id",
    "add_balance_amount": "admin:add_balance_amount",
}


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def cmd_admin(chat_id: int, user_id: int, bot: Bot):
    if not is_admin(user_id):
        return
    stats = db.get_stats()
    text = (
        "🛠 *Админ панель*\n\n"
        f"👤 Пользователей: `{stats.get('total_users', 0)}`\n"
        f"🎟 Промокодов: `{stats.get('total_promo_codes', 0)}`\n"
        f"  Активных: `{stats.get('active_promo_codes', 0)}`\n"
        f"  Использовано: `{stats.get('used_promo_codes', 0)}`\n\n"
        "Команды:\n"
        "/admin_promo — управление промокодами\n"
        "/admin_balance — добавить токены пользователю\n"
        "/admin_broadcast — рассылка\n"
        "/admin_stats — статистика"
    )
    await bot.send_message(chat_id=chat_id, text=text, format="markdown")


async def cmd_admin_promo(chat_id: int, user_id: int, bot: Bot):
    if not is_admin(user_id):
        return
    promo_codes = db.list_promo_codes()
    if not promo_codes:
        await bot.send_message(chat_id=chat_id, text="📋 Промокодов нет.")
        return
    active = [c for c in promo_codes if not c["is_used"]]
    used = [c for c in promo_codes if c["is_used"]]
    lines = ["🎟 *Промокоды*\n\n*Активные:*"]
    for c in active:
        lines.append(f"• `{c['code']}` — {c['amount']} токенов")
    lines.append(f"\n*Использованы ({len(used)})*")
    for c in used[:5]:
        lines.append(f"• ~~`{c['code']}`~~ — {c['amount']} токенов (user {c.get('used_by', '?')})")
    lines.append("\n/admin_create_promo CODE AMOUNT — создать промокод\n/admin_delete_promo CODE — удалить")
    await bot.send_message(chat_id=chat_id, text="\n".join(lines), format="markdown")


async def handle_create_promo(chat_id: int, user_id: int, code: str, amount_str: str, bot: Bot):
    if not is_admin(user_id):
        return
    try:
        amount = int(amount_str)
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="❌ Неверное количество токенов.")
        return
    code = code.strip().upper()
    if db.add_promo_code(code, amount):
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Промокод *{code}* создан — {amount} токенов.",
            format="markdown",
        )
    else:
        await bot.send_message(chat_id=chat_id, text=f"❌ Промокод `{code}` уже существует.", format="markdown")


async def handle_delete_promo(chat_id: int, user_id: int, code: str, bot: Bot):
    if not is_admin(user_id):
        return
    if db.delete_promo_code(code.strip().upper()):
        await bot.send_message(chat_id=chat_id, text=f"✅ Промокод удалён.")
    else:
        await bot.send_message(chat_id=chat_id, text=f"❌ Промокод не найден.")


async def handle_add_balance(chat_id: int, user_id: int, target_id_str: str, amount_str: str, bot: Bot):
    if not is_admin(user_id):
        return
    try:
        target_id = int(target_id_str)
        amount = int(amount_str)
    except ValueError:
        await bot.send_message(chat_id=chat_id, text="❌ Неверные параметры.\nФормат: /admin_balance USER_ID AMOUNT")
        return
    db.update_balance(target_id, amount)
    new_balance = db.get_balance(target_id)
    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ Пользователю `{target_id}` добавлено *{amount}* токенов.\nНовый баланс: *{new_balance}*",
        format="markdown",
    )


async def handle_broadcast(chat_id: int, user_id: int, text_to_send: str, bot: Bot):
    if not is_admin(user_id):
        return
    users = db.get_all_users()
    sent = 0
    failed = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u["user_id"], text=text_to_send)
            sent += 1
        except Exception:
            failed += 1
    await bot.send_message(
        chat_id=chat_id,
        text=f"📢 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}",
    )


async def cmd_stats(chat_id: int, user_id: int, bot: Bot):
    if not is_admin(user_id):
        return
    stats = db.get_stats()
    text = (
        "📊 *Статистика*\n\n"
        f"👤 Всего пользователей: `{stats.get('total_users', 0)}`\n"
        f"💰 Пополнений: `{stats.get('total_payments', 0)}`\n"
        f"🎟 Промокодов: `{stats.get('total_promo_codes', 0)}`\n"
        f"  Активных: `{stats.get('active_promo_codes', 0)}`\n"
    )
    await bot.send_message(chat_id=chat_id, text=text, format="markdown")
