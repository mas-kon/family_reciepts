"""The bot's root router: access check first, then the handlers in the order they are tried
(the first one whose filter matches wins, so a reply to a record is an edit before it can be
taken for a bank text)."""

from aiogram import Router

from app.bot import audio, banking, photos, records, start, statements
from app.bot.access import AllowedChatsOnly

router = Router()
router.message.outer_middleware(AllowedChatsOnly())
router.callback_query.outer_middleware(AllowedChatsOnly())
router.include_routers(start.router, photos.router, statements.router, records.router, audio.router, banking.router)
