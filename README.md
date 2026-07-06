# Trend Radar

Trend Radar - сервис для регулярного поиска трендов, болей аудитории и идей для проектов. Он собирает публикации из разных площадок, сохраняет их в PostgreSQL, оценивает через LLM по вашему профилю интересов и отправляет итоговый дайджест в Telegram.

Проект заточен под ниши: данные, системный анализ, MVP, автоматизация, SaaS, стартапы, инструменты для разработчиков и продуктовые идеи.

## Что Уже Умеет

- Собирать посты из Habr, RSS/Atom, Reddit, Product Hunt, VK, Telegram-каналов и YouTube.
- Применять общие фильтры по рейтингу и вовлеченности на уровне ядра.
- Защищаться от лишних HTTP-запросов через per-domain throttling.
- Хранить посты, оценки, дайджесты и историю доставок в PostgreSQL.
- Оценивать посты через OpenAI: релевантность, категория, краткое резюме, боль, продуктовая возможность и темы.
- Собирать дайджест через LLM и отправлять его в Telegram.
- Работать в ручном CLI-режиме или автономно через APScheduler.
- Управляться из Telegram-бота: дайджест, дайджест за сегодня, статус, ручной collect+score.

## Как Это Работает

```text
config/sources.yaml
        |
        v
Sources -> collect -> PostgreSQL -> score -> post_scores -> digest -> digests -> deliver -> Telegram
             ^             |          ^                       ^
             |             |          |                       |
             |             v          |                       |
             +------ common filters   OpenAI                  config/prompts
```

Основной пайплайн состоит из четырех независимых шагов:

1. `collect` - читает активные источники из `config/sources.yaml`, забирает новые посты и сохраняет их без дублей.
2. `score` - берет неоцененные посты и отправляет их в OpenAI для структурированной оценки.
3. `digest` - выбирает лучшие посты за период и формирует Markdown-дайджест.
4. `deliver` - отправляет сохраненный дайджест в Telegram и отмечает посты как доставленные.

Каждый шаг можно запускать отдельно, поэтому пайплайн удобно отлаживать по частям.

## Архитектура Проекта

Подробная архитектура описана в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Коротко:

```text
trend_researcher/
├── config/
│   ├── sources.yaml          # список источников и фильтры
│   └── prompts/              # профиль пользователя и LLM-промпты
├── docs/
│   ├── ARCHITECTURE.md       # архитектурный источник правды
│   └── PROMPTS.md            # промпты этапов разработки
├── src/
│   ├── main.py               # CLI и entrypoint контейнера
│   ├── scheduler.py          # APScheduler jobs
│   ├── settings.py           # переменные окружения
│   ├── db/                   # SQLAlchemy, repository, init.sql
│   ├── schemas/              # Pydantic-контракты
│   ├── sources/              # коннекторы источников
│   ├── llm/                  # OpenAI client, scorer, digest builder
│   ├── pipeline/             # collect, score, digest, deliver
│   ├── bot/                  # aiogram-бот
│   └── utils/                # HTTP, retry, throttle, logging
├── tests/                    # pytest-тесты источников и утилит
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### Главные Контракты

Все источники возвращают `RawPost`:

```text
source_name, external_id, url, title, author, content,
published_at, rating, engagement, raw
```

LLM возвращает `PostScore`:

```text
relevance_score, category, summary, problem, opportunity, topics
```

Контракты лежат в `src/schemas/`. Источники не пишут напрямую в БД и не вызывают LLM; они только приводят внешние данные к общей модели.

## Поддерживаемые Источники

| Type | Файл | Что собирает | Основная метрика |
|---|---|---|---|
| `habr` | `src/sources/habr.py` | статьи из RSS хабов Habr | `rating`, если доступен |
| `rss_generic` | `src/sources/rss_generic.py` | любой RSS/Atom | `engagement`, если фид отдает метрики |
| `reddit` | `src/sources/reddit.py` | посты из сабреддитов | upvotes |
| `producthunt` | `src/sources/producthunt.py` | запуски по топикам Product Hunt | votes |
| `vk` | `src/sources/vk.py` | посты VK-пабликов | likes + comments + reposts |
| `telegram` | `src/sources/telegram.py` | сообщения Telegram-каналов | views |
| `youtube` | `src/sources/youtube.py` | новые видео + описания + транскрипты | viewCount |

Источники включаются и настраиваются в [config/sources.yaml](config/sources.yaml).

## Что Потребуется

### Обязательное

- Python 3.11.
- PostgreSQL 15+ или совместимая версия.
- OpenAI API key.
- Telegram bot token.
- Telegram user id, которому бот будет отправлять дайджесты.

### Для Дополнительных Источников

| Источник | Что нужно |
|---|---|
| Reddit | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` |
| Product Hunt | `PRODUCTHUNT_TOKEN` |
| VK | `VK_ACCESS_TOKEN` |
| Telegram-каналы | `TG_API_ID`, `TG_API_HASH`, интерактивный `tg_login` |
| YouTube | `YOUTUBE_API_KEY` |

