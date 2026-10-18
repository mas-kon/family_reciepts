# Пример настроек. Скопируйте в .env и заполните: cp .env.example.ru .env
# English version: .env.example

# ===== Telegram =====
# Токен от @BotFather. У бота отключите privacy mode: /setprivacy -> Disable
BOT_TOKEN=
# ID семейной группы (узнать: добавить бота и написать /chatid). Несколько через запятую.
ALLOWED_CHAT_IDS=
# Пусто: бот отвечает только на /chatid (всё открыто лишь при AUTH_DISABLED=true).
# Куда слать месячный отчёт и предупреждения о бюджете. По умолчанию первая группа из списка.
# REPORT_CHAT_ID=

# ===== Нейросеть (любой OpenAI-совместимый API) =====
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=
# Модели по порядку: если первая не ответила, пробуется следующая.
# Чеки по фото (нужны модели, которые понимают картинки).
# Gemini 3.x идут через ключ Google AI Studio, если он подключён в OpenRouter (BYOK); 2.5 новым
# пользователям AI Studio уже недоступны и оплачиваются с баланса OpenRouter.
LLM_MODELS=google/gemini-3.5-flash-lite,google/gemini-3.5-flash,deepseek/deepseek-v4.1-flash
# Каскад: если суммы в чеке не сошлись, он перечитывается этими моделями. Пусто = выключено.
LLM_STRONG_MODELS=google/gemini-3.5-flash,deepseek/deepseek-v4.1-flash
# Текстовые задачи: траты текстом, банковские уведомления и выписки, комментарий к отчёту,
# склейка товаров, электронные чеки. Пусто = LLM_MODELS.
LLM_TEXT_MODELS=google/gemini-3.5-flash-lite,deepseek/deepseek-v4.1-flash
# Голосовые сообщения (нужны модели, которые понимают звук, например Gemini). Пусто = выключено.
LLM_AUDIO_MODELS=google/gemini-3.5-flash-lite,google/gemini-3.5-flash
# Вопросы в вебе (нужна поддержка вызова функций). Пусто = LLM_TEXT_MODELS.
# LLM_ASK_MODELS=

# Баланс (Настройки → Нейросеть). Бот предупредит в группе, когда на счёте OpenRouter или в лимите
# ключа останется меньше этой суммы, USD. 0 = не предупреждать.
# LLM_BALANCE_ALERT=1
# Ключ DeepSeek, только чтобы показывать его баланс. Запросы всё равно идут через LLM_BASE_URL.
# DEEPSEEK_API_KEY=

# Другие провайдеры, примеры:
# Google Gemini напрямую (есть бесплатный лимит):
#   LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
#   LLM_MODELS=gemini-3.5-flash-lite
# Локальная Ollama:
#   LLM_BASE_URL=http://localhost:11434/v1
#   LLM_MODELS=qwen2.5vl:7b

# ===== Веб =====
WEB_HOST=0.0.0.0
WEB_PORT=8000
# Публичный адрес веба, для кнопки «Открыть» в боте
WEB_BASE_URL=
# Случайная строка для подписи cookie: python3 -c "import secrets;print(secrets.token_urlsafe(32))"
# Если оставить change-me или пусто, один раз создаётся случайный ключ и хранится в data/.secret_key.
SECRET_KEY=change-me
# Адрес, на котором Docker публикует порт. 127.0.0.1, если реверс-прокси стоит на этой же машине.
# WEB_BIND=0.0.0.0
# Запасной вход по паролю, если нет домена для Telegram Login. Пусто = выключен.
WEB_PASSWORD=
# Отключить вход совсем. Только для локальной разработки!
# AUTH_DISABLED=true

# ===== Чеки по почте (IMAP) =====
# Отдельный ящик, куда пересылаются электронные чеки. Пусто = выключено.
# Для Gmail нужен «пароль приложения», обычный пароль не подойдёт.
# IMAP_HOST=imap.gmail.com
# IMAP_PORT=993
# IMAP_USER=checks.family@gmail.com
# IMAP_PASSWORD=
# IMAP_FOLDER=INBOX
# IMAP_POLL_MINUTES=10

# ===== Гарантии =====
# За сколько дней до конца гарантии напоминать в группе
# WARRANTY_REMIND_DAYS=30

# ===== Прочее =====
# DATABASE_URL=sqlite+aiosqlite:////root/check_bot/data/app.db
TIMEZONE=Europe/Sofia
