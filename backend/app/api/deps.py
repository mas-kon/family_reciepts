from dataclasses import dataclass

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings
from app.i18n import t

COOKIE = "cb_session"
MAX_AGE = 60 * 60 * 24 * 30


@dataclass
class Viewer:
    user_id: int | None
    name: str
    method: str  # telegram | password | disabled


def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="check-bot-auth")


def make_cookie(viewer: Viewer) -> str:
    return serializer().dumps({"u": viewer.user_id, "n": viewer.name, "m": viewer.method})


async def current_viewer(request: Request) -> Viewer:
    if get_settings().auth_disabled:
        return Viewer(user_id=None, name="dev", method="disabled")
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, t("api.login_required"))
    try:
        data = serializer().loads(token, max_age=MAX_AGE)
    except BadSignature:
        raise HTTPException(401, t("api.session_invalid"))
    return Viewer(user_id=data.get("u"), name=data.get("n", ""), method=data.get("m", ""))
