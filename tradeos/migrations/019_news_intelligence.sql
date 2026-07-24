-- TradeOS migration 019: News Intelligence + the Morning Brief (Milestone 1, the "Intelligence plane").
--
-- This is the second, NEW plane the product gains (decision: two-plane split). The Signal plane
-- (SEC convergence + calibration) keeps its hard rephrase-only guards untouched. This plane lets an
-- AI *interpret* sourced information — but honestly: every interpretation carries citations to the
-- news items it is grounded in, an explicit confidence, and the standing "AI analysis, not advice"
-- frame. Numbers that matter (impact) stay deterministic; only the prose + confidence are the model's.
--
--   news_items          one item from any source (SEC 8-K material event, reputable RSS, ...),
--                       point-in-time (knowable_time) so the brief can be reconstructed for a date.
--   news_item_entities  the tickers a news item is about (SEC filer via security_map; RSS by match).
--   news_analysis       the interpretive layer, cached per item: a DETERMINISTIC impact_score plus
--                       the guarded 'why it matters' prose + confidence + cited sources.
--   daily_briefs        the composed Morning Brief, cached by an inputs-hash per (scope,date[,user]);
--                       user_id NULL = the shared market brief, else a personalized one.

CREATE TABLE news_items (
    id            bigserial PRIMARY KEY,
    source        text NOT NULL,                 -- 'sec/8-k', 'rss/<feed>', ...
    external_id   text NOT NULL,                 -- accession_no (SEC) | stable guid/link hash (RSS)
    url           text NOT NULL,
    headline      text NOT NULL,
    summary       text,                          -- source description or derived item labels; never full-text republish
    category      text,                          -- 'earnings','ma','officer_change','guidance','macro','general',...
    published_at  timestamptz,                   -- the event/publish time as the source states it
    knowable_time timestamptz NOT NULL,          -- when it became public (point-in-time discipline)
    meta          jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, external_id)                 -- idempotent re-ingest
);
CREATE INDEX news_items_knowable_idx ON news_items (knowable_time DESC);
CREATE INDEX news_items_category_idx ON news_items (category);

CREATE TABLE news_item_entities (
    news_id   bigint NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    entity_id bigint,                            -- resolved issuer entity when known
    symbol    text NOT NULL,                     -- the ticker chip the product hangs the item on
    relation  text NOT NULL DEFAULT 'primary',   -- 'primary' (the registrant) | 'mentioned'
    PRIMARY KEY (news_id, symbol)
);
CREATE INDEX news_item_entities_symbol_idx ON news_item_entities (symbol);

CREATE TABLE news_analysis (
    news_id        bigint PRIMARY KEY REFERENCES news_items(id) ON DELETE CASCADE,
    impact_score   int NOT NULL,                 -- 0..100, DETERMINISTIC (category x signal-overlap x recency)
    category       text,                         -- normalized category used for ranking/sections
    why_it_matters text NOT NULL,                -- interpretive prose (guarded: cited, no advice)
    confidence     text NOT NULL,                -- 'low' | 'medium' | 'high'
    sources        jsonb NOT NULL DEFAULT '[]',  -- the news_item ids/urls this interpretation cites
    provider       text NOT NULL,
    model_id       text NOT NULL,
    used_template  boolean NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX news_analysis_impact_idx ON news_analysis (impact_score DESC);

CREATE TABLE daily_briefs (
    id            bigserial PRIMARY KEY,
    user_id       bigint REFERENCES users(id) ON DELETE CASCADE,  -- NULL = shared market brief
    brief_date    date NOT NULL,
    scope         text NOT NULL DEFAULT 'market',                 -- 'market' | 'personal'
    input_hash    char(64) NOT NULL,
    provider      text NOT NULL,
    model_id      text NOT NULL,
    used_template boolean NOT NULL,
    content       jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- one market brief per (date,scope); one personal brief per (user,date,scope). NULL user_id would
-- defeat a plain UNIQUE (NULLs are distinct), so split into two partial unique indexes.
CREATE UNIQUE INDEX daily_briefs_market_uniq   ON daily_briefs (brief_date, scope) WHERE user_id IS NULL;
CREATE UNIQUE INDEX daily_briefs_personal_uniq ON daily_briefs (user_id, brief_date, scope) WHERE user_id IS NOT NULL;

INSERT INTO schema_migrations (version) VALUES (19);
