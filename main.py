"""
MAX messenger bot — entry point.

Runs:
  • Event polling loop (maxapi Dispatcher)
  • All background job-queue workers (same logic as Telegram main.py,
    adapted to use MaxBot.send_message / send_media instead of aiogram)

Handlers are mounted in register_handlers() and route via:
  • dp.message_created() — text / media messages
  • dp.bot_started()     — user presses Start button
  • dp.message_callback() — inline button presses
"""

import asyncio
import concurrent.futures
import logging
import os
import random
import sys
import traceback
from typing import List, Optional

# ── Make parent project importable ────────────────────────────────────────────
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

import aiohttp
from maxapi import Bot, Dispatcher
from maxapi.filters import F
from maxapi.types import (
    BotStarted, MessageCreated, MessageCallback,
    InputMediaBuffer,
)
from maxapi.types import CallbackButton, ButtonsPayload
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from config import MAX_BOT_TOKEN, config
from database_pg import AsyncDatabase
from state_manager import state_mgr

# ── Handlers ──────────────────────────────────────────────────────────────────
from handlers import start as start_h
from handlers import user as user_h
from handlers import payment_tochka as pay_h
from handlers import generate as gen_h
from handlers import video as video_h
from handlers import ai_assistant as ai_h
from handlers import photo_session as ps_h
from handlers import flux_kontext as flux_h
from handlers import nano_banana as nano_h
from handlers import suno as suno_h
from handlers import avatar as avatar_h
from handlers import image_to_prompt as i2p_h
from handlers import admin as admin_h
from keyboards.menu import get_main_menu_kb, get_ai_ask_again_kb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=16)

bot = Bot(token=MAX_BOT_TOKEN)
dp = Dispatcher()


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: upload bytes and send as image/video/audio/document
# ═══════════════════════════════════════════════════════════════════════════════

async def send_photo_bytes(chat_id: int, data: bytes, caption: str = "", attachments: list = None, filename: str = "image.jpg"):
    """Upload bytes and send as a photo message with optional inline keyboard."""
    media = InputMediaBuffer(data=data, filename=filename)
    all_att = [media] + (attachments or [])
    await bot.send_message(chat_id=chat_id, text=caption, attachments=all_att, format="markdown")


async def send_video_bytes(chat_id: int, data: bytes, caption: str = "", attachments: list = None, filename: str = "video.mp4"):
    media = InputMediaBuffer(data=data, filename=filename)
    all_att = [media] + (attachments or [])
    await bot.send_message(chat_id=chat_id, text=caption, attachments=all_att, format="markdown")


async def send_audio_bytes(chat_id: int, data: bytes, caption: str = "", filename: str = "audio.mp3"):
    media = InputMediaBuffer(data=data, filename=filename)
    await bot.send_message(chat_id=chat_id, text=caption, attachments=[media], format="markdown")


