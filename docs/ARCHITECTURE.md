````markdown
# ARCHITECTURE.md

## 0. Назначение документа

Этот файл — единый источник правды о проекте. Прикрепляется в начало любой сессии разработки с промптом вида:
> "Используя архитектурный контекст, реализуй **Этап N**. Следуй контрактам, не меняй структуру модулей без явного запроса."

---

## 1. Цель проекта

Сервис автоматически собирает посты из множества площадок, ежедневно оценивает их LLM-ом на релевантность профилю пользователя, а раз в неделю отправляет структурированный дайджест в Telegram.

**Главная цель — поиск идей для проектов и болей аудитории** в нишах "данные, системный анализ, MVP, автоматизация, SaaS, стартапы". Habr даёт тренды и туториалы, но идеи и реальные боли живут в других местах (Hacker News, IndieHackers, Reddit) — под них проект и затачивается при расширении.

---

## 2. Технологический стек

| Слой | Технология | Назначение |
|---|---|---|
| Язык | Python 3.11 | — |
| LLM | OpenAI API (gpt-4o-mini для оценки, gpt-4o для дайджеста) | скоринг и генерация |
| БД | PostgreSQL (Docker на сервере, подключение по URL) | хранилище |
| ORM | SQLAlchemy 2.x (async, `Mapped[...]`) | работа с БД |
| Схема БД | SQL-скрипт `db/init.sql` (выполняется вручную) | DDL |
| HTTP | httpx (async) | загрузка фидов/страниц |
| Парсинг | feedparser (RSS), BeautifulSoup4 (HTML при необходимости) | извлечение постов |
| Telegram | aiogram 3.x | бот и доставка |
| Планировщик | APScheduler (внутри контейнера) | cron-задачи |
| Конфиг | YAML (`sources.yaml`) + `.env` + pydantic-settings | настройки |
| Логи | structlog (JSON) | наблюдаемость |
| CLI | typer | ручной запуск шагов |
| Throttling | собственный per-domain throttler (`utils/throttle.py`) | защита от банов |
| Зависимости | pip + requirements.txt | — |
| Контейнеризация | Docker + docker-compose | деплой |
| Тесты | pytest + pytest-asyncio | — |

### requirements.txt (полный перечень с назначением)

```
# Ядро
python-dotenv           # чтение .env (если нужно вне pydantic)
pydantic>=2.0           # контракты и валидация
pydantic-settings       # чтение настроек из .env
pyyaml                  # парсинг sources.yaml
typer                   # CLI-команды (collect/score/digest/...)
structlog               # JSON-логирование

# HTTP и парсинг
httpx                   # async HTTP-клиент
feedparser              # RSS/Atom
beautifulsoup4          # HTML-парсинг (fallback)
lxml                    # быстрый парсер для bs4/feedparser

# БД
sqlalchemy>=2.0         # ORM
asyncpg                 # async-драйвер PostgreSQL

# LLM
openai>=1.0             # OpenAI API
tenacity                # ретраи LLM-вызовов

# Telegram
aiogram>=3.0            # бот

# Планировщик
apscheduler             # cron-задачи

# Тесты (dev)
pytest
pytest-asyncio
```

> Зависимости для новых источников (async-praw, vk_api, telethon и т.д.) добавляются **на своём этапе**, а не заранее.

---

## 3. Принципы архитектуры

1. **Plugin-based источники.** Каждый источник = класс, реализующий `BaseSource`. Добавление источника = новый файл в `sources/`, без изменений в ядре.
2. **Универсальность важнее частных случаев.** Общая логика (фильтры по рейтингу/вовлечённости, throttling, приведение к UTC) — в ядре, а не в каждом коннекторе.
3. **Слой контрактов.** Все межмодульные обмены — через pydantic-модели (`schemas/`).
4. **Идемпотентность.** Повторный запуск не создаёт дубли (уникальность по `source + external_id`).
5. **Все шаги атомарны и перезапускаемы:** collect → score → digest → deliver.
6. **LLM-вызовы изолированы** в `llm/` с ретраями и логом стоимости.
7. **Никаких изменений контрактов без обновления этого файла.**

---

## 4. Доменные сущности (схема БД)

