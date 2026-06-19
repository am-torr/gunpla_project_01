-- price_history
-- ============================================================================
-- Append-only price + stock snapshots per SKU, captured by the Claude Agent
-- SDK low-stock pipeline (scripts/lowstock_agent/history.py) on every run.
-- One row = one observation of a SKU at a point in time. Covers both "price
-- history" and "stock log" in a single table.
--
-- This is the dataset that powers the V2 deal analyzer: once a SKU has >= 2
-- snapshots, checks/deal.py computes a real price_delta_pct + stock_trend.
-- Additive and append-only — it touches nothing the n8n flow owns.
-- ============================================================================
CREATE TABLE public.price_history (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    sku          text NOT NULL,
    name         text,

    price_jpy    numeric,                        -- parsed from "¥4,241" -> 4241
    prices       jsonb DEFAULT '{}'::jsonb,      -- all currencies as scraped

    stock_raw    text,                           -- "Only 3 left in stock."
    stock_count  integer,                        -- parsed N, null if unparseable
    in_stock     boolean,

    scraped_at   timestamptz NOT NULL,           -- from the scraped item
    captured_at  timestamptz DEFAULT now(),      -- when this row was written
    source       text DEFAULT 'hlj-lowstock-agent',

    -- Re-running the same scrape batch must never double-insert a snapshot.
    CONSTRAINT price_history_sku_scraped_at_key UNIQUE (sku, scraped_at)
);

CREATE INDEX price_history_sku_scraped_idx ON public.price_history (sku, scraped_at DESC);
