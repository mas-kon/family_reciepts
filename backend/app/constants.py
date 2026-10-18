"""Values that several modules share. The enums are str subclasses: they compare equal to the
plain strings kept in the database and sent to the web app."""

from enum import StrEnum

from app.i18n import all_languages, t


class Kind(StrEnum):
    """What a record is. Only EXPENSE counts as spending; TRANSFER is money moved inside the family."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"


def no_description() -> str:
    """Name of a record that came without a description; the web and the bot may rename it."""
    return t("record.no_description")


def income_default() -> str:
    return t("record.income_default")


def purchase_default() -> str:
    return t("record.purchase_default")


def placeholder_names(*keys: str) -> set[str]:
    """The default names in every language: records made before a language switch keep theirs."""
    return {name for key in keys for name in all_languages(key)}