```
sources              -- справочник источников (habr, hackernews, ...)
  id, name, type, config_json, is_active

posts                -- сырые посты
  id, source_id, external_id, url, title, author,
  content, published_at, rating, engagement, raw_json, collected_at
  UNIQUE(source_id, external_id)

post_scores          -- оценка LLM
  id, post_id, relevance_score (0-10),
  category (trend|pain|case|idea|other),
  summary (1-2 предложения),
  problem (какую боль описывает пост, nullable),
  opportunity (можно ли сделать продукт, nullable),
  topics (jsonb массив тем),
  scored_at, model, tokens_used

digests              -- сформированные дайджесты
  id, period_start, period_end, content_md,
  created_at, sent_at, is_manual

digest_posts         -- какие посты вошли в дайджест
  digest_id, post_id

delivery_log         -- что уже отправлено пользователю
  id, post_id, sent_at, digest_id
```

**Изменения относительно первой версии (для расширения на "идеи"):**
- `posts.engagement INTEGER NULL` — универсальная метрика вовлечённости (лайки/комментарии/очки), не привязанная к рейтингу Habr.
- `post_scores.problem TEXT NULL` — извлечённая боль.
- `post_scores.opportunity TEXT NULL` — потенциал продукта.

Схема создаётся один раз через `db/init.sql`. При изменении моделей — правим SQL вручную и применяем psql (осознанное решение для одиночного MVP).

---

## 5. Структура проекта (актуальная)

```
trend-radar/
├── Dockerfile
├── README.md
├── requirements.txt
├── .env.example
├── docker-compose.yml
├── config/
│   ├── sources.yaml
│   └── prompts/
│       ├── user_profile.md
│       ├── score_post.md
│       └── build_digest.md
├── docs/
│   ├── ARCHITECTURE.md          # этот файл
│   └── PROMPTS.md               # описание/версии промптов
├── src/
│   ├── __init__.py
│   ├── main.py                  # entrypoint + CLI (typer)
│   ├── settings.py              # pydantic-settings
│   ├── scheduler.py             # APScheduler jobs
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── init.sql             # DDL всех таблиц
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── post.py
│   │   ├── score.py
│   │   └── digest.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseSource (ABC)
│   │   ├── registry.py          # фабрика источников по type
│   │   └── habr.py              # [Этап 0 — готово]
│   │   # далее: rss_generic.py, reddit.py, vk.py, telegram.py, youtube.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py            # OpenAI wrapper + ретраи + лог токенов
│   │   ├── scorer.py            # оценка поста
│   │   └── digest_builder.py    # сборка дайджеста
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── collect.py
│   │   ├── score.py
│   │   ├── digest.py
│   │   └── deliver.py
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── bot.py
│   │   ├── handlers.py
│   │   └── keyboards.py
│   └── utils/
│       ├── __init__.py
│       ├── logging.py
│       ├── retry.py
│       └── throttle.py          # [добавляется на Этапе 5.5]
└── tests/
    ├── __init__.py
    ├── test_scorer.py
    ├── test_sources_habr.py
    └── ...
```

---

## 6. Ключевые контракты (pydantic)

### `schemas/post.py`
```python
class RawPost(BaseModel):
    source_name: str
    external_id: str
    url: HttpUrl
    title: str
    author: str | None = None
    content: str = ""
    published_at: datetime          # всегда UTC
    rating: int | None = None       # специфичная метрика (рейтинг Habr)
    engagement: int | None = None   # универсальная вовлечённость (очки/комменты)
    raw: dict = {}
```

### `schemas/score.py`
```python
class PostScore(BaseModel):
    relevance_score: int                    # 0-10
    category: Literal["trend", "pain", "case", "idea", "other"]
    summary: str                            # 1-2 предложения
    problem: str | None = None              # какую боль описывает пост
    opportunity: str | None = None          # можно ли сделать продукт
    topics: list[str]                       # ["data engineering", "MVP"]
```

### `sources/base.py`
```python
class BaseSource(ABC):
    name: str
    type: str

    @abstractmethod
    async def fetch(self, since: datetime) -> list[RawPost]:
        ...
```

**Контракты не меняем между этапами.** При необходимости — сначала правим `ARCHITECTURE.md` отдельным шагом.

---

## 7. Формат `config/sources.yaml`

