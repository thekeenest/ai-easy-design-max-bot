# AI Easy Design — MAX Messenger Bot

Mirror of the Telegram AI bot for **MAX messenger** (`max.ru`).

All AI backends (fal.ai, OpenAI, Google VEO3, Suno, etc.) and the SQLite database are shared
with the Telegram version. Only the messaging layer is adapted to the MAX Bot API.

---

## Setup

### 1. Create the bot in MAX messenger

1. Open MAX messenger app (iOS / Android / Web)
2. Find **@MasterBot** (official bot creation bot)
3. Send `/create`
4. Enter a username for your bot (Latin + Cyrillic, up to 59 chars, no emojis)
5. MasterBot will reply with your **bot token** — copy it

### 2. Configure the token

Set `MAX_BOT_TOKEN` in your environment:

```bash
# Option A — environment variable
export MAX_BOT_TOKEN="your_token_here"

# Option B — add to .env in the project root
echo "MAX_BOT_TOKEN=your_token_here" >> ../.env
```

Or edit `config.py` directly and replace `"YOUR_MAX_BOT_TOKEN_HERE"`.

### 3. Install dependencies

```bash
# From the max_bot/ directory
pip install -r requirements.txt

# Make sure parent project deps are also installed
cd ..
pip install -r requirements.txt
```

### 4. Initialize the database (if not done for Telegram bot already)

```bash
# From the parent directory
python init_database.py
```

### 5. Run the MAX bot

```bash
# From the max_bot/ directory
python main.py

# Or from the parent directory
python max_bot/main.py
```

---

## Architecture

```
max_bot/
├── main.py               # Entry point: polling loop + all background workers
├── config.py             # Re-exports parent config + reads MAX_BOT_TOKEN
├── state_manager.py      # In-memory FSM (replaces aiogram FSMContext)
├── requirements.txt
├── README.md
├── handlers/
│   ├── start.py          # /start, bot_started, /info, navigation
│   ├── user.py           # Profile, promo codes
│   ├── payment_tochka.py # Tochka Bank payments
│   ├── generate.py       # Seedream + GPT Images text→image
│   ├── video.py          # Kling / Runway / VEO3 video
│   ├── ai_assistant.py   # ChatGPT text/voice/vision/calorie
│   ├── photo_session.py  # Flux LoRA photo session
│   ├── flux_kontext.py   # Flux Kontext image editing
│   ├── nano_banana.py    # NanoBanana image editing
│   ├── suno.py           # Suno AI music generation
│   ├── avatar.py         # Flux LoRA avatar training
│   ├── image_to_prompt.py # Image → text prompt
│   └── admin.py          # Admin commands
└── keyboards/
    └── menu.py           # MAX inline keyboard builders
```

### Shared with parent Telegram bot
- `database.py` — SQLite with all job queues and user data
- `utils_fal.py` — fal.ai client (Flux, Kling, Runway, NanoBanana, Photosession)
- `utils_tochka.py` — Tochka Bank payment API
- `utils_ai_assistant.py` — OpenAI ChatGPT + Whisper + GPT-4 Vision
- `utils_seedream.py` — Seedream text-to-image
- `utils_suno.py` — Suno music generation
- `utils_veo3.py` — Google VEO3 video
- `config.py` — all API keys, costs, token packages

---

## Key differences from Telegram version

| Aspect | Telegram (aiogram) | MAX (maxapi) |
|--------|-------------------|--------------|
| Keyboards | `reply_markup=InlineKeyboardMarkup(...)` | `attachments=[ButtonsPayload(...).pack()]` |
| Send photo | `bot.send_photo(chat_id, BufferedInputFile(...))` | `bot.send_message(..., attachments=[InputMediaBuffer(...)])` |
| State | `aiogram FSMContext` | Custom `StateManager` (in-memory) |
| User ID | `message.from_user.id` | `event.message.sender.user_id` |
| Message text | `message.text` | `event.message.body.text` |
| Callback data | `callback_query.data` | `callback.payload` |
| Bot started | `CommandStart()` filter | `@dp.bot_started()` decorator |

---

## Admin commands

All commands require your user_id to be in `config.ADMIN_IDS`.

| Command | Action |
|---------|--------|
| `/admin` | Show admin dashboard |
| `/admin_promo` | List all promo codes |
| `/admin_create_promo CODE AMOUNT` | Create new promo code |
| `/admin_delete_promo CODE` | Delete a promo code |
| `/admin_balance USER_ID AMOUNT` | Add tokens to user |
| `/admin_broadcast TEXT` | Broadcast message to all users |
| `/admin_stats` | Show statistics |

---

## Bank acquiring (Tochka Bank)

The bot description is set automatically on startup via the `/info` command.
For Tochka Bank acquiring approval, direct reviewers to send `/info` to the bot — it returns:
- Business name, INN, phone
- Full price list
- Payment and refund terms

---

## Token Packages

| Package | Tokens | Price | Savings |
|---------|--------|-------|---------|
| 🌱 Стартовый | 100 | 299₽ | — |
| ⭐ Оптимальный | 200 | 499₽ | 16% |
| 💎 Продвинутый | 500 | 1099₽ | 26% |
| 👑 Максимум | 1000 | 1999₽ | 33% |

AI text chat is **free** (unlimited). Tokens are used only for media generation.
