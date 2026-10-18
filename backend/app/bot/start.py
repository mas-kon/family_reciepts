"""/start, /help, /chatid."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.i18n import t

router = Router()


@router.message(Command("start", "help"))
async def on_help(message: Message):
    await message.reply(t("bot.help"))


@router.message(Command("chatid"))
async def on_chatid(message: Message):
    await message.reply(t("bot.chat_id", id=message.chat.id))
