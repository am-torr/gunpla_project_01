-- agent_drafts
-- ============================================================================
-- Draft records produced by the Claude Agent SDK low-stock pipeline
-- (scripts/lowstock_agent). OWNED by the agent and kept deliberately SEPARATE
-- from the n8n flow (post_queue / post_queue_stg / post_queue_batch / hlj_posts).
-- The agent never auto-posts: a human reviews these drafts and promotes the good
-- ones by hand.
--
-- Classification columns mirror the live post_queue_stg AI columns so drafts line
-- up with the production staging schema. `post_copy` is the production-faithful
-- deterministic caption (parity with n8n "02 - Create Post Queue Candidates");
-- `suggested_caption` is an optional LLM enhancement for the reviewer.
-- The price_delta_* / is_real_deal fields stay null/low until price_history has
-- >= 2 snapshots for the SKU (V2 deal signal — see price_history.sql).
-- ============================================================================
CREATE TABLE public.agent_drafts (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,

    -- Source identifiers / audit
    sku                       text NOT NULL,
    name                      text,
    source_system             text NOT NULL DEFAULT 'hlj-lowstock-agent',
    source_type               text NOT NULL DEFAULT 'hlj',   -- matches post_queue.source_type
    scraped_at                timestamptz,
    content_hash              text UNIQUE,                   -- idempotent re-runs
    raw_item                  jsonb,                         -- full original low-stock item

    -- Classification (sub-agent 1) — mirrors post_queue_stg AI columns
    is_gunpla                 boolean,
    grade_normalized          text,              -- SD/HG/RG/MG/PG/EG/Unknown
    scale_ai                  text,              -- 1/144, 1/100, 1/60, non-scale, SD, Unknown
    product_type_ai           text,              -- model_kit/figure/book/decal/apparel/merch
    brand_ai                  text,              -- Bandai/Kotobukiya/Megahouse/Other
    audience_ai               text,              -- boys/girls/adult_collectors/unisex/unknown
    classification_confidence numeric(3,2),
    ai_notes                  text,

    -- Dedup (sub-agent 2)
    posted_recently           boolean,
    last_posted_at            timestamptz,
    post_count_30d            integer,

    -- Deal (sub-agent 3): stock-urgency is the V1 signal; price_delta_* fill in
    -- automatically once price_history has enough snapshots (V2).
    stock                     text,
    stock_urgency             integer,
    deal_signal               text,              -- 'stock_urgency_v1' | 'price_delta_v2'
    price_delta_pct           numeric,
    stock_trend               text,              -- 'falling' | 'flat' | 'rising' | null
    is_real_deal              boolean,
    deal_confidence           numeric(3,2),

    -- Content: deterministic post_copy (production parity) + optional LLM caption
    post_copy                 text,              -- the production-faithful template
    short_link                text,              -- Bitly/TinyURL/affiliate used in post_copy
    suggested_caption         text,              -- optional LLM enhancement
    suggested_hashtags        jsonb DEFAULT '[]'::jsonb,
    caption_tone              text,              -- urgent/fan/value/hype/neutral (LLM caption)

    -- Media
    image_urls                jsonb DEFAULT '[]'::jsonb,
    affiliate_url             text,

    -- Review workflow
    qualified                 boolean,           -- passed the caption gate
    gate_reason               text,              -- why it did / didn't qualify
    status                    text NOT NULL DEFAULT 'draft',  -- draft | approved | rejected

    created_at                timestamptz DEFAULT now(),
    updated_at                timestamptz DEFAULT now()
);

CREATE INDEX agent_drafts_status_idx     ON public.agent_drafts (status);
CREATE INDEX agent_drafts_created_at_idx ON public.agent_drafts (created_at DESC);
CREATE INDEX agent_drafts_sku_idx        ON public.agent_drafts (sku);