Если ключа нет, соответствующий источник мягко вернет пустой список и запишет ошибку в лог. Можно временно выключить источник через `enabled: false`.

## Переменные Окружения

Скопируйте пример:

```bash
cp .env.example .env
```

Заполните `.env`:

| Переменная | Обязательна | Назначение |
|---|---:|---|
| `DATABASE_URL` | да | async URL для SQLAlchemy, например `postgresql+asyncpg://user:pass@host:5432/db` |
| `OPENAI_API_KEY` | да | ключ OpenAI API |
| `OPENAI_MODEL_SCORE` | нет | модель оценки постов, по умолчанию `gpt-4o-mini` |
| `OPENAI_MODEL_DIGEST` | нет | модель сборки дайджеста, по умолчанию `gpt-4o` |
| `TELEGRAM_BOT_TOKEN` | да | токен бота из BotFather |
| `TELEGRAM_USER_ID` | да | Telegram user id получателя |
| `TZ` | нет | таймзона scheduler, например `Europe/Moscow` |
| `LOG_LEVEL` | нет | уровень логов |
| `COLLECT_CRON` | нет | cron для ежедневного `collect + score` |
| `DIGEST_CRON` | нет | cron для еженедельного `digest + deliver` |
| `HTTP_REQUESTS_PER_DOMAIN_PER_SEC` | нет | лимит HTTP-запросов на домен |
| `REDDIT_CLIENT_ID` | для Reddit | id Reddit app |
| `REDDIT_CLIENT_SECRET` | для Reddit | secret Reddit app |
| `REDDIT_USER_AGENT` | для Reddit | user-agent приложения |
| `PRODUCTHUNT_TOKEN` | для Product Hunt | bearer token Product Hunt API |
| `VK_ACCESS_TOKEN` | для VK | access token VK API |
| `TG_API_ID` | для Telegram-каналов | Telegram API id |
| `TG_API_HASH` | для Telegram-каналов | Telegram API hash |
| `YOUTUBE_API_KEY` | для YouTube | ключ YouTube Data API |

Для ручной инициализации БД удобно завести отдельную переменную `PSQL_URL` без `+asyncpg`, например:

```bash
export PSQL_URL=postgresql://user:pass@host:5432/trend_radar
```

## Настройка Базы Данных

Проект не поднимает PostgreSQL в `docker-compose.yml`; ожидается внешняя или уже существующая БД.

1. Создайте базу.
2. Примените DDL:

```bash
psql "$PSQL_URL" -f src/db/init.sql
```

Если вы используете `DATABASE_URL` из `.env`, помните: для `psql` нужен обычный URL без драйвера `+asyncpg`.

## Настройка Источников

Источники описываются в YAML:

```yaml
sources:
  - name: reddit_saas
    type: reddit
    enabled: true
    filters:
      min_engagement: 20
    params:
      subreddits: [ SaaS ]
      listing: top
      time_filter: week
      limit: 50
```

### Общие Поля

| Поле | Назначение |
|---|---|
| `name` | уникальное имя источника в БД |
| `type` | тип коннектора: `habr`, `reddit`, `youtube` и т.д. |
| `enabled` | включает или выключает источник |
| `filters` | общие фильтры ядра |
| `params` | параметры конкретного источника |

### Общие Фильтры

```yaml
filters:
  min_rating: 5
  min_engagement: 20
```

