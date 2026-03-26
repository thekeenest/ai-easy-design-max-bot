"""
MAX messenger keyboard builders.
Keyboards in MAX are inline_keyboard *attachments* — not a separate reply_markup field.
All functions here return a list of attachment objects ready to pass as `attachments=`.
"""
from maxapi.types import CallbackButton, LinkButton, ButtonsPayload
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from config import config as parent_cfg


# ── Helper ─────────────────────────────────────────────────────────────────────

def cb(text: str, data: str) -> CallbackButton:
    return CallbackButton(text=text, payload=data)


def link(text: str, url: str) -> LinkButton:
    return LinkButton(text=text, url=url)


def build(*rows) -> list:
    """Build keyboard attachment from a list of button rows."""
    buttons = [list(row) for row in rows]
    return [ButtonsPayload(buttons=buttons).pack()]


# ── Menus ──────────────────────────────────────────────────────────────────────

def get_main_menu_kb() -> list:
    return build(
        [cb("🖼 AI фото", "menu:photo"), cb("🎬 AI видео", "menu:video")],
        [cb("🎭 Аватары", "menu:avatar"), cb("🤖 Спросить AI", "menu:ai")],
        [cb("🎵 Suno AI", "menu:suno")],
        [cb("💼 Мой профиль", "menu:profile"), cb("💡 Помощь", "menu:help")],
    )


def get_photo_menu_kb() -> list:
    return build(
        [cb("✨ Seedream", "photo:seedream"), cb("🖼 GPT Images", "photo:gpt")],
        [cb("📷 AI Фотосессия", "photo:session")],
        [cb("🌀 Flux Kontext", "photo:flux"), cb("🎭 NanoBanana", "photo:nano")],
        [cb("🔍 Фото → Промпт", "photo:img2prompt")],
        [cb("⬅️ Назад", "menu:main")],
    )


def get_video_menu_kb() -> list:
    return build(
        [cb("🎞 KLING v2.1", "video:kling"), cb("🎬 RUNWAY", "video:runway")],
        [cb("🌟 VEO3 (Google)", "video:veo3")],
        [cb("⬅️ Назад", "menu:main")],
    )


def get_avatar_menu_kb() -> list:
    return build(
        [cb("🧑‍🎨 Создать аватар", "avatar:create")],
        [cb("⬅️ Назад", "menu:main")],
    )


def get_profile_kb() -> list:
    return build(
        [cb("💳 Пополнить токены", "buy_credits")],
        [cb("🎟 Промокод", "enter_promo")],
        [cb("⬅️ Назад", "menu:main")],
    )


def get_balance_kb() -> list:
    return get_profile_kb()


def get_packages_kb() -> list:
    rows = []
    for pkg in parent_cfg.TOKEN_PACKAGES:
        bonus = pkg.get("bonus_pct", 0)
        if bonus:
            label = f"{pkg['label']} — {pkg['tokens']} токенов • {pkg['price_rub']}₽ (-{bonus}%)"
        else:
            label = f"{pkg['label']} — {pkg['tokens']} токенов • {pkg['price_rub']}₽"
        rows.append([cb(label, f"tchpay:pkg:{pkg['id']}")])
    rows.append([cb("🎟 Промокод", "enter_promo")])
    rows.append([cb("⬅️ Назад", "menu:profile")])
    return [ButtonsPayload(buttons=rows).pack()]


def get_pay_link_kb(payment_url: str, order_id: str) -> list:
    return build(
        [link("💳 Оплатить картой / СБП", payment_url)],
        [cb("✅ Проверить оплату", f"tchpay:check:{order_id}")],
        [cb("⬅️ Другой пакет", "buy_credits")],
    )


def get_check_again_kb(order_id: str) -> list:
    return build(
        [cb("🔄 Проверить ещё раз", f"tchpay:check:{order_id}")],
        [cb("⬅️ Другой пакет", "buy_credits")],
    )


def get_cancel_kb() -> list:
    return build([cb("❌ Отмена", "cancel")])


def get_back_kb() -> list:
    return build([cb("⬅️ Назад", "menu:main")])


def get_help_kb() -> list:
    return build(
        [cb("📩 Написать в поддержку", "help:support")],
        [cb("⬅️ Назад", "menu:main")],
    )


# ── AI Assistant ───────────────────────────────────────────────────────────────

def get_ai_mode_kb() -> list:
    return build(
        [cb("💬 Текст", "ai:text"), cb("🎤 Голос", "ai:voice")],
        [cb("🖼 Фото-анализ", "ai:vision"), cb("🍽 Калории", "ai:calorie")],
        [cb("⬅️ Назад", "menu:main")],
    )


def get_ai_ask_again_kb() -> list:
    return build(
        [cb("🔄 Ещё вопрос", "ai:text")],
        [cb("⬅️ В меню", "menu:main")],
    )


# ── Photo session ──────────────────────────────────────────────────────────────

def get_photosession_style_kb() -> list:
    styles = list(parent_cfg.STYLES.keys())
    rows = []
    row = []
    for i, style in enumerate(styles):
        row.append(cb(style, f"pstyle:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([cb("❌ Отмена", "cancel")])
    return [ButtonsPayload(buttons=rows).pack()]


# ── Flux Kontext ───────────────────────────────────────────────────────────────

def get_flux_kontext_count_kb() -> list:
    return build(
        [cb("1 фото", "flux:count:1"), cb("2 фото", "flux:count:2")],
        [cb("3 фото", "flux:count:3"), cb("4 фото", "flux:count:4")],
        [cb("❌ Отмена", "cancel")],
    )


# ── Video ──────────────────────────────────────────────────────────────────────

def get_kling_duration_kb() -> list:
    return build(
        [cb("⚡ 5 сек (50 токенов)", "kling:5"), cb("🎬 10 сек (100 токенов)", "kling:10")],
        [cb("❌ Отмена", "cancel")],
    )


def get_runway_aspect_kb() -> list:
    return build(
        [cb("📱 Вертикальный 9:16", "runway:aspect:9:16"), cb("📺 Горизонтальный 16:9", "runway:aspect:16:9")],
        [cb("⬜ Квадратный 1:1", "runway:aspect:1:1")],
        [cb("❌ Отмена", "cancel")],
    )


def get_recreate_seedream_kb() -> list:
    return build([cb("🔄 Повторить с тем же промптом", "regen:seedream")])


def get_recreate_video_kb() -> list:
    return build([cb("🔄 Создать ещё видео", "regen:video")])
