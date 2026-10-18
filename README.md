# Family Expenses

**English** | [Русский](README.ru.md)

A Telegram bot for a family group plus a web app for tracking expenses.

Buy something, take a photo of the receipt, send it to the group. The bot reads the receipt's QR code, passes the photo to an LLM, gets back the list of purchases with categories and stores it in the database. The web app shows who spends what, where and on what, next to the original receipt photo for checking.

The interface, the bot's replies and the default categories are in Russian. Receipts are expected from Bulgaria, and all amounts are in euros. In this document, interface labels are given in English with the Russian original in brackets, so you can find them on screen.

## Features

**Recording expenses**

- **Receipt photo**, or the image as a file, including HEIC from an iPhone. Discounts and bottle deposits are kept as separate lines.
- **Electronic receipts**: a PDF receipt, a screenshot of an online order or delivery, or an e-mail with a receipt sent to a dedicated mailbox.
- **Bulgarian fiscal QR code** gives the exact date and total, prevents booking the same receipt twice and helps straighten a photo taken sideways. A picture without a QR code (for example a screenshot from a shop app) is recognised as a repeat too: the same total within 30 minutes and the same shop, or the same total within 10 minutes under any name. If the time was misread, a receipt of the same shop with the same total and number of lines within 2 days is kept, and the bot asks "Is this a duplicate?" with buttons to delete it or keep it. A receipt dated in the future is marked "Check".
- **Total check.** If the lines do not add up to the total or to the QR amount, the receipt is marked "Check" («Проверить») with an explanation.
- **Expense as text**: `+ taxi 12`, `/add coffee 3.50`. An amount alone, `+ 12`, is booked under "No category" («Без категории»).
- **Expense by voice message**: "twelve euros taxi".
- **Income**: salary, side jobs, refunds. Added with `/income salary 1500`, in the web app, from a bank statement, from a bank SMS about incoming money or as a recurring income. Counted separately from expenses; the statistics show what is left.
- **Transfers inside the family** count neither as an expense nor as income. Pocket money for a child is not counted twice, once when it is sent and again when the child spends it. You only need to tell the app once how the bank writes the child's name.
- **Bank notifications.** A bank SMS or push notification about a payment or incoming money, forwarded to the group, becomes a record.
- **Bank statement** in CSV or PDF: the web app shows the expenses and income that are not recorded yet. A PDF statement can also be sent to the bot: it lists what is missing and books it at the press of a button. A whole statement can be deleted at once.
- **Expense for another family member**: `+ Masha: cinema 12`, a photo caption `Masha: notebooks`, or by voice. Children without Telegram are added in the web app under Settings → Family («Настройки → Семья»).
- **Recurring payments and income**: rent, internet, subscriptions and salary are booked automatically on their day of the month.
- **Euro only.** If a receipt shows prices in two currencies, the euro amounts are used.

**Editing**

- **In the bot**: reply to the bot's message about a record. Text becomes the description, a number becomes the new amount, and `Masha:` moves the expense to Masha. Every record has a "Delete" button.
- **In the web app**: store, date, total, description, who paid, the lines, their categories and warranty. Deleting asks for confirmation.
- **Remembered categories.** Correct a product's category once, and it is applied to that product on all receipts and future purchases.

**Analysis**

- **Statistics** by category, person, month and store; a filterable list of receipts; CSV export.
- **Questions in plain language** in the web app: "how much did we spend on cafés this summer?".
- **Budgets per category.** The bot warns the group at 80% and when the budget is exceeded.
- **Monthly report** with a chart and a short LLM comment is posted to the group on the 1st of each month. If the service was down then, it is sent at the next start. A receipt cut off by a restart is marked failed and can be re-read in the web app.
- **Price history.** The same product sold under different names in different stores is merged into one.
- **Warranties.** The bot reminds you when an appliance's warranty is about to end.
- **LLM balance and spending** in one place, with a warning in the group when the balance runs low.

## Bot cheat sheet

