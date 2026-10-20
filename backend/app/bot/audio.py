"""Voice messages."""

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.bot.common import download, get_sender, react, reply_with_record
from app.config import get_settings
from app.db.session import session_factory
from app.i18n import t
from app.llm.slots import llm_slots
from app.receipts.service import ReceiptService
from app.voice import MAX_VOICE_SECONDS, handle_voice, to_wav

log = logging.getLogger(__name__)
router = Router()


@router.message(F.voice | F.audio)
async def on_voice(message: Message, bot: Bot):
    if not get_settings().audio_models:
        return
    media = message.voice or message.audio
    if media is None:
        return
    if media.duration and media.duration > MAX_VOICE_SECONDS:
        return  # a long voice message is a conversation, not an expense
    try:
        data = await download(bot, media.file_id)
        wav = await asyncio.to_thread(to_wav, data)
        async with llm_slots, session_factory()() as session:
            svc = ReceiptService(session)
            sender = await get_sender(svc, message)
            res = await handle_voice(svc, wav, sender, chat_id=message.chat.id, message_id=message.message_id)
            if res.receipt is None:
                if res.unknown_who:
                    await message.reply(t("bot.voice_unknown", problem=html.escape(res.problem or ""), heard=html.escape(res.transcript)))
                else:
                    # most likely an ordinary voice message without an expense: stay quiet
                    await react(message, "🤔")
                return
            await reply_with_record(message, bot, session, res.receipt, sender)
    except Exception:
        log.exception("failed to process voice message")
        await react(message, "🤷")
