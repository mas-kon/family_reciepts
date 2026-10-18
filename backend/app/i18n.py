"""Interface language of the family: one language for the bot, the web app and LLM answers.

The language is stored in `app_settings` and cached here; `load_language` fills the cache at
startup and `set_language` updates both. Texts live in `app/locales/`."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting
from app.locales import CATALOGS

DEFAULT_LANGUAGE = "ru"
LANGUAGES = tuple(CATALOGS)
LANGUAGE_KEY = "language"
# the language's own name, for the language picker and for LLM instructions ("answer in ...")
LANGUAGE_NAMES = {"ru": "русский", "en": "English", "bg": "български"}

_current = DEFAULT_LANGUAGE


def current_language() -> str:
    return _current


def use_language(lang: str) -> None:
    """Switch the cached language without touching the database (startup, tests)."""
    global _current
    _current = lang if lang in CATALOGS else DEFAULT_LANGUAGE


async def load_language(session: AsyncSession) -> str:
    row = await session.get(AppSetting, LANGUAGE_KEY)
    use_language(row.value if row else DEFAULT_LANGUAGE)
    return _current


async def set_language(session: AsyncSession, lang: str) -> None:
    if lang not in CATALOGS:
        raise ValueError(lang)
    row = await session.get(AppSetting, LANGUAGE_KEY)
    if row:
        row.value = lang
    else:
        session.add(AppSetting(key=LANGUAGE_KEY, value=lang))
    await session.commit()
    use_language(lang)


def _plural_index(lang: str, n: int) -> int:
    n = abs(n)
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return 0
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return 1
        return 2
    return 0 if n == 1 else 1  # en, bg: one | other


def _message(key: str, lang: str) -> str | tuple[str, ...]:
    for code in (lang, DEFAULT_LANGUAGE):
        if key in CATALOGS[code]:
            return CATALOGS[code][key]
    return key


def t(key: str, /, *, lang: str | None = None, **params) -> str:
    """Text for `key` in the family's language (Russian, then the key itself, when it is missing).
    A key with plural forms takes the count from the `n` parameter."""
    lang = lang or _current
    msg = _message(key, lang)
    if isinstance(msg, tuple):
        # a key missing in this language falls back to Russian forms, which have a different count
        forms = CATALOGS[lang].get(key)
        idx = _plural_index(lang if isinstance(forms, tuple) else DEFAULT_LANGUAGE, params.get("n", 1))
        msg = msg[min(idx, len(msg) - 1)]
    return msg.format(**params) if params else msg


def all_languages(key: str, /, **params) -> list[str]:
    """The text of `key` in every language: for finding a text that was sent before a language switch."""
    return [t(key, lang=code, **params) for code in CATALOGS]
