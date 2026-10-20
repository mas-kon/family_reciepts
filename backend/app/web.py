from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import text

from app.api import ai, auth, budgets, categories, llm, mail, receipts, recurring, settings, stats, users
from app.config import PROJECT_ROOT
from app.db.session import session_factory
from app.i18n import t

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
THEME_COLOR = "#863bff"


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
        settings.router,
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

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        """Web app manifest: the name follows the family's language; Android offers the app in the
        share sheet for pictures and PDFs (the service worker in /sw.js receives them)."""
        title = t("app.title")
        icons = [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]
        return JSONResponse(
            {
                "name": title,
                "short_name": title,
                "start_url": "/",
                "scope": "/",
                "display": "standalone",
                "theme_color": THEME_COLOR,
                "background_color": THEME_COLOR,
                "icons": icons,
                "share_target": {
                    "action": "/share-target",
                    "method": "POST",
                    "enctype": "multipart/form-data",
                    "params": {"files": [{"name": "receipt", "accept": ["image/*", "application/pdf"]}]},
                },
            },
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/share-target", include_in_schema=False)
    async def share_target():
        """The service worker normally handles this request; this is for a page it does not control yet."""
        return RedirectResponse("/receipts", status_code=303)

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