```yaml
# Общие фильтры применяются ядром (pipeline.collect), а не коннекторами.
sources:
  # --- Habr (Этап 0) ---
  - name: habr_ml
    type: habr
    enabled: true
    filters:
      min_rating: 10          # применяется ядром, если у поста есть rating
    params:
      hub: machine-learning

  - name: habr_python
    type: habr
    enabled: true
    filters:
      min_rating: 5
    params:
      hub: python

  # --- Универсальный RSS (Этап 5) ---
  - name: hackernews
    type: rss_generic
    enabled: false            # включаем на Этапе 5
    filters:
      min_engagement: 100
    params:
      url: https://hnrss.org/newest?points=100

  - name: indiehackers
    type: rss_generic
    enabled: false
    params:
      url: https://www.indiehackers.com/rss
```

Поля:
- `name` — уникальный идентификатор (используется как `sources.name` в БД).
- `type` — тип источника (`habr`, `rss_generic`, `reddit`, ...).
- `enabled` — если `false`, источник пропускается.
- `filters` — **общие фильтры уровня ядра**: `min_rating`, `min_engagement`. Применяются в `pipeline.collect` после `fetch`.
- `params` — dict, специфичный для типа источника, валидируется внутри коннектора.

Файл читается при каждом `collect`. Несуществующие в БД источники добавляются автоматически (upsert по `name`).

---

## 8. Конфигурация окружения (`.env.example`)

```
# БД
DATABASE_URL=postgresql+asyncpg://user:pass@host:6432/trend_radar
PSQL_URL=postgresql://user:pass@host:6432/trend_radar   # чистый URL для psql

# LLM
OPENAI_API_KEY=sk-...
OPENAI_MODEL_SCORE=gpt-4o-mini
OPENAI_MODEL_DIGEST=gpt-4o
OPENAI_PRICE_PER_1K_INPUT=0.00015     # опционально, лог стоимости
OPENAI_PRICE_PER_1K_OUTPUT=0.0006

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_USER_ID=123456789

# Общее
TZ=Europe/Moscow
LOG_LEVEL=INFO
COLLECT_CRON=0 7 * * *          # ежедневно в 07:00
DIGEST_CRON=0 10 * * 1          # понедельник в 10:00

# Throttling (Этап 5.5)
HTTP_REQUESTS_PER_DOMAIN_PER_SEC=1
```

> `DATABASE_URL` — с драйвером `+asyncpg` для приложения. `PSQL_URL` — чистый, для ручных команд psql.

---

## 9. Pipeline (логика работы)

### Ежедневно (COLLECT_CRON):
1. `pipeline.collect` — читает `sources.yaml`, для каждого enabled-источника вызывает `fetch(since)`, **применяет общие `filters`**, складывает `RawPost` в `posts` (idempotent через UNIQUE).
2. `pipeline.score` — берёт посты без записи в `post_scores`, прогоняет через `llm.scorer`, пишет `PostScore` (включая `problem`/`opportunity`). Промпт включает `user_profile.md`.

### Еженедельно (DIGEST_CRON) и по команде `/digest`:
3. `pipeline.digest` — берёт посты за период (по умолчанию 7 дней) с `relevance_score >= 6`, **исключая уже отправленные (`delivery_log`)**. Группирует по категориям. `llm.digest_builder` собирает Markdown.
4. `pipeline.deliver` — отправляет Markdown в Telegram (разбивка на сообщения при >4096 символов). Пишет в `delivery_log`.

### Структура дайджеста (выход `digest_builder`):
```
🗓 Дайджест за 12–18 ноября

🔥 Тренды недели
— Тема X (упоминалась в 5 постах)
   • Заголовок [ссылка] — краткое саммари

😣 Боли и вопросы
— Заголовок [ссылка] — боль: <problem>

💡 Идеи для проектов
— Заголовок [ссылка] — возможность: <opportunity>

📦 Кейсы и MVP
— ...

📈 Высокововлечённые посты
— ...
```

---

## 10. LLM-промпты

- `config/prompts/user_profile.md` — профиль пользователя (системный аналитик / данные / MVP / автоматизация / SMB / стартапы).
- `config/prompts/score_post.md` — оценка одного поста. Вход: profile + post. Выход: JSON по схеме `PostScore` (включая `problem`/`opportunity`).
- `config/prompts/build_digest.md` — сборка дайджеста. Вход: profile + оценённые посты. Выход: Markdown.
- `docs/PROMPTS.md` — описание назначения и истории изменений промптов.