Если у поста нет `rating`, фильтр `min_rating` для него пропускается. Если нет `engagement`, фильтр `min_engagement` тоже пропускается. Фильтрация живет в `src/pipeline/collect.py`, а не в коннекторах.

### Примеры Параметров Источников

```yaml
# Habr
params:
  hub: python

# RSS
params:
  url: https://hnrss.org/newest?points=100

# Reddit
params:
  subreddits: [ SaaS, startups ]
  listing: top
  time_filter: week
  limit: 50

# Product Hunt
params:
  topic: developer-tools
  limit: 30

# VK
params:
  groups: [ tproger, proglib, habr ]
  limit: 50

# Telegram
params:
  channels: [ startupsi, addmeto ]
  limit: 50

# YouTube
params:
  channel_ids:
    - UCcefcZRL2oaA_uBNeo5UOWg
  limit: 20
```

## Настройка Промптов

Промпты лежат в `config/prompts/`:

- `user_profile.md` - ваш профиль интересов. Это главный файл для настройки вкуса дайджеста.
- `score_post.md` - правила оценки отдельного поста.
- `build_digest.md` - правила сборки итогового дайджеста.

Обычно сначала правят `user_profile.md`: какие темы интересны, какие посты считать шумом, какие идеи особенно ценны.

## Установка И Запуск Локально

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`, примените схему БД, затем запускайте команды:

```bash
.venv/bin/python -m src.main collect
.venv/bin/python -m src.main score --limit 50
.venv/bin/python -m src.main digest --days 7 --min-relevance 6 --manual
.venv/bin/python -m src.main deliver --digest-id 1
```

Для автономного режима:

```bash
.venv/bin/python -m src.main run
```

Локальный запуск Telegram-источника использует путь `/data/telethon.session`. Если вы запускаете не через Docker, убедитесь, что каталог `/data` существует и доступен на запись, либо используйте Docker-режим ниже.

## Запуск Через Docker Compose

Сборка и запуск сервиса:

```bash
docker compose up -d --build
docker compose logs -f app
```

Контейнер запускает:

```bash
python -m src.main run
```

То есть одновременно стартуют Telegram-бот и scheduler.

Ручные команды внутри контейнера:

```bash
docker compose run --rm app python -m src.main collect
docker compose run --rm app python -m src.main score --limit 50
docker compose run --rm app python -m src.main digest --days 7 --manual
docker compose run --rm app python -m src.main deliver --digest-id 1
```

Для Telethon-сессии в `docker-compose.yml` подключен volume `trend-radar-data:/data`.

## Авторизация Telegram-Каналов

Для чтения Telegram-каналов Telethon должен один раз создать пользовательскую сессию.

1. Заполните:

```env
TG_API_ID=...
TG_API_HASH=...
```

2. Запустите интерактивный логин:

```bash
docker compose run --rm app python -m src.main tg_login
```

Telethon попросит телефон, код и, если включена двухфакторная защита, пароль. После успешного входа файл сессии сохранится в Docker volume `/data/telethon.session`.

После этого источник `type: telegram` сможет читать каналы, к которым у аккаунта есть доступ.

## CLI Команды

| Команда | Что делает |
|---|---|
| `python -m src.main run` | запускает bot + scheduler |
| `python -m src.main collect` | собирает посты из активных источников |
| `python -m src.main score --limit 50` | оценивает неоцененные посты |
| `python -m src.main digest --days 7 --min-relevance 6 --manual` | создает дайджест в БД |
| `python -m src.main deliver --digest-id 1` | отправляет существующий дайджест в Telegram |
| `python -m src.main bot` | запускает только Telegram-бота |
| `python -m src.main tg_login` | создает Telethon-сессию для чтения каналов |

## Telegram-Бот

Бот доступен только пользователю с id `TELEGRAM_USER_ID`.

Команды:

| Команда | Что делает |
|---|---|
| `/start` | показывает основную клавиатуру |
| `/help` | показывает справку |
| `/status` | показывает статистику базы |
| `/digest` | собирает и отправляет дайджест за 7 дней |
| `/digest_today` | собирает и отправляет дайджест за сутки |
| `/run_collect` | вручную запускает `collect + score` |

## Scheduler

Scheduler создается в `src/scheduler.py` и использует cron-выражения из `.env`:

```env
COLLECT_CRON=0 7 * * *
DIGEST_CRON=0 10 * * 1
TZ=Europe/Moscow
```

По умолчанию:

- каждый день в 07:00: `collect -> score`;
- каждый понедельник в 10:00: `digest -> deliver`.

## Данные В PostgreSQL

Основные таблицы:

| Таблица | Назначение |
|---|---|
| `sources` | справочник источников |
| `posts` | собранные сырые посты |
| `post_scores` | LLM-оценки |
| `digests` | сохраненные дайджесты |
| `digest_posts` | связь дайджеста и постов |
| `delivery_log` | история отправленных постов |

Дубли предотвращаются ограничением `UNIQUE(source_id, external_id)`.

## Разработка

Установка:

```bash
.venv/bin/pip install -r requirements.txt
```

Тесты:

```bash
.venv/bin/pytest
```

Проверить только источники:

```bash
.venv/bin/pytest tests/test_sources_*.py
```

Тесты источников не ходят в реальную сеть: внешние API замоканы.

## Как Добавить Новый Источник

1. Создайте файл `src/sources/my_source.py`.
2. Реализуйте класс от `BaseSource`.
3. Верните список `RawPost` из метода `fetch(self, since)`.
4. Зарегистрируйте тип в `src/sources/registry.py`.
5. Добавьте секцию в `config/sources.yaml`.
6. Добавьте тест в `tests/test_sources_my_source.py`.

Минимальный скелет:

```python
from datetime import datetime
from typing import Any

