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
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from html.parser import HTMLParser

from sqlalchemy import select

from app.config import get_settings
from app.db.models import User
from app.db.session import session_factory
from app.receipts.service import ProcessResult, ReceiptService

log = logging.getLogger(__name__)

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


def fetch_unseen() -> list[bytes]:
    """Unread messages from the configured folder; they are marked as read by fetching."""
    s = get_settings()
    box = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
    try:
        box.login(s.imap_user, s.imap_password)
        box.select(s.imap_folder)
        _, data = box.search(None, "UNSEEN")
        out = []
        for num in (data[0] or b"").split()[:20]:
            _, msg_data = box.fetch(num, "(RFC822)")
            for item in msg_data:
                if isinstance(item, tuple):
                    out.append(item[1])
        return out
    finally:
        try:
            box.logout()
        except Exception:
            pass


async def owner_by_email(session, address: str) -> User | None:
    for u in await session.scalars(select(User).where(User.emails.is_not(None))):
        if address in {e.strip().lower() for e in (u.emails or "").split(",") if e.strip()}:
            return u
    return None


async def process_mail(svc: ReceiptService, mail: ParsedMail) -> ProcessResult:
    owner = await owner_by_email(svc.session, mail.sender)
    ext = f"email:{mail.message_id}"[:300]
    for ctype, data in mail.attachments:
        if ctype == "application/pdf":
            return await svc.process_pdf(data, owner, source="email", external_id=ext, note=mail.subject or None)
        return await svc.process_photo(data, owner, source="email", external_id=ext, note=mail.subject or None)
    return await svc.process_text_receipt(mail.text, owner, source="email", external_id=ext)


async def poll_inbox(bot=None) -> int:
    """One IMAP round: books receipts from unread mail and reports them to the group."""
    s = get_settings()
    if not s.imap_host:
        return 0
    try:
        raws = await asyncio.to_thread(fetch_unseen)
    except Exception as e:
        log.warning("IMAP poll failed: %s", e)
        return 0
    booked = 0
    for raw in raws:
        mail = parse_mail(raw)
        async with session_factory()() as session:
            svc = ReceiptService(session)
            try:
                res = await process_mail(svc, mail)
            except Exception:
                log.exception("failed to process e-mail %s", mail.message_id)
                continue
            if not res.receipt:
                continue
            booked += 1
            chat = s.notify_chat_id
            if bot and chat:
                from app.bot.handlers import format_receipt, receipt_keyboard

                text = "📧 Чек из почты\n" + await format_receipt(session, res.receipt)
                msg = await bot.send_message(chat, text, reply_markup=receipt_keyboard(res.receipt.id))
                res.receipt.chat_id, res.receipt.bot_message_id = chat, msg.message_id
                await session.commit()
    return booked
