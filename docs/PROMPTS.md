# Промпты для реализации этапов (Claude Opus)

Ниже — готовые промпты. В начало каждого чата прикрепляй `docs/ARCHITECTURE.md`, затем вставляй нужный промпт.

---

## 📌 Универсальная шапка (входит в каждый промпт)

```
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

> Дальше в каждом этапе — только тело задачи. Шапку добавляй всегда.

---

## Этап 1. Апгрейд схемы под «идеи для проектов»

```
Реализуй ЭТАП 1 из ARCHITECTURE.md (раздел 12).

Контекст: Этап 0 (Habr MVP) готов. Сейчас готовим БД и контракты к поиску идей ДО подключения новых источников.

Задача:
1. src/db/models.py — добавь поля:
   - в модель posts: engagement: Mapped[int | None]
   - в модель post_scores: problem: Mapped[str | None], opportunity: Mapped[str | None]
   (существующие функции/классы моделей присылай целиком с указанием места).
2. src/db/init.sql — синхронно добавь эти колонки (CREATE TABLE обновить + отдельный ALTER-блок для уже существующей БД).
3. src/schemas/post.py — добавь engagement: int | None = None в RawPost.
4. src/schemas/score.py — добавь problem: str | None = None и opportunity: str | None = None в PostScore.
5. config/prompts/score_post.md — обнови так, чтобы LLM извлекала problem (какую боль описывает пост) и opportunity (можно ли сделать продукт). Для нерелевантных постов — null. JSON-выход должен строго соответствовать обновлённой схеме PostScore.
6. src/llm/scorer.py — если парсинг/валидация ответа завязаны на схему, обнови (присылай изменённые функции целиком с указанием места).
7. src/llm/digest_builder.py и config/prompts/build_digest.md — добавь секцию «💡 Идеи для проектов» (использует opportunity) и покажи problem в секции «Боли и вопросы» (см. раздел 9 ARCHITECTURE.md).

Не трогай источники и pipeline.collect на этом этапе.
```

---

## Этап 2. Общие фильтры в ядре

```
Реализуй ЭТАП 2 из ARCHITECTURE.md.

Контекст: Этап 1 готов (схема расширена). Сейчас выносим фильтрацию из коннекторов в ядро.

Задача:
1. Введи поддержку блока filters в config/sources.yaml (min_rating, min_engagement) — см. раздел 7 ARCHITECTURE.md. Обнови сам config/sources.yaml: перенеси min_rating из params в filters у habr-источников.
2. src/pipeline/collect.py — после вызова fetch() применяй общие фильтры к списку RawPost:
   - если у поста rating is None — фильтр min_rating пропускается;
   - если engagement is None — фильтр min_engagement пропускается;
   - логируй, сколько постов отсеяно по каждому источнику (structlog).
   Присылай изменённые функции целиком с указанием места (например: «Файл: src/pipeline/collect.py → функция collect_all() — заменить целиком на:»).
3. src/sources/habr.py — УБЕРИ из коннектора логику min_rating (теперь это делает ядро). Присылай изменённые методы целиком с указанием места.
4. Если для чтения filters из YAML нужна вспомогательная функция/модель — добавь, но не меняй контракт BaseSource (раздел 6).

Контракты раздела 6 не меняем.
```

---

## Этап 3. Per-domain throttler

```
Реализуй ЭТАП 3 из ARCHITECTURE.md.

Контекст: Этапы 1-2 готовы. Готовим защиту от банов перед подключением множества источников.

Задача:
1. Создай src/utils/throttle.py — async per-domain лимитер (semaphore + минимальный интервал между запросами к одному домену). Настраивается через переменную HTTP_REQUESTS_PER_DOMAIN_PER_SEC.
2. Обнови src/settings.py — добавь поле http_requests_per_domain_per_sec (читается из .env, дефолт 1). Присылай изменённый класс настроек целиком с указанием места.
3. Обнови .env.example — добавь HTTP_REQUESTS_PER_DOMAIN_PER_SEC=1.
4. Сделай единый httpx AsyncClient (общий User-Agent, таймауты) с интеграцией throttler и ретраев из src/utils/retry.py. Если уместно — размести фабрику клиента в src/utils/ (укажи файл).
5. src/sources/habr.py — переведи на использование этого клиента/throttler. Присылай изменённые методы целиком с указанием места.
6. Добавь tests/test_throttle.py — тест, что серия запросов к одному домену растягивается во времени согласно лимиту.

