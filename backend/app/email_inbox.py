"""Receipts by e-mail: forward electronic receipts and order confirmations to a mailbox.

The scheduler polls unread messages over IMAP. Image and PDF attachments go through the photo
pipeline, otherwise the message text is read. The sender address picks the family member
(Settings → Семья → e-mail). Every message is marked as read, so it is processed once.
"""

import asyncio
import email
import hashlib
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from html.parser import HTMLParser

from app.bot.ui import format_receipt, receipt_keyboard
from app.clock import now_local
from app.config import get_settings
from app.db.session import session_factory
from app.family import owner_by_email
from app.receipts.service import ProcessResult, ReceiptService

log = logging.getLogger(__name__)

@dataclass
class MailStatus:
    """The result of the last look into the mailbox, for the web app. Kept in memory."""

    checked_at: datetime | None = None
    ok: bool | None = None  # None: not checked yet
    error: str | None = None
    received: int = 0  # receipts booked since the start


status = MailStatus()


def _describe(e: Exception) -> str:
    text = str(e).strip() or type(e).__name__
    if isinstance(e, imaplib.IMAP4.error | OSError) or "AUTH" in text.upper():
        return text
    return f"{type(e).__name__}: {text}"


def check_connection() -> None:
    """Logs in and opens the folder; raises when the mailbox cannot be read."""
    _imap(lambda box: box.noop())


MAX_ATTEMPTS = 3
_failures: dict[str, int] = {}  # Message-ID -> failed attempts
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self._skip += 1
        elif tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


@dataclass
class ParsedMail:
    message_id: str
    sender: str
    subject: str
    text: str
    attachments: list[tuple[str, bytes]] = field(default_factory=list)  # (content type, data)


def parse_mail(raw: bytes) -> ParsedMail:
    msg: Message = email.message_from_bytes(raw)
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    sender = parseaddr(msg.get("From", ""))[1].lower()
    plain, html, attachments = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        is_pdf = ctype == "application/pdf" or (part.get_filename() or "").lower().endswith(".pdf")
        if ctype in IMAGE_TYPES or is_pdf:
            if is_pdf or len(payload) > 20_000:  # skip logos and tracking pixels in HTML mail
                attachments.append(("application/pdf" if is_pdf else ctype, payload))
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if ctype == "text/plain":
            plain.append(text)
        elif ctype == "text/html":
            html.append(html_to_text(text))
    body = "\n".join(plain) if any(p.strip() for p in plain) else "\n".join(html)
    return ParsedMail(
        message_id=(msg.get("Message-ID") or "").strip() or "sha1:" + hashlib.sha1(raw).hexdigest(),
        sender=sender,
        subject=subject,
        text=f"Тема: {subject}\n\n{body}".strip(),
        attachments=attachments,
    )


def _imap(action):
    s = get_settings()
    box = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
    try:
        box.login(s.imap_user, s.imap_password)
        box.select(s.imap_folder)
        return action(box)
    finally:
        try:
            box.logout()
        except Exception as e:
            log.debug("IMAP logout failed: %s", e)


def fetch_unseen() -> list[tuple[bytes, bytes]]:
    """(IMAP number, raw message) of unread mail. PEEK leaves it unread: it is marked as read
    by mark_seen only after it has been processed, so a failure does not lose the message."""

    def action(box):
        _, data = box.search(None, "UNSEEN")
        out = []
        for num in (data[0] or b"").split()[:20]:
            _, msg_data = box.fetch(num, "(BODY.PEEK[])")
            for item in msg_data:
                if isinstance(item, tuple):
                    out.append((num, item[1]))
        return out

    return _imap(action)


def mark_seen(nums: list[bytes]) -> None:
    if nums:
        _imap(lambda box: [box.store(n, "+FLAGS", "\\Seen") for n in nums])


async def process_mail(svc: ReceiptService, mail: ParsedMail) -> list[ProcessResult]:
    """One result per attachment (or one for a mail without attachments)."""
    owner = await owner_by_email(svc.session, mail.sender)
    base = f"email:{mail.message_id}"[:290]
    note = mail.subject or None
    results = []
    for i, (ctype, data) in enumerate(mail.attachments):
        ext = base if i == 0 else f"{base}#{i}"
        if ctype == "application/pdf":
            results.append(await svc.process_pdf(data, owner, source="email", external_id=ext, note=note))
        else:
            results.append(await svc.process_photo(data, owner, source="email", external_id=ext, note=note))
    if not results:
        results.append(await svc.process_text_receipt(mail.text, owner, source="email", external_id=base))
    return results


async def poll_inbox(bot=None) -> int:
    """One IMAP round: books receipts from unread mail and reports them to the group."""
    s = get_settings()
    if not s.imap_host:
        return 0
    try:
        raws = await asyncio.to_thread(fetch_unseen)
    except Exception as e:
        log.warning("IMAP poll failed: %s", e)
        status.checked_at, status.ok, status.error = now_local(), False, _describe(e)
        return 0
    status.checked_at, status.ok, status.error = now_local(), True, None
    booked = 0
    done: list[bytes] = []
    for num, raw in raws:
        mail = parse_mail(raw)
        async with session_factory()() as session:
            svc = ReceiptService(session)
            try:
                results = await process_mail(svc, mail)
            except Exception:
                _failures[mail.message_id] = _failures.get(mail.message_id, 0) + 1
                log.exception("failed to process e-mail %s (attempt %d)", mail.message_id, _failures[mail.message_id])
                if _failures[mail.message_id] >= MAX_ATTEMPTS:
                    done.append(num)  # give up on a message that never works
                continue
            done.append(num)
            for res in results:
                if not res.receipt:
                    continue
                booked += 1
                status.received += 1
                chat = s.notify_chat_id
                if bot and chat:
                    text = "📧 Чек из почты\n" + await format_receipt(session, res.receipt)
                    msg = await bot.send_message(chat, text, reply_markup=receipt_keyboard(res.receipt.id))
                    res.receipt.chat_id, res.receipt.bot_message_id = chat, msg.message_id
                    await session.commit()
    try:
        await asyncio.to_thread(mark_seen, done)
    except Exception as e:
        log.warning("could not mark e-mails as read: %s", e)
    return booked
