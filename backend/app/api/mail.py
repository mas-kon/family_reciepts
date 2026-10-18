import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import email_inbox
from app.api.deps import current_viewer
from app.clock import now_local
from app.config import get_settings
from app.i18n import t

router = APIRouter(prefix="/api/mail", tags=["mail"], dependencies=[Depends(current_viewer)])


class MailStatus(BaseModel):
    enabled: bool
    address: str | None
    host: str | None
    poll_minutes: int
    checked_at: datetime | None
    # None: not checked since the start
    ok: bool | None
    error: str | None
    hint: str | None
    # receipts booked from mail since the start
    received: int


def _out() -> MailStatus:
    s = get_settings()
    st = email_inbox.status
    return MailStatus(
        enabled=bool(s.imap_host),
        address=s.imap_user or None,
        host=s.imap_host or None,
        poll_minutes=s.imap_poll_minutes,
        checked_at=st.checked_at,
        ok=st.ok,
        error=st.error,
        hint=t("api.mail_hint_auth") if st.error and ("AUTH" in st.error.upper() or "CREDENTIAL" in st.error.upper()) else None,
        received=st.received,
    )


@router.get("/status", response_model=MailStatus)
async def mail_status():
    """Whether the mailbox is connected and what the last look into it found."""
    return _out()


@router.post("/check", response_model=MailStatus)
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