Новые зависимости (если нужны) — укажи для requirements.txt. Контракты раздела 6 не меняем.
```

---

## Этап 4. Универсальный источник `rss_generic`

```
Реализуй ЭТАП 4 из ARCHITECTURE.md.

Контекст: Этапы 1-3 готовы (расширенная схема, общие фильтры, throttler). Подключаем универсальный RSS-коннектор — одним классом десятки площадок.

Задача:
1. Создай src/sources/rss_generic.py — класс, реализующий BaseSource (type = "rss_generic"). Читает произвольный RSS/Atom по params.url через feedparser + общий httpx-клиент из Этапа 3.
   - external_id: из entry.id, иначе стабильный хэш ссылки;
   - published_at: приводить к UTC;
   - engagement: если фид отдаёт очки/комменты (например hnrss) — парсить, иначе None;
   - content: из summary/content, чистить от HTML;
   - все ошибки парсинга отдельной записи — WARNING + пропуск записи, не падать.
2. src/sources/registry.py — зарегистрируй "rss_generic". Присылай изменённую фабричную функцию целиком с указанием места.
3. config/sources.yaml — добавь и включи (enabled: true) источники hackernews (https://hnrss.org/newest?points=100, filters.min_engagement: 100) и indiehackers (https://www.indiehackers.com/rss).
4. tests/test_sources_rss_generic.py — тест на локальной .xml-фикстуре (без сети): проверь парсинг, external_id, UTC, engagement.

Контракты раздела 6 не меняем. Общие фильтры уже в ядре (Этап 2) — в коннекторе фильтрацию НЕ дублируй.
```

---

## Этап 5. Reddit

```
Реализуй ЭТАП 5 из ARCHITECTURE.md.

Контекст: Этапы 1-4 готовы, rss_generic работает. Reddit — главный источник болей и запросов на инструменты.

Задача:
1. Добавь в requirements.txt: asyncpraw (укажи явно).
2. Создай src/sources/reddit.py — класс BaseSource (type = "reddit"). Параметры из params: subreddits (list), listing (new|top), time_filter (для top).
   - engagement = score (upvotes);
   - external_id = id поста Reddit;
   - content = selftext (для текстовых постов), иначе title + url;
   - published_at → UTC;
   - авторизация через REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT из настроек;
   - ошибки по отдельному сабреддиту — ERROR + продолжаем.
3. src/settings.py — добавь поля для Reddit-креденшелов. Присылай класс настроек целиком с указанием места.
4. .env.example — добавь REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT.
5. src/sources/registry.py — зарегистрируй "reddit" (фабрику присылай целиком с указанием места).
6. config/sources.yaml — добавь источники по сабреддитам: SaaS, startups, Entrepreneur, SideProject (min_engagement по вкусу).
7. tests/test_sources_reddit.py — тест с замоканным asyncpraw (без реальной сети).

Контракты раздела 6 не меняем.
```

---

## Этап 6. Product Hunt

```
Реализуй ЭТАП 6 из ARCHITECTURE.md.

Контекст: Этапы 1-5 готовы. Добавляем Product Hunt — что запускают прямо сейчас.

Задача:
1. Новых pip-зависимостей нет — используем общий httpx-клиент + GraphQL API Product Hunt.
2. Создай src/sources/producthunt.py — класс BaseSource (type = "producthunt"). Параметры: topic, limit.
   - GraphQL-запрос к api.producthunt.com/v2/api/graphql, авторизация Bearer PRODUCTHUNT_TOKEN;
   - engagement = votesCount;
   - external_id = id продукта;
   - content = tagline + description;
   - published_at → UTC;
   - graceful degradation при ошибках API.
3. src/settings.py — добавь producthunt_token. Присылай класс настроек целиком с указанием места.
4. .env.example — добавь PRODUCTHUNT_TOKEN.
5. src/sources/registry.py — зарегистрируй "producthunt" (фабрику целиком с указанием места).
6. config/sources.yaml — добавь топики developer-tools, productivity, artificial-intelligence.
7. tests/test_sources_producthunt.py — тест с замоканным ответом GraphQL.

Контракты раздела 6 не меняем.
```

---

## Этап 7. VK

```
Реализуй ЭТАП 7 из ARCHITECTURE.md.

Контекст: Этапы 1-6 готовы. Добавляем русскоязычные VK-паблики.

Задача:
1. Добавь в requirements.txt: vk_api (укажи явно). Если vk_api синхронный — оберни вызовы в asyncio.to_thread, чтобы не блокировать event loop.
2. Создай src/sources/vk.py — класс BaseSource (type = "vk"). Параметр: groups (list доменов/id пабликов).
   - engagement = likes + comments + reposts;
   - external_id = "{owner_id}_{post_id}";
   - content = текст поста;
   - published_at (из unixtime) → UTC;
   - авторизация через VK_ACCESS_TOKEN;
   - ошибки по паблику — ERROR + продолжаем.
3. src/settings.py — добавь vk_access_token. Присылай класс настроек целиком с указанием места.
4. .env.example — добавь VK_ACCESS_TOKEN.
5. src/sources/registry.py — зарегистрируй "vk" (фабрику целиком с указанием места).
6. config/sources.yaml — добавь 2-3 профильных паблика.
7. tests/test_sources_vk.py — тест с замоканным vk_api.

Контракты раздела 6 не меняем.
```

---

## Этап 8. Telegram-каналы

```
Реализуй ЭТАП 8 из ARCHITECTURE.md.

Контекст: Этапы 1-7 готовы. Добавляем чтение TG-каналов через Telethon.

Задача:
1. Добавь в requirements.txt: telethon (укажи явно).
2. Создай src/sources/telegram.py — класс BaseSource (type = "telegram"). Параметр: channels (list).
   - сессия Telethon в volume: /data/telethon.session;
   - engagement = views (если доступны, иначе None);
   - external_id = "{channel}_{message_id}";
   - content = текст сообщения;
   - published_at → UTC;
   - авторизация через TG_API_ID / TG_API_HASH;
   - ошибки по каналу — ERROR + продолжаем.
3. Реализуй разовую интерактивную авторизацию: CLI-команда `python -m src.main tg_login` в src/main.py (typer). Присылай изменённую часть main.py целиком с указанием места.
4. src/settings.py — добавь tg_api_id, tg_api_hash. Присылай класс настроек целиком с указанием места.
5. .env.example — добавь TG_API_ID, TG_API_HASH.
6. docker-compose.yml — добавь volume для /data (сессия). Присылай изменённый сервис целиком с указанием места.
7. src/sources/registry.py — зарегистрируй "telegram" (фабрику целиком с указанием места).
8. config/sources.yaml — добавь список каналов.
9. tests/test_sources_telegram.py — тест с замоканным Telethon-клиентом.

Контракты раздела 6 не меняем.
```

---

## Этап 9. YouTube

```
Реализуй ЭТАП 9 из ARCHITECTURE.md.

Контекст: Этапы 1-8 готовы. Добавляем YouTube — идеи из видео (описания + транскрипты).

Задача:
1. Добавь в requirements.txt: google-api-python-client, youtube-transcript-api (укажи явно). Синхронные вызовы оборачивай в asyncio.to_thread.
2. Создай src/sources/youtube.py — класс BaseSource (type = "youtube"). Параметр: channel_ids (list).
   - через YouTube Data API берём новые видео канала;
   - content = описание + транскрипт (если доступен); если транскрипта нет — только описание + WARNING;
   - engagement = viewCount;
   - external_id = videoId;
   - published_at → UTC;
   - ошибки по каналу/видео — ERROR/WARNING + продолжаем.
3. src/settings.py — добавь youtube_api_key. Присылай класс настроек целиком с указанием места.
4. .env.example — добавь YOUTUBE_API_KEY.
5. src/sources/registry.py — зарегистрируй "youtube" (фабрику целиком с указанием места).
6. config/sources.yaml — добавь список каналов.
7. tests/test_sources_youtube.py — тест с замоканными API и transcript.

Контракты раздела 6 не меняем.
```

---

## Этап 10+. Улучшения (пример: дедупликация)

```
Реализуй улучшение из ЭТАПА 10+ ARCHITECTURE.md: дедупликация похожих постов между источниками.

Контекст: Этапы 1-9 готовы, работают все источники. Одна тема попадает из разных площадок — надо не дублировать её в дайджесте.

ВАЖНО: это улучшение затрагивает схему БД и/или контракты. Действуй так:
1. Сначала предложи правки в ARCHITECTURE.md (какие поля/таблицы/зависимости нужны, например хранение эмбеддингов). НЕ пиши код, пока я не подтвержу правки архитектуры.
2. После подтверждения — реализуй: генерация эмбеддингов, cosine-порог для склейки дубликатов на этапе digest.

Если меняешь src/db/models.py — синхронно обнови init.sql и дай SQL для ручного выполнения. Изменённые функции присылай целиком с указанием места.
```

---