async def send_video_url(chat_id: int, url: str, caption: str = "", attachments: list = None):
    """Download video from URL then send via MAX upload."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
            data = await resp.read()
    await send_video_bytes(chat_id, data, caption, attachments)


async def send_audio_url(chat_id: int, url: str, caption: str = "", filename: str = "audio.mp3"):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            data = await resp.read()
    await send_audio_bytes(chat_id, data, caption, filename)


# ═══════════════════════════════════════════════════════════════════════════════
# Background workers  (same logic as Telegram main.py, MAX API calls)
# ═══════════════════════════════════════════════════════════════════════════════

async def process_seedream_job_queue():
    from utils_seedream import generate_seedream_image
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_seedream_jobs(limit=1)
            for job in jobs:
                try:
                    image_path, seed, error, cdn_url = await generate_seedream_image(job["prompt"])
                    if error or not image_path:
                        await db.update_seedream_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка Seedream: {error}")
                        continue
                    with open(image_path, "rb") as f:
                        img_bytes = f.read()
                    caption = (
                        f"✨ *Seedream готово!*\n\n"
                        f"Промпт: _{job['prompt'][:200]}_"
                    )
                    recreate_kb = [ButtonsPayload(buttons=[[CallbackButton(text="🔄 Повторить", payload=f"regen:seedream:{job['id']}")]]).pack()]
                    await send_photo_bytes(job["user_id"], img_bytes, caption, recreate_kb, "seedream.jpg")
                    await db.update_seedream_job_status(job["id"], "completed", image_path=image_path, seed=seed)
                    await db.record_tool_usage(job["user_id"], job["username"], "seedream")
                except Exception as e:
                    await db.update_seedream_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Seedream job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Seedream queue error: {e}")
        await asyncio.sleep(5)


async def process_openai_image_job_queue():
    db = AsyncDatabase()
    while True:
        try:
            pending = await db.get_pending_openai_image_jobs()
            tasks = []
            for job in pending:
                if job["status"] == "processing" or len(tasks) >= 3:
                    continue
                await db.update_openai_image_job_status(job["id"], "processing")
                tasks.append(asyncio.create_task(
                    _process_openai_image_job(db, job)
                ))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"OpenAI image queue error: {e}")
        await asyncio.sleep(5)


async def _process_openai_image_job(db: AsyncDatabase, job: dict):
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    try:
        from utils import generate_openai_image
        image_paths, error = await generate_openai_image(
            prompt=job["prompt"],
            num_images=job.get("num_images", 1),
            job_type=job.get("job_type", "general"),
            product_images=job.get("product_images"),
        )
        if error or not image_paths:
            await db.update_openai_image_job_status(job["id"], "failed", error_message=error or "failed")
            if is_fal_balance_error(str(error or "")):
                asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
            else:
                await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка GPT Images: {error}")
            return
        for i, path in enumerate(image_paths):
            with open(path, "rb") as f:
                img_bytes = f.read()
            caption = f"🖼 *GPT Image {i+1}/{len(image_paths)}*\n\n_{job['prompt'][:150]}_"
            await send_photo_bytes(job["user_id"], img_bytes, caption, filename=f"gpt_image_{i}.jpg")
        await db.update_openai_image_job_status(job["id"], "completed")
        await db.record_tool_usage(job["user_id"], job.get("username", ""), "gpt_image")
    except Exception as e:
        await db.update_openai_image_job_status(job["id"], "failed", error_message=str(e))
        logger.error(f"OpenAI image job {job['id']} failed: {e}")


async def process_video_job_queue():
    """Kling video queue."""
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_video_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_video_job_status(job["id"], "processing")
                    from utils_fal import generate_kling_video
                    video_url, error = await generate_kling_video(
                        image_path=job["image_path"],
                        prompt=job["prompt"],
                        duration=job.get("duration", 5),
                    )
                    if error or not video_url:
                        await db.update_video_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка Kling: {error}")
                        continue
                    caption = f"🎬 *Kling видео готово!*\n\n_{job['prompt'][:150]}_"
                    await send_video_url(job["user_id"], video_url, caption)
                    await db.update_video_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "kling")
                except Exception as e:
                    await db.update_video_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Kling job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Video queue error: {e}")
        await asyncio.sleep(10)


async def process_runway_video_job_queue():
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_runway_video_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_runway_video_job_status(job["id"], "processing")
                    from utils_fal import generate_runway_video
                    video_url, error = await generate_runway_video(
                        image_path=job["image_path"],
                        prompt=job["prompt"],
                        aspect_ratio=job.get("aspect_ratio", "16:9"),
                    )
                    if error or not video_url:
                        await db.update_runway_video_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка Runway: {error}")
                        continue
                    caption = f"🎬 *Runway видео готово!*"
                    await send_video_url(job["user_id"], video_url, caption)
                    await db.update_runway_video_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "runway")
                except Exception as e:
                    await db.update_runway_video_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Runway job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Runway queue error: {e}")
        await asyncio.sleep(15)


async def process_veo3_video_job_queue():
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_veo3_video_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_veo3_video_job_status(job["id"], "processing")
                    from utils_veo3 import generate_veo3_video
                    video_url, error = await generate_veo3_video(job["prompt"])
                    if error or not video_url:
                        await db.update_veo3_video_job_status(job["id"], "failed", error_message=error or "failed")
                        await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка VEO3: {error}")
                        continue
                    caption = f"🌟 *VEO3 видео готово!*\n\n_{job['prompt'][:150]}_"
                    await send_video_url(job["user_id"], video_url, caption)
                    await db.update_veo3_video_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "veo3")
                except Exception as e:
                    await db.update_veo3_video_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"VEO3 job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"VEO3 queue error: {e}")
        await asyncio.sleep(30)


async def process_flux_kontext_job_queue():
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_flux_kontext_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_flux_kontext_job_status(job["id"], "processing")
                    image_urls = [u.strip() for u in (job.get("image_paths") or "").split(",") if u.strip()]
                    from utils_fal import generate_flux_kontext
                    result_url, error = await generate_flux_kontext(
                        image_urls=image_urls,
                        prompt=job["prompt"],
                    )
                    if error or not result_url:
                        await db.update_flux_kontext_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка Flux Kontext: {error}")
                        continue
                    async with aiohttp.ClientSession() as session:
                        async with session.get(result_url) as resp:
                            img_bytes = await resp.read()
                    caption = f"🌀 *Flux Kontext готово!*\n\n_{job['prompt'][:150]}_"
                    await send_photo_bytes(job["user_id"], img_bytes, caption, filename="flux_kontext.jpg")
                    await db.update_flux_kontext_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "flux_kontext")
                except Exception as e:
                    await db.update_flux_kontext_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Flux Kontext job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Flux Kontext queue error: {e}")
        await asyncio.sleep(5)


async def process_nano_banana_job_queue():
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_nano_banana_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_nano_banana_job_status(job["id"], "processing")
                    from utils_nano_banana import edit_image_nano_banana
                    result_url, error = await edit_image_nano_banana(
                        image_path=job["image_path"],
                        prompt=job["prompt"],
                    )
                    if error or not result_url:
                        await db.update_nano_banana_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка NanoBanana: {error}")
                        continue
                    async with aiohttp.ClientSession() as session:
                        async with session.get(result_url) as resp:
                            img_bytes = await resp.read()
                    caption = f"🎭 *NanoBanana готово!*\n\n_{job['prompt'][:150]}_"
                    await send_photo_bytes(job["user_id"], img_bytes, caption, filename="nano_banana.jpg")
                    await db.update_nano_banana_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "nano_banana")
                except Exception as e:
                    await db.update_nano_banana_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"NanoBanana job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"NanoBanana queue error: {e}")
        await asyncio.sleep(5)


async def process_photosession_queue():
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_photosession_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_photosession_job_status(job["id"], "processing")
                    photo_paths = [p.strip() for p in (job.get("photo_paths") or "").split(",") if p.strip()]
                    from utils_fal import generate_photosession
                    result_urls, error = await generate_photosession(
                        photo_paths=photo_paths,
                        style_prompt=job["style_prompt"],
                        trigger_phrase="photo",
                    )
                    if error or not result_urls:
                        await db.update_photosession_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка фотосессии: {error}")
                        continue
                    await bot.send_message(
                        chat_id=job["user_id"],
                        text=f"📷 *Фотосессия готова!*\nСтиль: *{job.get('style_name', '')}*",
                        format="markdown",
                    )
                    for url in result_urls:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(url) as resp:
                                img_bytes = await resp.read()
                        await send_photo_bytes(job["user_id"], img_bytes, filename="photosession.jpg")
                    await db.update_photosession_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "photosession")
                except Exception as e:
                    await db.update_photosession_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Photosession job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Photosession queue error: {e}")
        await asyncio.sleep(15)


async def process_avatar_training_queue():
    from utils_alerts import is_fal_balance_error, alert_fal_balance
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_avatar_training_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_avatar_training_job_status(job["id"], "processing")
                    from utils_fal import train_flux_lora_avatar
                    lora_path, error = await train_flux_lora_avatar(
                        user_dir=job["user_dir"],
                        trigger_phrase=job["trigger_phrase"],
                    )
                    if error or not lora_path:
                        await db.update_avatar_training_job_status(job["id"], "failed", error_message=error or "failed")
                        if is_fal_balance_error(str(error or "")):
                            asyncio.create_task(alert_fal_balance(job["user_id"], str(error or "")))
                            await bot.send_message(chat_id=job["user_id"], text="🔧 Технические неполадки, скоро все исправим! Ваши токены не списались зря, они в безопасности.")
                        else:
                            await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка обучения аватара: {error}")
                        continue
                    await db.save_user_lora(job["user_id"], job["trigger_phrase"], lora_path)
                    await db.update_avatar_training_job_status(job["id"], "completed", lora_path=lora_path)
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "avatar_training")
                    await bot.send_message(
                        chat_id=job["user_id"],
                        text=(
                            f"🎉 *Аватар обучен!*\n\n"
                            f"Trigger: *{job['trigger_phrase']}*\n\n"
                            "Теперь вы можете использовать аватар в AI Фотосессии."
                        ),
                        format="markdown",
                        attachments=get_main_menu_kb(),
                    )
                except Exception as e:
                    await db.update_avatar_training_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Avatar training job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Avatar training queue error: {e}")
        await asyncio.sleep(30)


async def process_suno_job_queue():
    db = AsyncDatabase()
    while True:
        try:
            jobs = await db.get_pending_suno_jobs(limit=1)
            for job in jobs:
                try:
                    await db.update_suno_job_status(job["id"], "processing")
                    from utils_suno import generate_suno_music
                    audio_url, error = await generate_suno_music(job["prompt"])
                    if error or not audio_url:
                        await db.update_suno_job_status(job["id"], "failed", error_message=error or "failed")
                        await bot.send_message(chat_id=job["user_id"], text=f"⚠️ Ошибка Suno: {error}")
                        continue
                    caption = f"🎵 *Suno музыка готова!*\n\n_{job['prompt'][:150]}_"
                    await send_audio_url(job["user_id"], audio_url, caption, "suno.mp3")
                    await db.update_suno_job_status(job["id"], "completed")
                    await db.record_tool_usage(job["user_id"], job.get("username", ""), "suno")
                except Exception as e:
                    await db.update_suno_job_status(job["id"], "failed", error_message=str(e))
                    logger.error(f"Suno job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"Suno queue error: {e}")
        await asyncio.sleep(10)


async def process_ai_assistant_job_queue():
    """Process AI assistant jobs and send results via MAX."""
    from utils_ai_assistant import ask_chatgpt, process_voice_question, analyze_images_with_gpt4_vision, analyze_food_calories
    from texts import AI_ASSISTANT_CALORIE_RESULT

    db = AsyncDatabase()
    await asyncio.sleep(random.uniform(2, 7))

    while True:
        try:
            jobs = await db.get_pending_ai_assistant_jobs(limit=1)
            for job in jobs:
                try:
                    answer = None
                    error = None
                    mode = job["mode"]

                    if mode == "text":
                        answer, error = await ask_chatgpt(job["question"])
                    elif mode == "voice":
                        if not job.get("transcribed_text"):
                            transcribed, answer, error = await process_voice_question(job["voice_path"])
                            if transcribed:
                                await db.update_ai_assistant_job_transcription(job["id"], transcribed)
                        else:
                            answer, error = await ask_chatgpt(job["transcribed_text"])
                    elif mode == "vision":
                        if job.get("image_paths"):
                            img_list = [p.strip() for p in job["image_paths"].split(",") if p.strip()]
                            answer, error = await analyze_images_with_gpt4_vision(img_list, job["question"])
                        else:
                            error = "No images"
                    elif mode == "calorie":
                        if job.get("image_paths"):
                            nutrition_data, error = await analyze_food_calories(job["image_paths"].strip())
                            if nutrition_data and not error:
                                answer = AI_ASSISTANT_CALORIE_RESULT.format(
                                    dish_name=nutrition_data.get("dish_name", "Неизвестное блюдо"),
                                    portion=nutrition_data.get("portion_size", "Не определено"),
                                    calories=nutrition_data.get("calories", 0),
                                    protein=nutrition_data.get("protein", 0),
                                    fat=nutrition_data.get("fat", 0),
                                    carbs=nutrition_data.get("carbohydrates", 0),
                                    fiber=nutrition_data.get("fiber", 0),
                                    sugar=nutrition_data.get("sugar", 0),
                                    additional_info=nutrition_data.get("additional_info", ""),
                                )

                    await db.update_ai_assistant_job_status(job["id"], "completed")

                    if error or not answer:
                        await bot.send_message(
                            chat_id=job["user_id"],
                            text=f"⚠️ Ошибка AI: {error or 'Пустой ответ'}",
                        )
                    else:
                        await bot.send_message(
                            chat_id=job["user_id"],
                            text=f"🤖 *AI ответ:*\n\n{answer}",
                            attachments=get_ai_ask_again_kb(),
                            format="markdown",
                        )
                except Exception as e:
                    await db.update_ai_assistant_job_status(job["id"], "failed")
                    logger.error(f"AI assistant job {job['id']} failed: {e}")
        except Exception as e:
            logger.error(f"AI assistant queue error: {e}")
        await asyncio.sleep(random.uniform(5, 10))


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatcher event handlers
# ═══════════════════════════════════════════════════════════════════════════════

@dp.bot_started()
async def on_bot_started(event: BotStarted):
    await start_h.on_bot_started(event, bot)


@dp.message_created(F.message.body.text)
async def on_message(event: MessageCreated):
    """Route all text messages."""
    user_id = event.message.sender.user_id
    chat_id = event.message.recipient.chat_id
    username = event.message.sender.name or str(user_id)
    text = (event.message.body.text or "").strip()
    state = state_mgr.get(user_id)

    # ── Commands ──────────────────────────────────────────────────────────────
    if text.lower() in ("/start", "start"):
        await start_h.cmd_start(event, bot)
        return

    if text.lower() == "/info":
        await start_h.cmd_info(chat_id, bot)
        return

    if text.lower() in ("/cancel", "отмена", "❌ отмена"):
        await start_h.cmd_cancel(chat_id, user_id, bot)
        return

    if text.lower() == "/admin" and admin_h.is_admin(user_id):
        await admin_h.cmd_admin(chat_id, user_id, bot)
        return

    if text.lower() == "/admin_promo" and admin_h.is_admin(user_id):
        await admin_h.cmd_admin_promo(chat_id, user_id, bot)
        return

    if text.lower().startswith("/admin_create_promo ") and admin_h.is_admin(user_id):
        parts = text.split()
        if len(parts) == 3:
            await admin_h.handle_create_promo(chat_id, user_id, parts[1], parts[2], bot)
        return

    if text.lower().startswith("/admin_delete_promo ") and admin_h.is_admin(user_id):
        parts = text.split()
        if len(parts) == 2:
            await admin_h.handle_delete_promo(chat_id, user_id, parts[1], bot)
        return

    if text.lower().startswith("/admin_balance ") and admin_h.is_admin(user_id):
        parts = text.split()
        if len(parts) == 3:
            await admin_h.handle_add_balance(chat_id, user_id, parts[1], parts[2], bot)
        return

    if text.lower().startswith("/admin_broadcast ") and admin_h.is_admin(user_id):
        broadcast_text = text[len("/admin_broadcast "):].strip()
        if broadcast_text:
            await admin_h.handle_broadcast(chat_id, user_id, broadcast_text, bot)
        return

    if text.lower() == "/admin_stats" and admin_h.is_admin(user_id):
        await admin_h.cmd_stats(chat_id, user_id, bot)
        return

    # ── State-based routing ───────────────────────────────────────────────────
    if state == user_h.STATES["waiting_for_promo"]:
        await user_h.process_promo_code(chat_id, user_id, text, bot)
        return

    if state == gen_h.STATES["seedream_prompt"]:
        await gen_h.process_seedream_prompt(chat_id, user_id, username, text, bot)
        return

    if state == gen_h.STATES["gpt_prompt"]:
        await gen_h.process_gpt_image_prompt(chat_id, user_id, username, text, bot)
        return

    if state == ai_h.STATES["text"]:
        await ai_h.process_text_question(chat_id, user_id, username, text, bot)
        return

    if state == ai_h.STATES["vision_prompt"]:
        await ai_h.process_vision_prompt(chat_id, user_id, username, text, bot)
        return

    if state == video_h.STATES["kling_prompt"]:
        await video_h.handle_kling_prompt(chat_id, user_id, username, text, bot)
        return

    if state == video_h.STATES["runway_prompt"]:
        await video_h.handle_runway_prompt(chat_id, user_id, username, text, bot)
        return

    if state == video_h.STATES["veo3_prompt"]:
        await video_h.handle_veo3_prompt(chat_id, user_id, username, text, bot)
        return

    if state == flux_h.STATES["prompt"]:
        await flux_h.handle_flux_prompt(chat_id, user_id, username, text, bot)
        return

    if state == nano_h.STATES["prompt"]:
        await nano_h.handle_nano_prompt(chat_id, user_id, username, text, bot)
        return

    if state == suno_h.STATES["prompt"]:
        await suno_h.handle_suno_prompt(chat_id, user_id, username, text, bot)
        return

    if state == avatar_h.STATES["trigger"]:
        await avatar_h.handle_trigger_phrase(chat_id, user_id, username, text, bot)
        return

    # ── Unknown message → show main menu ──────────────────────────────────────
    await bot.send_message(
        chat_id=chat_id,
        text="Выберите раздел в меню:",
        attachments=get_main_menu_kb(),
    )


@dp.message_created()
async def on_media_message(event: MessageCreated):
    """Handle incoming media (photos, voice, audio) based on current state."""
    user_id = event.message.sender.user_id
    chat_id = event.message.recipient.chat_id
    username = event.message.sender.name or str(user_id)
    state = state_mgr.get(user_id)

    # Skip text messages — handled by on_message above
    if event.message.body.text:
        return

    attachments = event.message.body.attachments or []

    # Find first image or audio
    photo_url = None
    audio_url = None
    for att in attachments:
        att_type = getattr(att, "type", None)
        if att_type == "image" and not photo_url:
            payload = getattr(att, "payload", None)
            if payload:
                photo_url = getattr(payload, "url", None)
        elif att_type in ("audio", "voice") and not audio_url:
            payload = getattr(att, "payload", None)
            if payload:
                audio_url = getattr(payload, "url", None)

    # Voice message routing
    if audio_url and state == ai_h.STATES["voice"]:
        await ai_h.process_voice_message(chat_id, user_id, username, audio_url, bot)
        return

    # Photo routing
    if photo_url:
        if state == video_h.STATES["kling_photo"]:
            await video_h.handle_kling_photo(chat_id, user_id, photo_url, bot)
        elif state == video_h.STATES["runway_photo"]:
            await video_h.handle_runway_photo(chat_id, user_id, photo_url, bot)
        elif state == ps_h.STATES["collecting"]:
            await ps_h.handle_session_photo(chat_id, user_id, photo_url, bot)
        elif state == flux_h.STATES["photos"]:
            await flux_h.handle_flux_photo(chat_id, user_id, photo_url, bot)
        elif state == nano_h.STATES["photo"]:
            await nano_h.handle_nano_photo(chat_id, user_id, photo_url, bot)
        elif state == avatar_h.STATES["photos"]:
            await avatar_h.handle_avatar_photo(chat_id, user_id, photo_url, bot)
        elif state == ai_h.STATES["vision_photos"]:
            await ai_h.process_vision_photo(chat_id, user_id, photo_url, bot)
        elif state == ai_h.STATES["calorie"]:
            await ai_h.process_calorie_photo(chat_id, user_id, username, photo_url, bot)
        elif state == i2p_h.STATES["photo"]:
            await i2p_h.handle_img2prompt_photo(chat_id, user_id, username, photo_url, bot)
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="Выберите раздел в меню, куда отправить это изображение:",
                attachments=get_main_menu_kb(),
            )
        return

    # Nothing matched
    await bot.send_message(
        chat_id=chat_id,
        text="Выберите раздел:",
        attachments=get_main_menu_kb(),
    )


@dp.message_callback()
async def on_callback(callback: MessageCallback):
    """Route all inline button presses."""
    user_id = callback.user.user_id
    chat_id = callback.message.recipient.chat_id
    username = callback.user.name or str(user_id)
    payload = callback.payload or ""

    # Navigation
    if payload.startswith("menu:") or payload == "cancel":
        await start_h.handle_nav_callback(payload, chat_id, user_id, bot)
        return

    # Profile
    if payload == "menu:profile":
        await user_h.show_profile(chat_id, user_id, bot)
        return

    # Payment
    if payload == "buy_credits":
        await pay_h.show_packages(chat_id, user_id, bot)
        return

    if payload.startswith("tchpay:pkg:"):
        pkg_id = payload.split(":", 2)[2]
        await pay_h.handle_package_selected(chat_id, user_id, pkg_id, bot)
        return

    if payload.startswith("tchpay:check:"):
        order_id = payload.split(":", 2)[2]
        await pay_h.handle_check_payment(chat_id, user_id, order_id, bot)
        return

    # Promo
    if payload == "enter_promo":
        await user_h.handle_enter_promo(chat_id, user_id, bot)
        return

    # Photo menu
    if payload == "photo:seedream":
        await gen_h.show_seedream_start(chat_id, user_id, bot)
        return

    if payload == "photo:gpt":
        await gen_h.show_gpt_image_start(chat_id, user_id, bot)
        return

    if payload == "photo:session":
        await ps_h.show_photosession_start(chat_id, user_id, bot)
        return

    if payload == "photo:flux":
        await flux_h.show_flux_start(chat_id, user_id, bot)
        return

    if payload == "photo:nano":
        await nano_h.show_nano_start(chat_id, user_id, bot)
        return

    if payload == "photo:img2prompt":
        await i2p_h.show_img2prompt_start(chat_id, user_id, bot)
        return

    # Video menu
    if payload == "video:kling":
        await video_h.show_kling_start(chat_id, user_id, bot)
        return

    if payload == "video:runway":
        await video_h.show_runway_start(chat_id, user_id, bot)
        return

    if payload == "video:veo3":
        await video_h.show_veo3_start(chat_id, user_id, bot)
        return

    # Video - duration / aspect
    if payload.startswith("kling:"):
        dur = int(payload.split(":")[1])
        await video_h.handle_kling_duration(chat_id, user_id, username, dur, bot)
        return

    if payload.startswith("runway:aspect:"):
        aspect = ":".join(payload.split(":")[2:])
        await video_h.handle_runway_aspect(chat_id, user_id, aspect, bot)
        return

    # AI assistant
    if payload == "ai:text":
        await ai_h.handle_ai_mode(chat_id, user_id, "text", bot)
        return

    if payload == "ai:voice":
        await ai_h.handle_ai_mode(chat_id, user_id, "voice", bot)
        return

    if payload == "ai:vision":
        await ai_h.handle_ai_mode(chat_id, user_id, "vision", bot)
        return

    if payload == "ai:calorie":
        await ai_h.handle_ai_mode(chat_id, user_id, "calorie", bot)
        return

    if payload == "ai:vision_analyze":
        await ai_h.handle_vision_analyze_callback(chat_id, user_id, bot)
        return

    # Photo session
    if payload == "session:choose_style":
        await ps_h.handle_choose_style_callback(chat_id, user_id, bot)
        return

    if payload.startswith("pstyle:"):
        idx = int(payload.split(":")[1])
        await ps_h.handle_style_selected(chat_id, user_id, username, idx, bot)
        return

    # Flux Kontext count
    if payload.startswith("flux:count:"):
        count = int(payload.split(":")[2])
        await flux_h.handle_flux_count(chat_id, user_id, count, bot)
        return

    # Avatar
    if payload == "avatar:create":
        await avatar_h.show_avatar_start(chat_id, user_id, bot)
        return

    if payload == "avatar:next":
        await avatar_h.handle_avatar_next_callback(chat_id, user_id, bot)
        return

    # Suno
    if payload == "menu:suno":
        await suno_h.show_suno_menu(chat_id, user_id, bot)
        return

    # Regen
    if payload.startswith("regen:seedream"):
        await gen_h.show_seedream_start(chat_id, user_id, bot)
        return

    if payload.startswith("regen:video"):
        await video_h.show_kling_start(chat_id, user_id, bot)
        return

    # Unknown callback
    logger.warning(f"Unknown callback payload: {payload!r} from user {user_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    loop = asyncio.get_event_loop()
    loop.set_default_executor(thread_pool)

    # Start all background workers
    workers = [
        process_seedream_job_queue(),
        process_openai_image_job_queue(),
        process_flux_kontext_job_queue(),
        process_nano_banana_job_queue(),
        process_photosession_queue(),
        process_avatar_training_queue(),
        process_suno_job_queue(),
        process_ai_assistant_job_queue(),
        process_ai_assistant_job_queue(),  # 2nd worker for throughput
        process_video_job_queue(),
        process_runway_video_job_queue(),
        process_veo3_video_job_queue(),
    ]

    for i, coro in enumerate(workers):
        asyncio.create_task(coro)
        await asyncio.sleep(0.3)  # stagger starts

    logger.info("Starting MAX bot polling...")
    try:
        await dp.start_polling(bot)
    finally:
        thread_pool.shutdown(wait=False)
        logger.info("MAX bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("MAX bot stopped")