| Send to the group | Result |
|---|---|
| Receipt photo | The receipt is recognised and booked. The caption becomes its description |
| Photo with the caption `Masha: notebooks` | Booked for Masha with the description "notebooks" |
| PDF receipt, order screenshot | Recognised like a regular receipt |
| PDF bank statement | A list of unrecorded expenses, income and family transfers, a "Book" button and then "Delete the whole statement" |
| `/income salary 1500` | Income of 1500 € in the "Salary" («Зарплата») category |
| `/income Masha: side job 200` | Income booked for Masha |
| `+ taxi 12` or `/add taxi 12` | Expense of 12 € in the "Taxi" category |
| `+ 12` | Expense of 12 € without a description, under "No category" |
| `+ Masha: cinema 12` | Expense booked for Masha |
| Voice message "twelve euros taxi" | Expense of 12 € for a taxi |
| Forwarded bank SMS | An expense, income or family transfer is booked, or the bot says it is already there |
| `/bank text`, or `/bank` as a reply to a message | The same for text the bot did not recognise by itself |
| Text reply to the bot's message | Description of the record |
| Number as a reply to the bot's message | New amount of a single-line record |
| `Masha:` as a reply to the bot's message | The expense is moved to Masha |
| `/help` | Help |
| `/chatid` | The group's ID, for the setup |

All amounts are in euros.

## Stack

| Part | Technology |
|---|---|
| Bot | Python 3.13, aiogram 3 |
| LLM | any OpenAI-compatible API, OpenRouter by default; models are set per task |
| QR, PDF, audio | zxing-cpp, pypdf, pypdfium2, PyAV |
| API | FastAPI, SQLAlchemy 2, Alembic |
| Database | SQLite; switch to PostgreSQL by changing `DATABASE_URL` |
| Frontend | React, Vite, TypeScript, Mantine, TanStack Query, Recharts |
| Runtime | one process for the web app, the bot and the scheduler; Docker Compose or systemd |

## Installation

