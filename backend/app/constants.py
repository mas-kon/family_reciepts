"""Values that several modules share. The enums are str subclasses: they compare equal to the
plain strings kept in the database and sent to the web app."""

from enum import StrEnum


class Kind(StrEnum):
    """What a record is. Only EXPENSE counts as spending; TRANSFER is money moved inside the family."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"


# names given to a record that came without a description; the web and the bot may rename them
NO_DESCRIPTION = "Без описания"
INCOME_DEFAULT = "Поступление"
PURCHASE_DEFAULT = "Покупка"
