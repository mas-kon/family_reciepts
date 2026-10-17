"""Bulgarian fiscal receipt QR code (Наредба Н-18).

Format: <fiscal device no>*<receipt no>*<YYYY-MM-DD>*<HH:MM:SS>*<amount>
Example: DT123456*0012345*2026-01-15*14:30:25*23.40

The code has no line items, so we use it to detect duplicates and to cross-check the total.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from PIL import Image

_QR_RE = re.compile(
    r"^\s*(?P<device>[A-Z0-9]{6,12})\*(?P<number>\d{1,10})\*(?P<date>\d{4}-\d{2}-\d{2})"
    r"\*(?P<time>\d{2}:\d{2}(?::\d{2})?)\*(?P<amount>-?\d+(?:[.,]\d+)?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FiscalQR:
    raw: str
    device: str
    number: str
    purchased_at: datetime
    amount: float

    @property
    def fiscal_key(self) -> str:
        return f"{self.device}:{self.number}:{self.purchased_at:%Y%m%d}"


def parse_fiscal_qr(text: str) -> FiscalQR | None:
    m = _QR_RE.match(text or "")
    if not m:
        return None
    t = m["time"] if m["time"].count(":") == 2 else m["time"] + ":00"
    try:
        dt = datetime.strptime(f"{m['date']} {t}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return FiscalQR(
        raw=text.strip(),
        device=m["device"].upper(),
        number=m["number"].lstrip("0") or "0",
        purchased_at=dt,
        amount=float(m["amount"].replace(",", ".")),
    )


def read_qr(image: Image.Image) -> list[tuple[str, int]]:
    """All codes on the photo as (text, orientation in degrees). Image must be EXIF-transposed."""
    import zxingcpp

    img = image.convert("L")
    found: list[tuple[str, int]] = []
    # Try original and a downscaled copy: phone photos are huge and zxing can miss small codes.
    variants = [img]
    if max(img.size) > 1600:
        scale = 1600 / max(img.size)
        variants.append(img.resize((int(img.width * scale), int(img.height * scale))))
    for v in variants:
        for r in zxingcpp.read_barcodes(v):
            if r.text and r.text not in [t for t, _ in found]:
                found.append((r.text, r.orientation))
        if found:
            break
    return found


def upright_rotation(orientation: int) -> int:
    """Angle for PIL Image.rotate() that makes a code with this orientation upright."""
    return (round(orientation / 90) * 90) % 360


def find_fiscal_qr(image: Image.Image) -> tuple[FiscalQR | None, str | None, int]:
    """Parsed fiscal QR (if any), raw text of the first code, and the rotation that
    puts the receipt upright (0 when unknown)."""
    codes = read_qr(image)
    for text, orient in codes:
        parsed = parse_fiscal_qr(text)
        if parsed:
            return parsed, text, upright_rotation(orient)
    if codes:
        return None, codes[0][0], upright_rotation(codes[0][1])
    return None, None, 0
