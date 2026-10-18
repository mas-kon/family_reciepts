"""Entry point: runs migrations, then the web server, the Telegram bot and the scheduler
in one asyncio loop.

    uv run python -m app.main
"""

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.db.migrate import upgrade
from app.db.seed import fail_interrupted, seed_categories
from app.db.session import session_factory
from app.i18n import load_language
from app.scheduler import create_scheduler
from app.web import create_app

log = logging.getLogger("check_bot")


async def run() -> None:
    s = get_settings()
    s.receipts_dir.mkdir(parents=True, exist_ok=True)

    async with session_factory()() as session:
        await load_language(session)
        await seed_categories(session)
        if n := await fail_interrupted(session):
            log.warning("%d records were interrupted by a restart: marked failed", n)

    app = create_app()
    bot: Bot | None = None
    dp: Dispatcher | None = None
    if s.bot_token:
        from app.bot.handlers import router

        bot = Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        me = await bot.get_me()
        app.state.bot = bot
        app.state.bot_username = me.username
        dp = Dispatcher()
        dp.include_router(router)
        log.info("bot @%s started", me.username)
    else:
        log.warning("BOT_TOKEN is empty: running web UI only")

    scheduler = create_scheduler(bot)
    scheduler.start()

    server = uvicorn.Server(uvicorn.Config(app, host=s.web_host, port=s.web_port, log_level="info", proxy_headers=True))
    web = asyncio.create_task(server.serve(), name="web")
    polling = None
    if dp and bot:
        polling = asyncio.create_task(
            dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types()),
            name="bot",
        )
    app.state.polling_task = polling
    try:
        # whichever stops first ends the process: a dead bot must not hide behind a live web app
        done, _ = await asyncio.wait({t for t in (web, polling) if t}, return_when=asyncio.FIRST_COMPLETED)
        if polling in done:
            err = polling.exception() if not polling.cancelled() else None
            log.error("the bot stopped (%r): exiting so the service restarts", err)
            raise SystemExit(1)
    finally:
        scheduler.shutdown(wait=False)
        server.should_exit = True
        if not web.done():
            await asyncio.wait({web}, timeout=10)  # let uvicorn finish in-flight requests
        if dp and polling and not polling.done():
            try:
                await dp.stop_polling()
            except RuntimeError:
                pass  # polling was not running
        for t in (web, polling):
            if t and not t.done():
                t.cancel()
        if bot:
            await bot.session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    upgrade()
    asyncio.run(run())


if __name__ == "__main__":
    main()
