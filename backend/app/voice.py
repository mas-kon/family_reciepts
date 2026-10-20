"""Voice messages: "двенадцать евро такси" -> an expense record (source "voice")."""

import io
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select

from app.constants import no_description
from app.db.models import Receipt, User
from app.i18n import t
from app.llm.prompt import VOICE_SYSTEM
from app.receipts.service import ReceiptService

MAX_VOICE_SECONDS = 60  # longer is a conversation, not an expense; also the cap when converting


def to_wav(data: bytes, rate: int = 16000) -> bytes:
    """Telegram voice (OGG/Opus) or any audio -> 16 kHz mono WAV that every audio model accepts."""
    import av
    from av.container import InputContainer, OutputContainer

    src = cast(InputContainer, av.open(io.BytesIO(data)))
    out_buf = io.BytesIO()
    out = cast(OutputContainer, av.open(out_buf, "w", format="wav"))
    stream = out.add_stream("pcm_s16le", rate=rate, layout="mono")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    samples = 0
    for frame in src.decode(audio=0):
        for f in resampler.resample(frame):
            samples += f.samples
            if samples > MAX_VOICE_SECONDS * rate:
                break
            for p in stream.encode(f):
                out.mux(p)
    for p in stream.encode(None):
        out.mux(p)
    out.close()
    src.close()
    return out_buf.getvalue()


@dataclass
class VoiceResult:
    transcript: str
    receipt: Receipt | None = None
    problem: str | None = None
    # the person named in the message is not in the family
    unknown_who: bool = False


async def handle_voice(
    svc: ReceiptService,
    wav: bytes,
    sender: User | None,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> VoiceResult:
    family = ", ".join(u.name for u in await svc.session.scalars(select(User))) or "none"
    res = await svc.llm.parse_voice(wav, VOICE_SYSTEM.replace("{family}", family))
    v = res.data
    if not v.has_speech or not v.is_expense or v.amount is None or v.amount <= 0:
        return VoiceResult(transcript=v.transcript, problem=t("voice.no_amount"))
    owner = sender
    if v.who:
        owner = await svc.find_user(v.who)
        if owner is None:
            return VoiceResult(transcript=v.transcript, problem=t("voice.unknown_who", who=v.who), unknown_who=True)
    name = (v.name or "").strip().capitalize() or no_description()
    category_id = await svc.classify(name, v.amount) if name != no_description() else None
    receipt = await svc.book_single(
        name=name,
        amount=v.amount,
        category_id=category_id,
        user_id=owner.id if owner else None,
        source="voice",
        note=f"🎤 {v.transcript}" if v.transcript else None,
        chat_id=chat_id,
        message_id=message_id,
    )
    return VoiceResult(transcript=v.transcript, receipt=receipt)
