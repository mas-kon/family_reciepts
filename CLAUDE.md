# CLAUDE.md

Family expense tracker: a Telegram bot takes receipt photos, bank messages, statements, voice and text in a family group; an LLM turns them into records; a React web app shows statistics. Overview, features and setup: [README.md](README.md) (English) and [README.ru.md](README.ru.md) (Russian).

The user writes in Russian, so answer in Russian. The UI, bot replies and default categories are in Russian too.

## Documentation must stay current, in English and Russian

Every change that affects behaviour, settings, commands or setup updates the docs **in the same change, in both languages**:

| English | Russian |
|---|---|
| `README.md` | `README.ru.md` |
| `.env.example` | `.env.example.ru` |

- Both versions say the same thing. Change one, change the other.
- `.env.example` and `.env.example.ru` hold identical settings; only the comments differ. Check: `diff <(grep -v '^#' .env.example | grep -v '^$') <(grep -v '^#' .env.example.ru | grep -v '^$')`.
- In the English README, UI labels are given in English with the Russian original in brackets: Settings → Family («Настройки → Семья»).
- New bot commands go into the bot cheat sheet in both READMEs and into `HELP` in `backend/app/bot/handlers.py`.
- New backend modules go into the module table under "Development" / «Разработка».

## Layout

- `backend/app/` — Python 3.13, uv. FastAPI, aiogram 3, SQLAlchemy 2 async on SQLite, APScheduler. One process runs the web app, the bot and the scheduler (`app/main.py`).
  - `receipts/service.py` receipts and single records (`book_single`), `bank.py` bank messages, statements, record kinds and family transfers, `family.py` member lookups, `clock.py` (`now_local`), `constants.py` (`Kind`), `bot/ui.py` messages and buttons, `voice.py`, `products.py`, `ask.py`, `email_inbox.py`, `warranty.py`, `reports.py`, `stats.py`, `scheduler.py`.
  - `llm/` client (one shared `get_llm()`, model fallback, usage logging), `prompt.py`, `schema.py`, `usage.py` (request log, balances).
  - `api/` FastAPI routers, `bot/handlers.py` the bot.
- `backend/alembic/versions/` hand-numbered migrations `0001`… `0008`.
- `frontend/src/` React 19, Vite, TypeScript, Mantine, TanStack Query, Recharts. `api.ts` holds the types that mirror the API.
- `data/` (git-ignored) holds `app.db` and receipt photos. This is the family's real data.

## Commands

```bash
cd backend && uv run pytest                      # backend tests
cd backend && uv run ruff check .                # lint (CI runs it too)
cd frontend && npx tsc -b && npm run build       # type check and build
docker compose up -d --build                     # deploy (from the project root); migrations run at startup
docker compose logs -f
```

The production app runs in the `check-bot` container on this machine. After a change, rebuild it and check it is `healthy`. The container has no `curl` or `httpx`; use `urllib` in `docker exec check-bot python -c ...`. A signed-in API call from inside the container: `make_cookie(Viewer(user_id=None, name='check', method='password'))` from `app.api.deps`, sent as the `cb_session` cookie.

## Rules

- **Euro only.** No other currencies anywhere.
- **Record kinds.** `Receipt.kind` is `expense`, `income` or `transfer` (inside the family). Spending statistics, budgets, reports and questions count only `expense`; `stats._filtered` does this through its `kind` argument. Every new aggregation must filter by kind. Transfers to family members (matched by `User.bank_names`) are never spending.
- **The bot does not show statistics.** The group is for sending things in; statistics live in the web app. The monthly report and budget, warranty and balance warnings are the agreed exceptions.
- **LLM prompts contain no concrete example values** that a model could echo back. A voice prompt with example phrases made models "hear" those phrases in silence. Describe the format, not sample content.
- **Every LLM request goes through `LLMClient._create`** with a task name, so it lands in `llm_calls`. A new task gets a label in `TASK_LABEL` in `llm/usage.py`.
- **Models are configured per task in `.env`** (`LLM_MODELS`, `LLM_STRONG_MODELS`, `LLM_TEXT_MODELS`, `LLM_AUDIO_MODELS`, `LLM_ASK_MODELS`). Keep the code provider-agnostic (OpenAI-compatible API).
- **Secrets.** `.env` holds real tokens and keys: never print their values, show them masked. Never commit `.env`, `data/` or personal photos. Test fixtures must have EXIF stripped (GPS).
- **Git.** The user commits. Do not commit or push unless asked.
- **Real data.** Do not modify or delete records in `data/app.db` on your own. Test migrations and risky queries on a copy in the scratchpad first (`DATABASE_URL=sqlite+aiosqlite:///<copy> uv run alembic upgrade head`, then downgrade and upgrade again).

## Gotchas

- **Migrations** use `render_as_batch` (SQLite). Autogenerate needs hand fixes: give every constraint and foreign key an explicit name, and give a new NOT NULL column a `server_default`.
- **Lazy loading in async** raises `MissingGreenlet`: use `await obj.awaitable_attrs.items`, or set `items=[]` when creating a record. Sessions use `expire_on_commit=False`.
- **Cyrillic search**: SQLite's `lower()` is replaced with a Unicode version in `db/session.py`; use `icontains()` for case-insensitive search.
- **Tests**: `tests/conftest.py` sets env vars before importing the app and blanks the model lists, so the developer's `.env` does not leak in. `FakeLLM` replaces the real client. Bot tests feed updates through a fresh `Dispatcher` (`dp` fixture) with a fake Telegram session; fake messages need `.as_(bot)`.
- **SQLite dates**: `func.strftime` is used for month and day grouping; on PostgreSQL it would be `to_char`.
- **OpenRouter BYOK**: a user key is used only when OpenRouter routes to that provider. Gemini 3.x goes through Google AI Studio; Gemini 2.5 does not. The DeepSeek provider serves only dated model ids, and the user's privacy settings currently block it. `llm_calls.is_byok` and `provider` show what actually happened.
