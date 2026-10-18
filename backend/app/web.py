from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.api import ai, auth, budgets, categories, llm, mail, receipts, recurring, stats, users
from app.config import PROJECT_ROOT
from app.db.session import session_factory

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Check Bot", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.bot = None
    app.state.bot_username = None

    for r in (
        auth.router,
        receipts.router,
        stats.router,
        ai.router,
        users.router,
        categories.router,
        budgets.router,
        recurring.router,
        llm.router,
        mail.router,
    ):
        app.include_router(r)

    @app.get("/api/health")
    async def health():
        """Database reachable and, when the bot is configured, its polling task alive."""
        polling = getattr(app.state, "polling_task", None)
        if polling is not None and polling.done():
            raise HTTPException(503, "bot is not running")
        try:
            async with session_factory()() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "database is not reachable")
        return {"ok": True}

    # Serve the built React app; unknown paths fall back to index.html (client-side routing).
    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        if not FRONTEND_DIST.exists():
            return {"detail": "Frontend is not built. Run: cd frontend && npm run build"}
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(Path(FRONTEND_DIST / "index.html"))

    return app