You need Docker with Compose. To run without Docker, you need [uv](https://docs.astral.sh/uv/) and Node.js 20 or newer.

### 1. Telegram bot

1. In [@BotFather](https://t.me/BotFather), create a bot with `/newbot` and save the token.
2. Still in BotFather, run `/setprivacy`, choose the bot and select **Disable**. Otherwise the bot cannot see photos and voice messages in the group.
3. Add the bot to the family group and send `/chatid` there. The bot replies with the group's ID. This command works before the setup is finished. While `ALLOWED_CHAT_IDS` is empty, the bot answers only `/chatid` and ignores every other chat (it is open to all chats only with `AUTH_DISABLED=true`).

### 2. LLM key

Sign up at [openrouter.ai](https://openrouter.ai), create a key and top up a few dollars. Which models to use for what, and how to save money, is described below under "LLM".

### 3. Configuration

```bash
cp .env.example .env   # .env.example.ru has the same settings with Russian comments
# fill in BOT_TOKEN, ALLOWED_CHAT_IDS, LLM_API_KEY, SECRET_KEY and WEB_PASSWORD
# (SECRET_KEY left as change-me or empty: a random key is created once in data/.secret_key)
# WEB_BIND=127.0.0.1 publishes the port only on this machine, for a reverse proxy running here
```

### 4. Run with Docker

```bash
docker compose up -d --build
```

The web app opens at `http://server-address:8000`; the port comes from `WEB_PORT`. The database and receipt photos are stored in the `data/` folder next to the project. Database migrations run automatically at startup.

```bash
docker compose logs -f              # logs
docker compose restart              # after editing .env
docker compose up -d --build        # after updating the code
docker compose down                 # stop
```

The container restarts by itself after a crash and after the machine reboots.

### 5. Mailbox for electronic receipts (optional)

1. Create a separate mailbox, for example in Gmail. For Gmail, turn on 2-step verification and create an "app password"; the regular password will not work.
2. Set `IMAP_HOST`, `IMAP_USER` and `IMAP_PASSWORD` in `.env`, then run `docker compose restart`.
3. In the web app, under Settings → Family («Настройки → Семья»), enter every address of each person, for example a personal and a work one. Type each address and press Enter. A receipt forwarded from any of them is booked for that person. Mail from an unknown address is processed too, but without an owner.

The bot checks the mailbox every `IMAP_POLL_MINUTES` minutes and posts about each receipt in the group. A message is marked as read only after it has been processed, so a failure does not lose it; every attachment of a message is read as a separate receipt. Whether the mailbox is connected, when it was last checked and the login error, if any, are shown in the web app under Settings → Report and mail («Настройки → Отчёт и почта»), with a "Check the connection" button.

### Run without Docker

```bash
cd frontend && npm ci && npm run build && cd ..
cd backend && uv sync && uv run python -m app.main
```

To start it automatically without Docker, use the systemd unit in `deploy/check-bot.service`. Run only one of the two at a time: two bot instances would compete for incoming messages.

## Signing in to the web app

- **With Telegram.** Works when the web app has a domain. In @BotFather, run `/setdomain` and enter the domain. Only members of the groups in `ALLOWED_CHAT_IDS` are let in.
- **With a password.** Set `WEB_PASSWORD`. Useful while there is no domain. After 5 wrong attempts in a minute, further attempts from that address are refused for a minute.

To open the app to the internet, put a reverse proxy with HTTPS in front of it, for example Caddy:

```
expenses.example.com {
    reverse_proxy localhost:8000
}
```

## LLM

### Models per task

Everything is set in `.env`; no code changes are needed. Each list is comma-separated. If the first model does not answer or hits a rate limit, the next one is used. The current lists are shown in the web app under Settings → LLM («Настройки → Нейросеть»).

| Variable | Task | Model must | If empty |
|---|---|---|---|
| `LLM_MODELS` | Receipt photos, PDFs without text, screenshots | understand images | required |
| `LLM_STRONG_MODELS` | Re-reading a receipt whose totals do not match | understand images, ideally more accurate than the main one | cascade off |
| `LLM_TEXT_MODELS` | Text expenses, bank messages, statements, electronic receipts, report comment, product merging | anything | `LLM_MODELS` is used |
| `LLM_AUDIO_MODELS` | Voice messages | understand audio, e.g. Gemini | voice off |
| `LLM_ASK_MODELS` | Questions in the web app | support tool calling | `LLM_TEXT_MODELS` is used |

An example tested on Bulgarian receipts:

```bash
LLM_MODELS=google/gemini-3.5-flash-lite,google/gemini-3.5-flash,deepseek/deepseek-v4.1-flash
LLM_STRONG_MODELS=google/gemini-3.5-flash,deepseek/deepseek-v4.1-flash
LLM_TEXT_MODELS=google/gemini-3.5-flash-lite,deepseek/deepseek-v4.1-flash
LLM_AUDIO_MODELS=google/gemini-3.5-flash-lite,google/gemini-3.5-flash
```

Other providers, such as Gemini directly or a local Ollama, are connected through `LLM_BASE_URL`. All tasks then go to that one provider. See `.env.example` for examples.

### Costs

A receipt costs about 0.1 cent; text tasks are cheaper still. For a family that is a few cents a month.

OpenRouter lets you connect your own provider keys under Workspace → BYOK. Requests then go through your key and its limits, and OpenRouter charges nothing or a 5% fee. But your key is used only when OpenRouter sends the request to that very provider:

- **Google AI Studio** serves Gemini 3.x. Gemini 2.5 models are not available to new AI Studio users, so OpenRouter sends them to Google Vertex and charges its own balance. Use `google/gemini-3.5-flash-lite` and `google/gemini-3.5-flash` in `.env`.
- **DeepSeek** as a provider serves only dated versions, for example `deepseek/deepseek-v4.1-flash-1017`. `deepseek/deepseek-v4.1-flash` without a date is served by third-party providers and paid from the OpenRouter balance. Also, DeepSeek may train on requests, and OpenRouter will not route to it until you allow that under Settings → Privacy. Whether to allow it is up to you.
- **A spending limit** on the OpenRouter key in `LLM_API_KEY` caps what can be charged to the balance, for example $2 a month.

How each request was paid for is shown in the web app under Settings → LLM.

Note Google's terms: in the EU, the free tier of the Gemini API may not formally be used for an app with users. Free models from other providers may log requests.

### Balance and spending

The Settings → LLM tab («Настройки → Нейросеть») puts everything in one place:

- **OpenRouter balance**: what is left on the account, the key's limit and what remains of it, what was charged today and this month, and how much went through your own keys.
- **DeepSeek balance**, if `DEEPSEEK_API_KEY` is set in `.env`. The key is used only for this; requests still go through `LLM_BASE_URL`.
- **Google AI Studio** has no balance: its free tier limits the number of requests, not money.
- **Spending** for today, 7, 30 or 90 days: by task (receipts, bank, voice, questions...), by model and provider, and by day. What was charged to OpenRouter and what was paid with your own keys are shown separately, along with errors and the average cost per request. Every LLM request is stored in the `llm_calls` table.

Once a day at 9:30 the bot checks the balance and posts in the group if the OpenRouter account or the key's limit has less than `LLM_BALANCE_ALERT` dollars left, 1 by default. It warns about the same low balance only once.

### Testing models on your own receipts

```bash
cd backend
uv run python scripts/test_llm.py ~/receipt1.jpg ~/receipt2.jpg --quiet
uv run python scripts/test_llm.py ~/receipt1.jpg --models google/gemini-3.5-flash-lite,deepseek/deepseek-v4.1-flash
```

The script writes nothing to the database. It shows the response time, the number of lines and whether the sum matches the total and the QR code. A poorly recognised receipt can be re-read with another model in the web app using the "Recognise again" («Распознать заново») button.

## How the LLM features work

**Cascade.** If the lines do not add up to the total or to the QR amount, the receipt is re-read with the models from `LLM_STRONG_MODELS`. If the totals still do not match, the receipt stays marked "Check" with a note saying which model re-read it.

**Record types.** Every record has one of three types:

| Type | What it is | Where it counts |
|---|---|---|
| Expense («Расход») | a purchase, a service, a bank fee, a cash withdrawal, a transfer to someone outside the family | statistics, budgets, report, questions |
| Income («Доход») | salary, a refund, cashback, money from someone outside the family | the separate "Income" total and the balance |
| Inside the family («Внутри семьи») | a transfer to or from a family member | nowhere; only shown in the list of records |

The type can be changed on the record's page. Moves between your own accounts and top-ups from your own card are not booked at all.

**Transfers inside the family.** Under Settings → Family, in the "Name at the bank" («Имя в банке») field, enter how the bank writes the person: `Vera Maslennikova`. Several spellings are allowed. From then on, transfers to and from that person, past and future, count as transfers inside the family. You can do the same from a record: choose "Inside the family", pick the family member and keep the "Remember" («Запомнить») box ticked. The "Statement" page has a "Family: name" type for this.

**Bank notifications.** The bot passes a message to the LLM only if it contains an amount with a currency and a banking word: card, плащане, покупка, постъпление, превод and the like. Ordinary chat never goes to the LLM. Then:
- **Type.** The LLM tells a purchase, income, a transfer to a person and a move between own accounts apart. The record type follows the rules above.
- **Owner.** If the card's last 4 digits are entered for someone under Settings → Family, the record is booked for that person. Otherwise it is booked for whoever forwarded the message.
- **Duplicates.** If the same amount of the same type is already recorded within two days from another source, for example an expense from a receipt, the bot only says so and books nothing. Another bank record counts as the same operation only for the same shop on the same day. Two identical operations of one day are two purchases; loading the same statement again books nothing twice. A notification forwarded twice is recognised too.

**Statement.** The "Statement" page («Выписка») in the web app. Upload a CSV or a PDF with text; scans do not work. The LLM finds the transactions, and the page shows each one's type and which are already recorded, by the same rules. You can change a row's type. Nothing is saved until you press "Book" («Записать»). Importing the same statement again creates no duplicates.

A PDF statement can also be sent to the bot. The bot tells a statement from a receipt by the IBAN and words like "statement" and "balance". It lists unrecorded expenses, income and family transfers in separate groups and books them all with the "Book" button. If you need only some rows, upload the statement in the web app. The button works until the bot restarts. The bot does not book a screenshot of a statement; send the PDF.

**Deleting a statement.** Records from one statement are linked. You can delete them all at once from the "Uploaded statements" list on the "Statement" page, from the list of that statement's records, or with the "🗑 Delete the whole statement" button under the bot's message. Other records are not affected.

**Income categories** are chosen by words in the description: "salary" → "Salary" («Зарплата»), "refund" → "Refunds" («Возвраты»), anything else → "Other income" («Прочие доходы»). The list can be edited under Settings → Categories.

**Voice messages.** Requires `LLM_AUDIO_MODELS`. The bot ignores voice messages longer than a minute. If a message has no speech or is not about an expense, the bot books nothing and quietly reacts with 🤔. The recognised phrase is saved in the record's description.

**Product merging.** After each receipt, the LLM matches new product names against known products in the background. For example, "ПРЯСНО МЛЯКО 3% 1Л" and "Мляко прясно Верея 3% 1л" both become "Milk 3% 1 l". Different sizes stay separate products. On the "Prices" page («Цены») you can select products and merge them by hand, or split a merged product. Automatic merging never overrides your manual choices.

**Warranties.** For appliances and electronics, the LLM takes the warranty period from the receipt. If there is none and the item costs more than 30 €, it sets 24 months, the EU minimum. `WARRANTY_REMIND_DAYS` days before the end, the bot reminds the group. The list is on the "Warranties" page («Гарантии»); the period can be edited on the receipt line.

**Questions.** The LLM does not see the database directly and cannot change anything. It can call only three functions: totals for a period, spending by month and a purchase search. If there is no data, it says so.

**Report comment.** The monthly report gets 2–4 sentences about what went up, what was unusual and which budgets were exceeded. If the LLM is unavailable, the report is posted without the comment.

## Development

```bash
# backend without sign-in and without the bot
cd backend && AUTH_DISABLED=true uv run python -m app.main
# frontend with hot reload; /api requests are proxied to :8000
cd frontend && npm run dev
# tests
cd backend && uv run pytest
# new migration after changing the models
cd backend && uv run alembic revision --autogenerate -m "description"
```

API documentation: `/api/docs`.

Where things are in the backend:

| Module | What it does |
|---|---|
| `app/receipts/service.py` | receipt recognition, cascade, PDFs, electronic receipts, text expenses |
| `app/bank.py` | bank notifications, statements, transaction types and transfers inside the family |
| `app/voice.py` | voice messages |
| `app/products.py` | product merging |
| `app/ask.py` | questions and the functions the LLM may call |
| `app/email_inbox.py` | receipts from the mailbox |
| `app/warranty.py` | warranty reminders |
| `app/reports.py` | monthly report and its comment |
| `app/llm/` | LLM client (one per process, model fallback), prompts and response schemas |
| `app/llm/usage.py` | request log, provider balances, low-balance warning |
| `app/bot/handlers.py` | the bot (an access check for family chats runs before every handler) |
| `app/bot/ui.py` | bot messages and buttons, also used by the jobs and the mailbox poller |
| `app/family.py` | family members found by name, card, e-mail or the name in the bank |
| `app/clock.py` | local time (`now_local`) |
| `app/constants.py` | record kinds and shared names |
| `app/api/` | web API, one module per resource (receipts, stats, users, categories, budgets, recurring, llm, ai, auth) |

## Backup

All state lives in the `data/` folder: the `app.db` database and the receipt photos. A copy of the database can be taken while the app is running:

```bash
docker compose exec check-bot python -c "import sqlite3; sqlite3.connect('/app/data/app.db').backup(sqlite3.connect('/app/data/app-backup.db'))"
tar czf backup-$(date +%F).tgz data/
```