Все промпты версионируются в git.

---

## 11. Telegram-бот

Команды:
- `/digest` — дайджест за последние 7 дней.
- `/digest_today` — только новые (ещё не отправленные) посты за сегодня.
- `/status` — статистика: собрано / оценено / последний запуск.
- `/help` — список команд.

Доступ: только `TELEGRAM_USER_ID`. Работа в канале — во 2-й фазе (`chat_id` канала).
`bot/keyboards.py` — inline-клавиатуры (например, кнопка "Собрать дайджест").

---

## 12. Этапы разработки

> Каждый этап = ветка `stage/N-name`, после ручного теста — merge в `main`. Перед этапом прикрепить `ARCHITECTURE.md` и указать "Реализуй Этап N".

---

### ✅ Этап 0. Habr MVP (ВЫПОЛНЕНО)

Полный рабочий цикл на одном источнике — Habr.

**Что сделано:**
- Скелет проекта (раздел 5), Docker, docker-compose, settings.
- БД: `models.py` + `init.sql` (все таблицы раздела 4).
- `sources/base.py`, `sources/registry.py`, `sources/habr.py` (RSS через feedparser + httpx).
- `pipeline`: collect / score / digest / deliver.
- `llm`: client / scorer / digest_builder.
- `bot`: bot / handlers / keyboards (`/digest`, `/digest_today`, `/status`, `/help`).
- `scheduler.py` с COLLECT_CRON и DIGEST_CRON.
- Тесты: `test_sources_habr.py`, `test_scorer.py`.

**Статус контрактов:** базовые версии `RawPost`/`PostScore` без полей `engagement`/`problem`/`opportunity`.

---

### ✅ Этап 1. Апгрейд схемы под "идеи для проектов"

**Цель:** подготовить БД и контракты к поиску идей до подключения новых источников.

**Делаем:**
- `posts`: добавить `engagement INTEGER NULL`.
- `post_scores`: добавить `problem TEXT NULL`, `opportunity TEXT NULL`.
- Обновить `db/models.py` и `db/init.sql` (см. SQL ниже).
- Обновить `schemas/post.py` (`RawPost.engagement`) и `schemas/score.py` (`problem`, `opportunity`).
- Обновить `config/prompts/score_post.md`: LLM должна извлекать `problem` (боль) и `opportunity` (потенциал продукта). Для нерелевантных постов — `null`.
- Обновить `llm/digest_builder.py` и `build_digest.md`: новая секция "💡 Идеи для проектов".

**SQL к ручному выполнению:**
```sql
ALTER TABLE posts ADD COLUMN IF NOT EXISTS engagement INTEGER;
ALTER TABLE post_scores ADD COLUMN IF NOT EXISTS problem TEXT;
ALTER TABLE post_scores ADD COLUMN IF NOT EXISTS opportunity TEXT;
```

**Как проверить:**
```bash
psql $PSQL_URL -f src/db/init.sql   # либо ALTER выше
psql $PSQL_URL -c "\d posts"        # видим engagement
psql $PSQL_URL -c "\d post_scores"  # видим problem, opportunity
docker compose run --rm app python -m src.main score
psql $PSQL_URL -c "SELECT problem, opportunity FROM post_scores WHERE problem IS NOT NULL LIMIT 5;"
```

---

### Этап 2. Общие фильтры в ядре

**Цель:** унифицировать фильтрацию, убрать habr-специфику из коннекторов.

**Делаем:**
- Перенести логику `min_rating` из `sources/habr.py` в `pipeline/collect.py`.
- Добавить поддержку блока `filters` в `sources.yaml` (`min_rating`, `min_engagement`).
- В `collect`: после `fetch` отфильтровать посты по `filters`; если метрика `None` — фильтр пропускается.
- Обновить `config/sources.yaml` (перенести `min_rating` в `filters`).

**Как проверить:**
```bash
docker compose run --rm app python -m src.main collect
# В логах видно, сколько постов отсеяно фильтрами по каждому источнику.
psql $PSQL_URL -c "SELECT source_id, count(*) FROM posts GROUP BY source_id;"
```

---

### Этап 3. Per-domain throttler

**Цель:** защита от банов при масштабировании на много площадок.

