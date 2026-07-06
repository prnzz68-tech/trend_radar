-- ============================================================
-- Trend Radar — DDL (Этап 1)
-- Применяется вручную: psql $PSQL_URL -f src/db/init.sql
-- ============================================================

CREATE TABLE IF NOT EXISTS sources (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(128) NOT NULL UNIQUE,
    type         VARCHAR(64)  NOT NULL,
    config_json  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS posts (
    id            BIGSERIAL PRIMARY KEY,
    source_id     INTEGER     NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id   VARCHAR(256) NOT NULL,
    url           TEXT        NOT NULL,
    title         TEXT        NOT NULL,
    author        VARCHAR(256),
    content       TEXT        NOT NULL DEFAULT '',
    engagement INTEGER,
    published_at  TIMESTAMPTZ NOT NULL,
    rating        INTEGER,
    raw_json      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    collected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_posts_source_external UNIQUE (source_id, external_id)
);

CREATE INDEX IF NOT EXISTS ix_posts_source_id    ON posts(source_id);
CREATE INDEX IF NOT EXISTS ix_posts_published_at ON posts(published_at);

CREATE TABLE IF NOT EXISTS post_scores (
    id              BIGSERIAL PRIMARY KEY,
    post_id         BIGINT      NOT NULL UNIQUE REFERENCES posts(id) ON DELETE CASCADE,
    relevance_score INTEGER     NOT NULL,
    category        VARCHAR(32) NOT NULL,
    summary         TEXT        NOT NULL,
    topics          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model           VARCHAR(64) NOT NULL,
    tokens_used     INTEGER     NOT NULL DEFAULT 0,
    problem TEXT,
    pportunity TEXT
);

CREATE INDEX IF NOT EXISTS ix_post_scores_post_id   ON post_scores(post_id);
CREATE INDEX IF NOT EXISTS ix_post_scores_scored_at ON post_scores(scored_at);

CREATE TABLE IF NOT EXISTS digests (
    id            BIGSERIAL PRIMARY KEY,
    period_start  TIMESTAMPTZ NOT NULL,
    period_end    TIMESTAMPTZ NOT NULL,
    content_md    TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at       TIMESTAMPTZ,
    is_manual     BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_digests_sent_at ON digests(sent_at);

CREATE TABLE IF NOT EXISTS digest_posts (
    digest_id BIGINT NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
    post_id   BIGINT NOT NULL REFERENCES posts(id)   ON DELETE CASCADE,
    PRIMARY KEY (digest_id, post_id)
);

CREATE TABLE IF NOT EXISTS delivery_log (
    id        BIGSERIAL PRIMARY KEY,
    post_id   BIGINT      NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    sent_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    digest_id BIGINT      REFERENCES digests(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_delivery_log_post_id ON delivery_log(post_id);

ALTER TABLE posts ADD COLUMN IF NOT EXISTS engagement INTEGER;
ALTER TABLE post_scores ADD COLUMN IF NOT EXISTS problem TEXT;
ALTER TABLE post_scores ADD COLUMN IF NOT EXISTS opportunity TEXT;