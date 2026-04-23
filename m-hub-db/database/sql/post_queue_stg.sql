CREATE TABLE public.post_queue_stg (
    -- Core staging metadata
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    stg_status          text NOT NULL DEFAULT 'raw',
    post_queue_id       uuid,
    ingested_at         timestamptz DEFAULT now(),
    ingested_by         text,
    source_system       text,

    -- Validation / review fields
    validation_errors   jsonb DEFAULT '[]'::jsonb,
    rejected_reason     text,
    reviewed_at         timestamptz,
    reviewed_by         text,

    -- Deduplication / batching / source identifiers
    content_hash        text,
    batch_queue_id      uuid,
    source_type         text,
    source_id           text,

    -- Content and media
    post_copy           text,
    image_urls          jsonb DEFAULT '[]'::jsonb,
    affiliate_url       text,
    fb_media_ids        jsonb DEFAULT '[]'::jsonb,

    -- Posting context
    channel             text DEFAULT 'facebook',
    urgency             integer,
    tier                text,
    mobile_suit         text,
    tags                jsonb DEFAULT '[]'::jsonb,
    scheduled_for       timestamptz,

    -- Timestamps
    created_at          timestamptz DEFAULT now(),
    updated_at          timestamptz DEFAULT now(),

    -- Raw product data
    name                text,
    stock               text,

    -- AI enrichment fields
    -- Normalized Gunpla grade (e.g. 'SD', 'HG', 'RG', 'MG', 'PG', 'EG', 'Unknown')
    grade_normalized    text,

    -- Normalized scale (e.g. '1/144', '1/100', '1/60', 'non-scale', 'SD', 'Unknown')
    scale_ai            text,

    -- High-level product type classification
    -- (e.g. 'model_kit', 'figure', 'book', 'decal', 'apparel', 'merch')
    product_type_ai     text,

    -- Brand classification (e.g. 'Bandai', 'Kotobukiya', 'Megahouse', 'Other')
    brand_ai            text,

    -- Audience classification (e.g. 'boys', 'girls', 'adult_collectors', 'unisex', 'unknown')
    audience_ai         text,

    -- Overall confidence score for the AI classification (0.00–1.00)
    classification_confidence numeric(3,2),

    -- Optional notes from AI about the classification
    ai_notes            text,

    -- Flag indicating AI enrichment has been applied
    ai_processed        boolean NOT NULL DEFAULT false,

    -- When AI enrichment last ran for this row
    classified_at       timestamptz
);