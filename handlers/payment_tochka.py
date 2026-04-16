"""
Tochka Bank payment handler for MAX messenger.
Same backend logic as Telegram version, different UI layer.
"""
import logging

from maxapi import Bot

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import get_packages_kb, get_pay_link_kb, get_check_again_kb, get_main_menu_kb
from utils_tochka import (
    PAID_STATUSES,
    generate_order_id,
    get_payment_status,
    create_payment_link,
)

logger = logging.getLogger(__name__)
db = AsyncDatabase()


def build_packages_text() -> str:
    lines = [
        "🪙 *Покупка токенов*\n",
        "Токены тратятся на генерацию контента — *чат с ботом бесплатный* 🆓\n",
    ]
    for pkg in config.TOKEN_PACKAGES:
        bonus = pkg.get("bonus_pct", 0)
        bonus_str = f"  ✅ Экономия {bonus}%" if bonus else ""
        lines.append(f"{pkg['label']} — *{pkg['price_rub']}₽* → {pkg['tokens']} токенов{bonus_str}")
    lines.append(
        "\n⚙️ *На что тратятся токены:*\n"
        "• Фото (Seedream/GPT): 8–12 токенов\n"
        "• AI Фотосессия: 8 токенов/фото\n"
        "• Flux Kontext / NanoBanana: 10 токенов\n"
        "• Kling видео (5 сек): 50 токенов\n"
        "• Runway видео: 120 токенов\n"
        "• VEO3 видео: 400 токенов\n"
        "• AI аватар: 700 токенов\n"
        "• Музыка Suno: 50 токенов\n"
        "• Голос / зрение AI: 3–5 токенов\n\n"
        "ℹ️ Минимальная сумма платежа — 50₽"
    )
    return "\n".join(lines)


async def show_packages(chat_id: int, user_id: int, bot: Bot):
    await db.add_user(user_id, str(user_id))
    await bot.send_message(
        chat_id=chat_id,
        text=build_packages_text(),
        attachments=get_packages_kb(),
        format="markdown",
    )


async def handle_package_selected(chat_id: int, user_id: int, package_id: str, bot: Bot):
    pkg = next((p for p in config.TOKEN_PACKAGES if p["id"] == package_id), None)
    if not pkg:
        await bot.send_message(chat_id=chat_id, text="❌ Пакет не найден.")
        return

    order_id = generate_order_id(user_id, package_id)
    description = f"{pkg['tokens']} токенов для MAX-бота"

    await db.add_user(user_id, str(user_id))
    await db.create_tochka_payment(
        user_id=user_id,
        order_id=order_id,
        package_id=package_id,
        tokens_amount=pkg["tokens"],
        amount_rub=pkg["price_rub"],
    )

    result = await create_payment_link(
        jwt_token=config.TOCHKA_JWT_TOKEN,
        customer_code=config.TOCHKA_CUSTOMER_CODE,
        amount_rub=float(pkg["price_rub"]),
        order_id=order_id,
        description=description,
    )

    if not result:
        await bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Не удалось создать платёж. Напишите в поддержку: {config.SUPPORT_USERNAME}",
        )
        await db.fail_tochka_payment(order_id, "init_failed")
        return

    operation_id = result["operationId"]
    payment_url = result["paymentUrl"]
    await db.update_tochka_operation_id(order_id, operation_id)

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"🛒 *{pkg['label']}*\n\n"
            f"💰 Сумма: *{pkg['price_rub']}₽*\n"
            f"🪙 Токены: *{pkg['tokens']}*\n\n"
            "Нажмите *Оплатить* и завершите оплату в браузере.\n"
            "Принимаем банковские карты и СБП 🏦\n\n"
            "Токены зачислятся автоматически после оплаты.\n"
            "После оплаты нажмите *Проверить оплату*."
        ),
        attachments=get_pay_link_kb(payment_url, order_id),
        format="markdown",
    )
    logger.info(f"Tochka payment created: user={user_id} order={order_id} amount={pkg['price_rub']}RUB")


async def handle_check_payment(chat_id: int, user_id: int, order_id: str, bot: Bot):
    payment = await db.get_tochka_payment_by_order(order_id)
    if not payment:
        await bot.send_message(chat_id=chat_id, text="❌ Платёж не найден.")
        return

    if payment["user_id"] != user_id:
        await bot.send_message(chat_id=chat_id, text="❌ Доступ запрещён.")
        return

    if payment["status"] == "paid":
        balance = await db.get_balance(user_id)
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Оплата уже подтверждена!\n🪙 Ваш баланс: *{balance} токенов*",
            format="markdown",
        )
        return

    if not payment.get("operation_id"):
        await bot.send_message(
            chat_id=chat_id,
            text="⏳ Платёж ещё создаётся. Попробуйте позже.",
            attachments=get_check_again_kb(order_id),
        )
        return

    state = await get_payment_status(
        jwt_token=config.TOCHKA_JWT_TOKEN,
        operation_id=payment["operation_id"],
    )

    if not state:
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ Не удалось получить статус. Попробуйте снова.",
            attachments=get_check_again_kb(order_id),
        )
        return

    tochka_status = state.get("status", "")
    logger.info(f"Tochka check: order={order_id} status={tochka_status}")

    if tochka_status in PAID_STATUSES:
        credited = await db.confirm_tochka_payment(order_id)
        balance = await db.get_balance(user_id)
        if credited:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "🎉 *Оплата подтверждена!*\n\n"
                    f"🪙 Зачислено: *{payment['tokens_amount']} токенов*\n"
                    f"💰 Ваш баланс: *{balance} токенов*\n\n"
                    "Теперь вы можете использовать все функции бота! 🚀"
                ),
                attachments=get_main_menu_kb(),
                format="markdown",
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=f"✅ Оплата уже была зачислена ранее.\n🪙 Баланс: *{balance} токенов*",
                format="markdown",
            )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=f"⏳ Платёж обрабатывается (статус: {tochka_status or 'в обработке'}).\n\nЗавершите оплату и нажмите *Проверить оплату*.",
            attachments=get_check_again_kb(order_id),
            format="markdown",
        )
