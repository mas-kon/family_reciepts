from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.api import ai, auth, receipts, settings, stats
from app.config import PROJECT_ROOT

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="Check Bot", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.bot = None
    app.state.bot_username = None

    for r in (auth.router, receipts.router, stats.router, settings.router, ai.router):
        app.include_router(r)

    @app.get("/api/health")
    async def health():
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
