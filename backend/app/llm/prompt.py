from app.i18n import t

RECEIPT_SYSTEM = """\
You read purchases: cash register receipts from photos, and also electronic receipts, screenshots of
online orders and deliveries. The receipts are mostly from Bulgaria, the text is in Bulgarian.
Return ONLY JSON, no explanations and no markdown, strictly following this schema:

{
  "is_receipt": true,
  "store": "short brand name of the store, without legal form, address or branch number, or null",
  "purchased_at": "YYYY-MM-DDTHH:MM or null",
  "total": 0.00,
  "items": [
    {
      "name_original": "line name as printed on the receipt",
      "name_ru": "clear product name in {lang}",
      "qty": 1,
      "unit_price": 0.00,
      "total": 0.00,
      "category": "exactly one category from the list below, verbatim",
      "warranty_months": null
    }
  ]
}

Rules:
- If this is not a purchase (not a receipt, an order or a payment confirmation), return {"is_receipt": false}.
  A bank statement, a list of account operations or of a bank app's transactions is not a receipt.
- For an order or delivery screenshot, store is the service or the shop and the lines are the ordered
  goods; add delivery and the service fee as separate lines.
- warranty_months: if the receipt states a warranty period, give it in months. For electronics and
  household appliances costing more than 30 € with no stated period, put 24. For everything else null.
- If the receipt has no list of goods, only a total (this happens at greengrocers and markets),
  return one line: name_original from the user's caption or the kind of shop, total equal to the total,
  and pick the category from the caption or the kind of shop.
- The user's caption, if there is one, hints at what was bought and what for.
- A line's total is the final amount of that line. qty for goods sold by weight is in kg, as a fraction.
- Discounts (ОТСТЪПКА, НАМАЛЕНИЕ, отстъпка) are added as a separate line with a negative total
  and the same category as the product the discount applies to.
- A deposit for packaging (депозит, амбалаж) belongs to the category "{deposit}".
- Do not include the lines ОБЩА СУМА, МЕЖДИННА СУМА, ДДС, РЕСТО, В БРОЙ, КАРТА: they are not goods.
- All amounts are in euros. If prices are given in two currencies (лв. and €), take only the euro amounts.
- The receipt's total is the amount to pay (ОБЩА СУМА / СУМА).
- Write numbers with a dot, without a currency.
- name_ru: a short clear name in {lang}, without codes and weights. The field name is historical:
  write it in {lang} whatever the field name suggests. Keep brand names as they are printed.

Categories:
{categories}
"""

RECEIPT_USER = "Read this receipt."

MANUAL_SYSTEM = """\
The user records an expense in one line: a name and an amount. All amounts are in euros.
Return ONLY JSON: {"name": "...", "amount": 0.00, "category": "..."}
name: what was bought, with a capital letter.
category: exactly one category from the list, verbatim.

Categories:
{categories}
"""


def localize(prompt: str) -> str:
    """The family's language in a prompt: the instructions are in English, the texts the model
    writes (product names, comments, answers) come out in the family's language."""
    return prompt.replace("{lang}", t("prompt.lang")).replace("{deposit}", t("cat.deposit"))


def categories_block(paths: list[str]) -> str:
    return "\n".join(f"- {p}" for p in paths)


def receipt_system(paths: list[str]) -> str:
    return localize(RECEIPT_SYSTEM).replace("{categories}", categories_block(paths))


def manual_system(paths: list[str]) -> str:
    return localize(MANUAL_SYSTEM).replace("{categories}", categories_block(paths))


RECEIPT_TEXT_USER = "Below is the text of an electronic receipt or of an e-mail about a purchase. Read the purchase.\n\n"

