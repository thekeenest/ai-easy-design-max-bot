"""
Start handler: /start, bot_started, /info, /cancel, back-to-menu callbacks.
"""
from maxapi import Bot
from maxapi.types import MessageCreated, BotStarted, MessageCallback

from config import config
from database_pg import AsyncDatabase
from keyboards.menu import (
    get_main_menu_kb, get_photo_menu_kb, get_video_menu_kb,
    get_avatar_menu_kb, get_help_kb,
)
from state_manager import state_mgr

db = AsyncDatabase()

WELCOME_TEXT = (
    "Добро пожаловать! 👋\n\n"
    "Я — ваш персональный AI-ассистент 🤖✨\n\n"
    "🎨 *AI фото:* Seedream · GPT Images · Flux Kontext · NanoBanana · Фотосессия\n"
    "🎬 *AI видео:* VEO3 · Runway · Kling v2.1\n"
    "🎭 *Аватары:* Flux LoRA\n"
    "🎵 *Музыка:* Suno AI\n"
    "🤖 *AI чат:* ChatGPT (бесплатно)\n\n"
    "Выберите раздел:"
)


async def cmd_start(event: MessageCreated, bot: Bot):
    user_id = event.message.sender.user_id
    username = event.message.sender.name or str(user_id)
    await db.add_user(user_id, username)
    state_mgr.clear(user_id)
    await bot.send_message(
        chat_id=event.message.recipient.chat_id,
        text=WELCOME_TEXT,
        attachments=get_main_menu_kb(),
        format="markdown",
    )


async def on_bot_started(event: BotStarted, bot: Bot):
    user_id = event.user.user_id
    username = event.user.name or str(user_id)
    await db.add_user(user_id, username)
    state_mgr.clear(user_id)
    await bot.send_message(
        chat_id=event.chat_id,
        text=WELCOME_TEXT,
        attachments=get_main_menu_kb(),
        format="markdown",
    )


async def cmd_info(chat_id: int, bot: Bot):
    pkg_lines = "\n".join(
        f"• {p['label']}: {p['tokens']} токенов — {p['price_rub']}₽"
        for p in config.TOKEN_PACKAGES
    )
    text = (
        "ℹ️ *О боте и тарифах*\n\n"
        "Бот предоставляет доступ к AI-генерации контента: фото, видео, аватары, музыка.\n"
        "Чат с AI-ассистентом — *бесплатный* 🆓\n\n"
        "📦 *Пакеты токенов:*\n"
        f"{pkg_lines}\n\n"
        "💳 Оплата банковской картой и СБП.\n"
        "🔄 Возврат — по запросу в поддержку (14 дней).\n\n"
        "📋 *Реквизиты:*\n"
        f"{config.BUSINESS_NAME}\n"
        f"ИНН: {config.BUSINESS_INN}\n"
        f"Тел.: {config.BUSINESS_PHONE}\n\n"
        f"💬 Поддержка: {config.SUPPORT_USERNAME}"
    )
    await bot.send_message(chat_id=chat_id, text=text, format="markdown")


async def cmd_cancel(chat_id: int, user_id: int, bot: Bot):
    state_mgr.clear(user_id)
    await bot.send_message(
        chat_id=chat_id,
        text="❌ Операция отменена.",
        attachments=get_main_menu_kb(),
    )


# ── Menu navigation callbacks ──────────────────────────────────────────────────

async def handle_nav_callback(payload: str, chat_id: int, user_id: int, bot: Bot):
    state_mgr.clear(user_id)
    if payload == "menu:main" or payload == "cancel":
        await bot.send_message(
            chat_id=chat_id, text="Главное меню:", attachments=get_main_menu_kb()
        )
    elif payload == "menu:photo":
        await bot.send_message(
            chat_id=chat_id, text="🖼 *AI фото*\n\nВыберите инструмент:",
            attachments=get_photo_menu_kb(), format="markdown",
        )
    elif payload == "menu:video":
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "🎬 *AI Видео Студия*\n\n"
                "🌟 VEO3 — генерация видео (Google)\n"
                "🎬 RUNWAY — трансформация видео\n"
                "🎞 KLING v2.1 — видео из изображений\n\n"
                "Выберите инструмент:"
            ),
            attachments=get_video_menu_kb(),
            format="markdown",
        )
    elif payload == "menu:avatar":
        await bot.send_message(
            chat_id=chat_id,
            text="🎭 *Аватары*\n\nСоздайте персональный AI-аватар:",
            attachments=get_avatar_menu_kb(),
            format="markdown",
        )
    elif payload == "menu:help":
        await bot.send_message(
            chat_id=chat_id,
            text=f"💡 *Поддержка*\n\nНапишите нам: {config.SUPPORT_USERNAME}",
            attachments=get_help_kb(),
            format="markdown",
        )
    elif payload == "menu:ai":
        from handlers.ai_assistant import show_ai_menu
        await show_ai_menu(chat_id, user_id, bot)
    elif payload == "menu:suno":
        from handlers.suno import show_suno_menu
        await show_suno_menu(chat_id, user_id, bot)
    elif payload == "menu:profile":
        from handlers.user import show_profile
        await show_profile(chat_id, user_id, bot)
    elif payload == "help:support":
        await bot.send_message(
            chat_id=chat_id,
            text=f"📩 Напишите в поддержку: {config.SUPPORT_USERNAME}",
        )
