"""The receipt service: one class made of its parts, and the names other modules import."""

from app.receipts.base import ProcessResult, single_item
from app.receipts.images import pdf_text_and_preview, prepare_photo
from app.receipts.parsing import add_months, income_category_name, parse_manual_text, split_who
from app.receipts.recognition import (
    DUPLICATE_MINUTES,
    DUPLICATE_NEAR_MINUTES,
    PROBABLE_DUPLICATE_DAYS,
    RecognitionMixin,
)
from app.receipts.records import RecordsMixin

__all__ = [
    "DUPLICATE_MINUTES",
    "DUPLICATE_NEAR_MINUTES",
    "PROBABLE_DUPLICATE_DAYS",
    "ProcessResult",
    "ReceiptService",
    "add_months",
    "income_category_name",
    "parse_manual_text",
    "pdf_text_and_preview",
    "prepare_photo",
    "single_item",
    "split_who",
]


class ReceiptService(RecognitionMixin, RecordsMixin):
    """Recognition (photos, PDFs, e-mails) and records (typed, spoken, bank, edits) share the
    session and the LLM client set up in ServiceBase."""