**Делаем:**
- `src/utils/throttle.py` — async-лимитер запросов на домен (semaphore + минимальный интервал), настраивается через `HTTP_REQUESTS_PER_DOMAIN_PER_SEC`.
- Единый httpx-клиент с общим User-Agent, таймаутами, ретраями (`utils/retry.py`).
- Все источники используют этот клиент (обновить `habr.py`).

**Как проверить:**
```bash
# Юнит-тест: серия запросов к одному домену растягивается по времени.
docker compose run --rm app pytest tests/test_throttle.py -v
docker compose run --rm app python -m src.main collect   # без ошибок
```

---

### Этап 4. Универсальный источник `rss_generic` (быстрая победа)

**Цель:** одним коннектором подключить десятки площадок (HN, IndieHackers, dev.to, блоги).

**Делаем:**
- `src/sources/rss_generic.py` — читает произвольный RSS/Atom по `params.url`.
  - `external_id` — из `entry.id` или хэш ссылки.
  - `engagement` — если фид отдаёт очки/комменты (например hnrss), иначе `None`.
  - `content` — из `summary`/`content`, чистится от HTML.
- Зарегистрировать `rss_generic` в `registry.py`.
- В `sources.yaml` добавить и включить: `hackernews`, `indiehackers`.
- Тест `tests/test_sources_rss_generic.py` на локальном .xml-фикстуре.

**Как проверить:**
```bash
docker compose run --rm app python -m src.main collect
psql $PSQL_URL -c "SELECT s.name, count(*) FROM posts p JOIN sources s ON s.id=p.source_id GROUP BY s.name;"
# Ожидаем посты по hackernews и indiehackers.
```

---

### Этап 5. Reddit (главный источник болей и идей)

**Цель:** собирать боли аудитории и запросы "I wish there was a tool for...".

**Делаем:**
- Добавить в `requirements.txt`: `asyncpraw`.
- `src/sources/reddit.py` — сбор постов из сабреддитов (`params.subreddits`, `params.listing: new|top`, `params.time_filter`).
  - `engagement` = `score` (upvotes).