from src.schemas.post import RawPost
from src.sources.base import BaseSource


class MySource(BaseSource):
    type = "my_source"

    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self.name = name
        self.params = params

    async def fetch(self, since: datetime) -> list[RawPost]:
        return []
```

Ядро пайплайна менять обычно не нужно.

## Практический Сценарий Первого Запуска

1. Заполнить `.env`.
2. Отключить источники, для которых пока нет ключей: `enabled: false`.
3. Применить `src/db/init.sql`.
4. Запустить `collect`.
5. Проверить, что в логах есть `collect.done`.
6. Запустить `score --limit 10`.
7. Запустить `digest --days 7 --manual`.
8. Отправить дайджест через `deliver --digest-id <id>`.
9. Если все хорошо, запустить `docker compose up -d --build`.

## Частые Проблемы

### `psql` не принимает `DATABASE_URL`

`DATABASE_URL` содержит драйвер `postgresql+asyncpg://`, который нужен приложению. Для `psql` используйте URL вида `postgresql://...`.

### Telegram-каналы возвращают пусто

Проверьте, что выполнен `tg_login`, сессия сохранена в `/data/telethon.session`, аккаунт имеет доступ к каналам, а `TG_API_ID` и `TG_API_HASH` заполнены.

### Reddit, VK, Product Hunt или YouTube возвращают пусто

Проверьте ключи в `.env` и включенность источника в `config/sources.yaml`. Источник без ключа не падает, а возвращает пустой список.

### CLI `--help` падает из-за Click/Typer

В `requirements.txt` закреплен `click<8.2`, потому что текущий `typer==0.13.1` несовместим с более свежими версиями Click для rich-help.

### Дайджест не создается

Возможные причины:

- нет собранных постов за период;
- посты еще не оценены;
- `min_relevance` слишком высокий;
- посты уже были доставлены и исключаются через `exclude_delivered=True`.

## Безопасность

- Не коммитьте `.env`.
- Используйте отдельные API tokens для проекта.
- Telegram-бот ограничивает доступ по `TELEGRAM_USER_ID`.
- Для Telethon используется пользовательская сессия; храните volume `/data` как секретный артефакт.

## Текущий Статус

Реализированы этапы 1-9:

- расширенная схема под идеи;
- общие фильтры;
- throttling;
- RSS;
- Reddit;
- Product Hunt;
- VK;
- Telegram-каналы;
- YouTube.

Следующий крупный блок из архитектуры - улучшения уровня 10+: дедупликация похожих постов между источниками, эмбеддинги и более умная сборка дайджеста.
