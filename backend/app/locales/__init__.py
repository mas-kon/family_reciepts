"""Message catalogs, one module per language: a flat dict of key -> text with `{name}` placeholders.
A key that has plural forms holds a tuple of forms (see `app.i18n.plural`)."""

from app.locales import bg, en, ru

CATALOGS: dict[str, dict[str, str | tuple[str, ...]]] = {"ru": ru.MESSAGES, "en": en.MESSAGES, "bg": bg.MESSAGES}
