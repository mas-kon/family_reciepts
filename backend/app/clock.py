"""Local time. The database keeps naive datetimes in the family's time zone (TIMEZONE)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone)).replace(tzinfo=None, microsecond=0)
