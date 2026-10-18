import asyncio

from fastapi import APIRouter, Depends

from app import email_inbox
from app.api.deps import current_viewer
from app.clock import now_local
from app.config import get_settings

router = APIRouter(prefix="/api/mail", tags=["mail"], dependencies=[Depends(current_viewer)])

HINT_AUTH = "Проверьте IMAP_USER и IMAP_PASSWORD в .env (для Gmail нужен пароль приложения, не обычный пароль)."


def _out() -> dict:
    s = get_settings()
    st = email_inbox.status
    return {
        "enabled": bool(s.imap_host),
        "address": s.imap_user or None,
        "host": s.imap_host or None,
        "poll_minutes": s.imap_poll_minutes,
        "checked_at": st.checked_at,
        "ok": st.ok,
        "error": st.error,
        "hint": HINT_AUTH if st.error and ("AUTH" in st.error.upper() or "CREDENTIAL" in st.error.upper()) else None,
        "received": st.received,
    }


@router.get("/status")
async def mail_status():
    """Whether the mailbox is connected and what the last look into it found."""
    return _out()


@router.post("/check")
async def mail_check():
    """Tries to log in right now instead of waiting for the next poll."""
    if get_settings().imap_host:
        st = email_inbox.status
        try:
            await asyncio.to_thread(email_inbox.check_connection)
            st.checked_at, st.ok, st.error = now_local(), True, None
        except Exception as e:
            st.checked_at, st.ok, st.error = now_local(), False, email_inbox._describe(e)
    return _out()
