"""CPU work on pictures and PDFs: call these in a thread."""

import io

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.receipts.qr import FiscalQR, find_fiscal_qr

register_heif_opener()


def prepare_photo(data: bytes, ext: str) -> tuple[Image.Image, FiscalQR | None, str | None, bytes, str]:
    """Decodes a photo, reads its fiscal QR code and straightens a receipt shot sideways or
    upside down. CPU work: call it in a thread. Returns (image, qr, qr text, bytes to keep, ext)."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    image.load()
    qr, qr_raw, rotation = find_fiscal_qr(image)
    if rotation:
        image = image.rotate(rotation, expand=True)
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=92)
        data, ext = buf.getvalue(), "jpg"
    return image, qr, qr_raw, data, ext


def pdf_text_and_preview(data: bytes, max_pages: int = 3) -> tuple[str, bytes]:
    """Text layer of the first pages and a JPEG of the first page."""
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])
    except Exception:
        text = ""
    pdf = pdfium.PdfDocument(data)
    page = pdf[0].render(scale=2.5).to_pil().convert("RGB")  # pyright: ignore[reportArgumentType]
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=90)
    return text, buf.getvalue()