- Регистрация в `registry.py`.
- В `.env.example`: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`.
- В `sources.yaml`: `r/SaaS`, `r/startups`, `r/Entrepreneur`, `r/SideProject`.

**Как проверить:**
```bash
docker compose run --rm app python -m src.main collect
psql $PSQL_URL -c "SELECT count(*) FROM posts p JOIN sources s ON s.id=p.source_id WHERE s.type='reddit';"
```

---

````markdown
### Этап 6. Product Hunt (продолжение)

**Цель:** видеть, что запускают прямо сейчас.

**Делаем:**
- Добавить в `requirements.txt`: ничего нового (используем httpx + GraphQL).
- `src/sources/producthunt.py` — через официальный GraphQL API (`params.topic`, `params.limit`).
  - `engagement` = `votesCount`.
  - `external_id` — id продукта из API.
- Регистрация в `registry.py`.
- Токен в `.env.example`: `PRODUCTHUNT_TOKEN`.
- В `sources.yaml`: топики `developer-tools`, `productivity`, `artificial-intelligence`.

**Как проверить:**
```bash
docker compose run --rm app python -m src.main collect
psql $PSQL_URL -c "SELECT count(*) FROM posts p JOIN sources s ON s.id=p.source_id WHERE s.type='producthunt';"
```

---

### Этап 7. VK

**Цель:** подключить русскоязычные паблики (стартапы, IT-бизнес).

**Делаем:**
- Добавить в `requirements.txt`: `vk_api`.
- `src/sources/vk.py` — сбор постов со стен пабликов (`params.groups`).
  - `engagement` = likes + comments + reposts.
  - `external_id` = `{owner_id}_{post_id}`.
- Регистрация в `registry.py`.
- Токен в `.env.example`: `VK_ACCESS_TOKEN`.
- В `sources.yaml`: 2-3 профильных паблика.

**Как проверить:**
```bash
docker compose run --rm app python -m src.main collect
psql $PSQL_URL -c "SELECT count(*) FROM posts p JOIN sources s ON s.id=p.source_id WHERE s.type='vk';"
```

---

### Этап 8. Telegram-каналы

**Цель:** собирать посты из тематических TG-каналов.

**Делаем:**
- Добавить в `requirements.txt`: `telethon`.
- `src/sources/telegram.py` — чтение каналов через Telethon (`params.channels`).
  - Сессия хранится в Docker volume (`/data/telethon.session`).
  - `engagement` = views (если доступны).
  - `external_id` = `{channel}_{message_id}`.
- Регистрация в `registry.py`.
- В `.env.example`: `TG_API_ID`, `TG_API_HASH`.
- В `docker-compose.yml`: volume для сессии.
- В `sources.yaml`: список каналов.

**⚠️ Первый запуск** требует интерактивной авторизации (ввод кода). Сделать разовый скрипт `python -m src.main tg_login`.

**Как проверить:**
```bash
docker compose run --rm app python -m src.main tg_login   # разовая авторизация
docker compose run --rm app python -m src.main collect
psql $PSQL_URL -c "SELECT count(*) FROM posts p JOIN sources s ON s.id=p.source_id WHERE s.type='telegram';"
```

---

### Этап 9. YouTube

**Цель:** собирать идеи из видео (описания + транскрипты).

**Делаем:**
- Добавить в `requirements.txt`: `google-api-python-client`, `youtube-transcript-api`.
- `src/sources/youtube.py` — новые видео с каналов через YouTube Data API (`params.channel_ids`).
  - `content` = описание + транскрипт (если доступен, иначе только описание + `WARNING`).
  - `engagement` = viewCount.
  - `external_id` = videoId.
- Регистрация в `registry.py`.
- Токен в `.env.example`: `YOUTUBE_API_KEY`.
- В `sources.yaml`: список каналов.

**Как проверить:**
```bash
docker compose run --rm app python -m src.main collect
psql $PSQL_URL -c "SELECT count(*) FROM posts p JOIN sources s ON s.id=p.source_id WHERE s.type='youtube';"
```

---

### Этап 10+. Улучшения (по желанию)

- **Дедупликация похожих постов между источниками** (эмбеддинги + cosine) — одна тема с HN и Reddit не дублируется в дайджесте.
- **Тренд-аналитика:** подсчёт частоты тем, динамика по неделям.
- **"Pain mining" фильтр:** отдельный prompt-проход для постов-запросов ("I wish there was...", "does anyone know a tool...") — ключевой сигнал для идей.
- **Веб-UI** для просмотра истории и тюнинга профиля.
- **Работа в Telegram-канале** (broadcast вместо личного).
- **Кэш LLM-ответов** по хэшу поста — экономия токенов на повторных запусках.

---

## 13. Приоритет источников (обоснование порядка этапов)

Порядок этапов выбран под главную цель — **поиск идей и болей**, а не сбор новостей:

| Источник | Что даёт | Сложность | Этап |
|---|---|---|---|
| Habr | тренды, туториалы | — | 0 (готово) |
| rss_generic (HN, IndieHackers) | боли, реальные MVP, "Show HN" | легко (RSS) | 4 |
| Reddit | боли аудитории, запросы на инструменты | средне (API) | 5 |
| Product Hunt | что запускают сейчас | средне (API) | 6 |
| VK | русскоязычные паблики | средне | 7 |
| Telegram | тематические каналы | средне | 8 |
| YouTube | идеи из видео | сложнее | 9 |

**Логика:** сначала `rss_generic` (одним коннектором — десятки площадок), затем Reddit (главный источник болей), потом остальное по убыванию ценности для целей проекта.

---

## 14. Правила работы Claude в чате

При запросе на реализацию этапа:
1. **Не выдумывать структуру** — следовать разделу 5.
2. **Не менять контракты** из раздела 6 без явного запроса.
3. При изменении `models.py` — обязательно синхронизировать `db/init.sql` (добавить ALTER/CREATE) и указать в ответе, какой SQL выполнить вручную.
4. **Каждый ответ заканчивать блоком "Как проверить"** — конкретные команды.
5. **Если нужны изменения архитектуры** — сначала предложить правки в `ARCHITECTURE.md`, потом код.
6. Код — типизированный (mypy-friendly), async где имеет смысл (HTTP, БД, LLM).

---

## 15. Свобода реализации

Claude (или другой исполнитель) **НЕ должен** спрашивать разрешения на технические детали. Принимает решение сам, фиксирует в коде или коротким комментарием. К таким деталям относятся:

- Парсинг HTML: библиотека (BeautifulSoup / lxml), селекторы, очистка тегов.
- HTTP-клиент: таймауты, User-Agent, лимиты параллелизма (в рамках throttler).
- Формирование `external_id` — любое стабильное значение, уникальное в рамках источника.
- Состав служебных полей внутри `raw_json` / `raw`.
- Как именно маппится `engagement` для конкретного источника (очки/лайки/просмотры) — выбрать разумно.
- Sync vs async внутри модуля, если контракт раздела 6 не диктует обратное.
- Обработка таймзон — всё приводим к UTC.
- Graceful degradation: если опциональные данные не извлекаются — `None` + лог `WARNING`, пайплайн не падает.
- Внутренние вспомогательные функции, приватные классы, структура модуля.

**Спрашивать обязательно** только в случаях:
1. Нестыковка между разделами `ARCHITECTURE.md`.
2. Пробел или противоречие в контрактах раздела 6.
3. Бизнес-решение: что считать релевантным, какие пороги фильтров, какие источники приоритетны.
4. Изменение схемы БД (раздел 4) или добавление/удаление полей в контрактах.
5. Добавление новой внешней зависимости, не упомянутой в `requirements.txt` соответствующего этапа.

Во всех остальных случаях — делаем и идём дальше. Если выбор неочевиден — короткий комментарий в коде с обоснованием (1 строка).

---

## 16. Быстрый старт для нового разработчика

```bash
# 1. Клонируем и настраиваем окружение
cp .env.example .env          # заполнить секреты (OPENAI, TELEGRAM, DATABASE_URL)

