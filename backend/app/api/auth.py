import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import COOKIE, MAX_AGE, Viewer, current_viewer, make_cookie
from app.config import get_settings
from app.db.models import User
from app.db.session import get_session
from app.i18n import t

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


class TelegramAuth(BaseModel):
    # unknown fields are kept: they are part of the signed data
    model_config = ConfigDict(extra="allow")

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class PasswordAuth(BaseModel):
    password: str


def verify_telegram(data: TelegramAuth, bot_token: str) -> bool:
    """https://core.telegram.org/widgets/login#checking-authorization"""
    fields = data.model_dump(exclude={"hash"}, exclude_none=True)
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    fresh = time.time() - data.auth_date < 86400
    return fresh and hmac.compare_digest(expected, data.hash)


def _set_cookie(response: Response, viewer: Viewer, request: Request):
    response.set_cookie(
        COOKIE,
        make_cookie(viewer),
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


@router.get("/config")
async def auth_config(request: Request):
    s = get_settings()
    return {
        "telegram_bot": getattr(request.app.state, "bot_username", None),
        "password_enabled": bool(s.web_password),
        "auth_disabled": s.auth_disabled,
    }


async def _telegram_viewer(data: TelegramAuth, request: Request, session: AsyncSession) -> Viewer:
    """Checks the widget signature and group membership; raises HTTPException(403) otherwise."""
    s = get_settings()
    if not s.bot_token or not verify_telegram(data, s.bot_token):
        raise HTTPException(403, t("api.tg_signature"))

    bot = getattr(request.app.state, "bot", None)
    allowed = False
    if bot and s.allowed_chats:
        for chat_id in s.allowed_chats:
            try:
                member = await bot.get_chat_member(chat_id, data.id)
                if member.status in MEMBER_STATUSES:
                    allowed = True
                    break
            except Exception as e:
                log.warning("get_chat_member(%s, %s) failed: %s", chat_id, data.id, e)
    else:
        allowed = bool(await session.scalar(select(User.id).where(User.telegram_id == data.id)))
    if not allowed:
        raise HTTPException(403, t("api.not_member"))

    name = " ".join(x for x in (data.first_name, data.last_name) if x) or data.username or str(data.id)
    user = await session.scalar(select(User).where(User.telegram_id == data.id))
    if not user:
        user = User(telegram_id=data.id, name=name, username=data.username)
        session.add(user)
        await session.commit()
    return Viewer(user_id=user.id, name=user.name, method="telegram")


@router.post("/telegram")
async def login_telegram(
    data: TelegramAuth,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    viewer = await _telegram_viewer(data, request, session)
    _set_cookie(response, viewer, request)
    return {"user_id": viewer.user_id, "name": viewer.name}


@router.get("/telegram/callback")
async def login_telegram_redirect(request: Request, session: AsyncSession = Depends(get_session)):
    """Target of the widget's data-auth-url: Telegram redirects here with the signed fields."""
    try:
        data = TelegramAuth.model_validate(dict(request.query_params))
        viewer = await _telegram_viewer(data, request, session)
    except ValidationError:
        return RedirectResponse("/?" + urlencode({"login_error": t("api.tg_incomplete")}), 303)
    except HTTPException as e:
        return RedirectResponse("/?" + urlencode({"login_error": e.detail}), 303)
    response = RedirectResponse("/", 303)
    _set_cookie(response, viewer, request)
    return response


# failed password attempts per client address: {ip: [timestamps]}
_failures: dict[str, list[float]] = {}
MAX_FAILURES = 5
FAILURE_WINDOW = 60.0


def _throttled(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW]
    _failures[ip] = recent
    if not recent:
        _failures.pop(ip, None)
    return len(recent) >= MAX_FAILURES


@router.post("/password")
async def login_password(data: PasswordAuth, request: Request, response: Response):
    s = get_settings()
    ip = request.client.host if request.client else "?"
    if _throttled(ip):
        raise HTTPException(429, t("api.too_many"))
    # bytes: compare_digest raises TypeError on non-ASCII str
    if not s.web_password or not secrets.compare_digest(data.password.encode(), s.web_password.encode()):
        _failures.setdefault(ip, []).append(time.monotonic())
        raise HTTPException(403, t("api.bad_password"))
    _failures.pop(ip, None)
    viewer = Viewer(user_id=None, name=t("api.family_viewer"), method="password")
    _set_cookie(response, viewer, request)
    return {"user_id": None, "name": viewer.name}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(viewer: Viewer = Depends(current_viewer)):
    return {"user_id": viewer.user_id, "name": viewer.name, "method": viewer.method}
