"""Which chats the bot works in."""

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from app.config import get_settings


def allowed(chat_id: int) -> bool:
    """Only the configured family chats. An empty list is open to every chat in dev mode
    (AUTH_DISABLED) only; otherwise the bot answers just /chatid until it is filled in."""
    s = get_settings()
    return chat_id in s.allowed_chats if s.allowed_chats else s.auth_disabled


class AllowedChatsOnly(BaseMiddleware):
    """Drops updates from chats that are not the family's, before any handler runs. The
    commands that help to set the bot up work everywhere."""

    OPEN_COMMANDS = ("/start", "/help", "/chatid")

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message else None
        elif isinstance(event, Message):
            chat = event.chat
            if (event.text or "").startswith(self.OPEN_COMMANDS):
                return await handler(event, data)
        else:
            chat = None
        if chat is not None and allowed(chat.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer()
        return None