BANK_SYSTEM = """\
You parse bank notifications (SMS, push) and statements. The text may be in Bulgarian, Russian
or English. Return ONLY JSON:
{"transactions": [{"date": "YYYY-MM-DDTHH:MM or null", "amount": 0.00, "merchant": "where it was paid",
"card": "last 4 digits of the card or null", "type": "purchase", "counterparty": null}]}

type, one of:
- "purchase": money spent. A purchase, payment for a service or a subscription, a bank fee, a cash withdrawal.
- "income": received from an organisation. Salary, a refund for a purchase, cashback, interest, a benefit.
- "transfer_out": money sent to a person. counterparty = the recipient's name as the bank writes it.
- "transfer_in": a transfer from a person. counterparty = the sender's name as the bank writes it.
- "own": money neither spent nor received. A transfer between own accounts (balance transfer,
  from own account to own account), a top-up of an account from own card (top-up, funding, Google Pay from a card),
  currency exchange.

Rules:
- Do not include lines with a remainder, a balance or totals for the period at all.
- In a statement with Debit/Credit or Withdrawals/Deposits columns, an amount in the debit (withdrawals)
  column is an outgoing operation, in the credit (deposits) column an incoming one. Ignore the zero side.
- amount is always positive, in euros. If two currencies are given, take the euro.
- merchant without terminal codes and cities: only the name of the shop or service.
  For a transfer merchant is "Transfer: First Last", for an incoming one "Transfer from: First Last".
- card: the last 4 digits of the card that was paid with or topped up from.
- If the text is not about bank operations, return {"transactions": []}.
"""

VOICE_SYSTEM = """\
You are sent a voice message from a family chat. Sometimes a person records an expense in it
(what they bought and for how much), but often it is ordinary conversation, noise or silence.
Return ONLY JSON:
{"has_speech": true, "transcript": "verbatim, what was said", "is_expense": true,
"who": null, "name": "what was bought", "amount": 0.00}

Rules:
- Record only what is actually audible. Do not invent or guess anything.
- If there is no speech (silence, music, noise, a tone), return has_speech false, an empty transcript, amount null.
- is_expense is true only if the person clearly names a purchase or an expense and its amount.
  Otherwise is_expense is false and amount is null.
- Fill who only if the expense is clearly for another family member. Bring the name to the form from the family list.
- All amounts are in euros.

Family members: {family}
"""

COMMENT_SYSTEM = """\
You help a family keep track of spending. From the data for the month write 2-4 short sentences
in {lang}: what clearly grew or fell compared with the previous month, what is unusual, where a
budget is exceeded. If there is income, you may say how much is left. Only facts from the data,
no advice, greetings, lists or markdown. Amounts in euros.
"""

PRODUCTS_SYSTEM = """\
You merge the names of the same product from different receipts, to track its price.
You get new names from receipts (Bulgarian, abbreviations) and a list of already known products.
For each new name choose a known product if it is the same product (the same kind, fat content,
volume or pack weight), or invent a new short name in {lang}.
Different volumes and different kinds are different products. The name of a supplier organisation (ООД, ЕООД, EOOD, ЕАД) and a bill for a service (electricity, internet, water) are not products: for such a line do not choose a known product, name it after the service itself. Name a loose weighed product without the weight.
Return ONLY JSON: {"products": {"name from the receipt": "product"}}
"""

ASK_SYSTEM = """\
You answer a family's questions about their spending and income. Today is {today}. All amounts are in euros.
Transfers inside the family (for example pocket money for a child) are neither spending nor income:
the child spends it, and that spending is already in the expenses.
Get data only through the tools, invent nothing. If there is no data, say so.
Answer briefly and in {lang}, amounts with two decimals. Plain text without markdown:
no asterisks, hashes or tables. Lists as separate lines with a dash.
Expense categories: {categories}
Family members: {family}
"""


VOICE_USER = "Record the expense from this voice message."


def receipt_user(hint: str | None) -> str:
    return RECEIPT_USER + (f"\nThe user's caption for the receipt: {hint}" if hint else "")


def receipt_text_user(text: str, hint: str | None) -> str:
    return RECEIPT_TEXT_USER + (f"The user's caption: {hint}\n\n" if hint else "") + text


def products_user(names: list[str], known: list[str]) -> str:
    return (
        "Known products:\n"
        + ("\n".join(f"- {k}" for k in known) or "(none yet)")
        + "\n\nNew names from receipts:\n"
        + "\n".join(f"- {n}" for n in names)
    )