# 2. Поднимаем контейнер
docker compose build

# 3. Создаём схему БД (разово)
psql $PSQL_URL -f src/db/init.sql

# 4. Полный цикл вручную
docker compose run --rm app python -m src.main collect   # сбор
docker compose run --rm app python -m src.main score     # оценка LLM
docker compose run --rm app python -m src.main digest --days 7   # дайджест
docker compose run --rm app python -m src.main deliver   # отправка в TG

# 5. Автономный режим (бот + scheduler)
docker compose up -d
docker compose logs -f app
```

**Что где искать:**
- Добавить источник → новый файл в `src/sources/` + регистрация в `registry.py` + секция в `config/sources.yaml`.
- Изменить логику оценки → `config/prompts/score_post.md` + `src/llm/scorer.py`.
- Изменить вид дайджеста → `config/prompts/build_digest.md` + `src/llm/digest_builder.py`.
- Изменить расписание → `COLLECT_CRON` / `DIGEST_CRON` в `.env`.
- Изменить схему БД → `src/db/models.py` + `src/db/init.sql` (синхронно!).

---

**Конец документа.**
````



Ты — senior Python-разработчик проекта Trend Radar. К сообщению прикреплён docs/ARCHITECTURE.md — это единый источник правды. Строго следуй ему.

ПРАВИЛА РАБОТЫ (обязательны для всех ответов):
1. Не выдумывай структуру проекта — следуй разделу 5 ARCHITECTURE.md.
2. Не меняй контракты (раздел 6) без явного запроса.
3. Код типизированный (mypy-friendly), async где нужно (HTTP, БД, LLM).
4. ЕСЛИ НУЖНО ИЗМЕНИТЬ существующую функцию/метод/класс — присылай её ЦЕЛИКОМ в переписанном виде, а не диффом. Обязательно указывай ТОЧНОЕ место: путь к файлу и имя функции/класса, например: «Файл: src/pipeline/collect.py → функция collect_all() — заменить целиком на:».
5. Если меняешь src/db/models.py — синхронно обновляй src/db/init.sql и в конце ответа отдельным блоком укажи SQL для ручного выполнения через psql.
6. Каждый ответ заканчивай блоком «✅ Как проверить» с конкретными командами.
7. Если обнаружишь противоречие в архитектуре или контрактах — сначала спроси, не пиши код наугад.
8. Новые внешние зависимости — явно указывай, что добавить в requirements.txt.

Формат ответа:
- Кратко: что делаешь и почему.
- Файлы: для каждого — полный путь + полное содержимое (новые файлы) ИЛИ переписанная целиком функция с указанием места (правки).
- SQL (если менялась схема).
- ✅ Как проверить.
```

