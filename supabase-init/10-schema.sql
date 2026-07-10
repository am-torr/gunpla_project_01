--
-- PostgreSQL database dump
--

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.5

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- CREATE SCHEMA public;  -- already exists in the supabase/postgres image


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: post_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.post_status AS ENUM (
    'draft',
    'needs_review',
    'approved',
    'rejected',
    'published'
);


--
-- Name: assign_all_batches(integer, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.assign_all_batches(p_max integer DEFAULT 10, p_message text DEFAULT NULL::text) RETURNS TABLE(batch_id uuid, message text, copy_message text, attached_media jsonb)
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_batch_id uuid;
  v_remaining INT;
  v_status text;
BEGIN
  v_status := 'pending';
  LOOP
    SELECT COUNT(*) INTO v_remaining
    FROM post_queue
    WHERE status = v_status AND batch_queue_id IS NULL;
    EXIT WHEN v_remaining = 0;
    v_batch_id := gen_random_uuid();
    INSERT INTO post_queue_batch (id, message)
    VALUES (v_batch_id, p_message);
    UPDATE post_queue
    SET batch_queue_id = v_batch_id
    WHERE id IN (
      SELECT id FROM post_queue
      WHERE status = v_status AND batch_queue_id IS NULL
      ORDER BY urgency DESC, created_at ASC
      LIMIT p_max
    );
    -- Sync post_queue_stg: update stg rows where source_id matches and stg.status = 'posted'
    UPDATE post_queue_stg stg
    SET batch_queue_id = v_batch_id
    FROM post_queue pq
    WHERE pq.batch_queue_id = v_batch_id
      AND pq.source_id = stg.source_id
      AND stg.stg_status = 'posted';
    RETURN QUERY
    SELECT b.id AS batch_id, b.message,
           string_agg(pq.post_copy, E'\n---\n' ORDER BY pq.urgency DESC, pq.created_at ASC) AS copy_message,
           COALESCE(
             jsonb_agg(jsonb_build_object('media_fbid', fm.fb_media_id))
             FILTER (WHERE fm.fb_media_id IS NOT NULL),
             '[]'::jsonb
           ) AS attached_media
    FROM post_queue_batch b
    JOIN post_queue pq ON pq.batch_queue_id = b.id
    LEFT JOIN LATERAL (
      SELECT jsonb_array_elements_text(pq.fb_media_ids) AS fb_media_id
      WHERE pq.fb_media_ids IS NOT NULL
    ) fm ON true
    WHERE b.id = v_batch_id
    GROUP BY b.id, b.message;
  END LOOP;
END;
$$;


--
-- Name: assign_batch(integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.assign_batch(p_max integer DEFAULT 8) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_batch_id uuid := gen_random_uuid();
BEGIN
  UPDATE post_queue
  SET batch_queue_id = v_batch_id
  WHERE id IN (
    SELECT id FROM post_queue
    WHERE status = 'new'
      AND batch_queue_id IS NULL
    ORDER BY urgency DESC, created_at ASC
    LIMIT p_max
  );
  RETURN v_batch_id;
END;
$$;


--
-- Name: check_repost_cooldown(text, text, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.check_repost_cooldown(p_source_type text, p_source_id text, p_days integer DEFAULT 30) RETURNS jsonb
    LANGUAGE sql STABLE
    AS $$
  SELECT jsonb_build_object(
    'posted_recently', count(*) > 0,
    'post_count_30d',  count(*),
    'last_posted_at',  max(bq.posted_at)
  )
  FROM public.post_queue pq
  JOIN public.post_queue_batch bq
    ON bq.id = pq.batch_queue_id
  WHERE pq.source_type = p_source_type
    AND pq.source_id   = p_source_id
    AND bq.status      = 'posted'
    AND bq.posted_at   >= (now() - (p_days || ' days')::interval);
$$;


--
-- Name: import_post_queue(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.import_post_queue(p_row jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
declare
  v_result jsonb;
  v_post_queue_id uuid;
  v_reason text;
begin
  begin
    insert into public.post_queue (
      batch_queue_id,
      source_type,
      source_id,
      post_copy,
      image_urls,
      affiliate_url,
      status,
      channel,
      urgency,
      tier,
      tags
    )
    values (
      (p_row->>'batch_queue_id')::uuid,
      p_row->>'source_type',
      p_row->>'source_id',
      p_row->>'post_copy',
      p_row->'image_urls',
      p_row->>'affiliate_url',
      coalesce(p_row->>'status', 'new'),
      p_row->>'channel',
      (p_row->>'urgency')::int,
      p_row->>'tier',
      p_row->'tags'
    )
    on conflict (source_type, source_id)
    where status not in ('posted', 'rejected', 'archived')
    do nothing
    returning id, to_jsonb(post_queue.*)
    into v_post_queue_id, v_result;

    if v_result is not null then
      insert into public.post_queue_import_log (
        source_type,
        source_id,
        batch_queue_id,
        outcome,
        reason,
        post_queue_id,
        input_payload
      )
      values (
        p_row->>'source_type',
        p_row->>'source_id',
        (p_row->>'batch_queue_id')::uuid,
        'inserted',
        'row inserted into post_queue',
        v_post_queue_id,
        p_row
      );

      return v_result;
    end if;

    v_reason := 'duplicate skipped by conflict rule';

    insert into public.post_queue_import_log (
      source_type,
      source_id,
      batch_queue_id,
      outcome,
      reason,
      input_payload
    )
    values (
      p_row->>'source_type',
      p_row->>'source_id',
      (p_row->>'batch_queue_id')::uuid,
      'duplicate_skipped',
      v_reason,
      p_row
    );

    return jsonb_build_object(
      'status', 'skipped',
      'reason', v_reason,
      'source_type', p_row->>'source_type',
      'source_id', p_row->>'source_id'
    );

  exception
    when others then
      insert into public.post_queue_import_log (
        source_type,
        source_id,
        batch_queue_id,
        outcome,
        reason,
        sqlstate,
        error_message,
        input_payload
      )
      values (
        p_row->>'source_type',
        p_row->>'source_id',
        case
          when coalesce(p_row->>'batch_queue_id', '') = '' then null
          else (p_row->>'batch_queue_id')::uuid
        end,
        'error',
        'exception during import_post_queue',
        sqlstate,
        sqlerrm,
        p_row
      );

      return jsonb_build_object(
        'status', 'error',
        'sqlstate', sqlstate,
        'message', sqlerrm,
        'source_type', p_row->>'source_type',
        'source_id', p_row->>'source_id'
      );
  end;
end;
$$;


--
-- Name: import_post_queue_stg(jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.import_post_queue_stg(p_row jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
    v_result jsonb;
BEGIN
    INSERT INTO public.post_queue_stg (
        -- Core payload (mirrors post_queue)
        batch_queue_id,
        source_type,
        source_id,
        post_copy,
        image_urls,
        affiliate_url,
        fb_media_ids,
        channel,
        urgency,
        tier,
        mobile_suit,
        tags,
        scheduled_for,

        -- Staging‑specific fields
        content_hash,
        ingested_by,
        source_system,
        stg_status
    )
    VALUES (
        (p_row->>'batch_queue_id')::uuid,
        p_row->>'source_type',
        p_row->>'source_id',
        p_row->>'post_copy',
        p_row->'image_urls',
        p_row->>'affiliate_url',
        p_row->'fb_media_ids',
        COALESCE(p_row->>'channel', 'facebook')::text,
        (p_row->>'urgency')::int,
        p_row->>'tier',
        p_row->>'mobile_suit',
        p_row->'tags',
        (p_row->>'scheduled_for')::timestamptz,
        p_row->>'content_hash',
        p_row->>'ingested_by',
        p_row->>'source_system',
        COALESCE(p_row->>'stg_status', 'raw')   -- default to 'raw' if not supplied
    )
    ON CONFLICT (content_hash) DO NOTHING   -- unique index on content_hash blocks dupes
    RETURNING to_jsonb(post_queue_stg.*) INTO v_result;

    -- Return the inserted row or an empty object if the conflict was skipped
    RETURN COALESCE(v_result, '{}'::jsonb);
END;
$$;


--
-- Name: import_post_queue_stg(jsonb, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.import_post_queue_stg(p_row jsonb, p_repost_days integer DEFAULT 30) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
  v_result            jsonb;
  v_recently_posted   boolean := false;
  v_last_posted_at    timestamptz;
  v_existing_stg      jsonb;
BEGIN
  -- 1) REPOST COOLDOWN (PRIMARY FILTER)
  IF p_repost_days > 0 THEN
    SELECT bq.posted_at
    INTO v_last_posted_at
    FROM public.post_queue pq
    JOIN public.post_queue_batch bq
      ON bq.id = pq.batch_queue_id
    WHERE pq.source_type = p_row->>'source_type'
      AND pq.source_id   = p_row->>'source_id'
      AND bq.status      = 'posted'
      AND bq.posted_at   >= (now() - (p_repost_days || ' days')::interval)
    ORDER BY bq.posted_at DESC
    LIMIT 1;

    v_recently_posted := v_last_posted_at IS NOT NULL;
  END IF;

  IF v_recently_posted THEN
    RETURN jsonb_build_object(
      'inserted',       false,
      'reason',         'repost_cooldown',
      'source_id',      p_row->>'source_id',
      'source_type',    p_row->>'source_type',
      'repost_days',    p_repost_days,
      'last_posted_at', v_last_posted_at,
      'eligible_at',    v_last_posted_at + (p_repost_days || ' days')::interval
    );
  END IF;

  /*
    2) DUPLICATE HASH CHECK (SECONDARY, RESPECTING COOLDOWN)

    At this point, cooldown has already allowed a repost.

    We now look up any existing staging row with the same content_hash.
    If there is an existing row with an "active" staging status, we treat
    this as a true duplicate and do NOT insert a new one.
    If the existing row is completed / non-active, we proceed to insert a fresh row.
  */
  SELECT to_jsonb(s.*)
  INTO v_existing_stg
  FROM public.post_queue_stg s
  WHERE s.content_hash = p_row->>'content_hash'
  ORDER BY s.created_at DESC
  LIMIT 1;

  IF v_existing_stg IS NOT NULL
     AND (v_existing_stg->>'stg_status') IN ('raw', 'queued', 'processing') THEN
    RETURN jsonb_build_object(
      'inserted',            false,
      'reason',              'duplicate_hash',
      'source_id',           p_row->>'source_id',
      'source_type',         p_row->>'source_type',
      'content_hash',        p_row->>'content_hash',
      'existing_stg_id',     v_existing_stg->>'id',
      'existing_stg_status', v_existing_stg->>'stg_status',
      'first_ingested_at',   v_existing_stg->>'created_at'
    );
  END IF;

  -- 3) INSERT INTO STAGING (ALLOWED BY COOLDOWN + DUPLICATE POLICY)
  INSERT INTO public.post_queue_stg (
    batch_queue_id,
    source_type,
    source_id,
    post_copy,
    image_urls,
    affiliate_url,
    fb_media_ids,
    channel,
    urgency,
    tier,
    mobile_suit,
    tags,
    scheduled_for,
    content_hash,
    ingested_by,
    source_system,
    stg_status,
    name,
    stock,

    -- raw product fields
    sku,
    gradescale,
    scraped_at,
    image_url,

    -- pricing fields
    currency_source,
    price_jpy,
    price_php,
    price_usd,
    price_sgd,
    price_myr,
    price_thb,
    price_idr
  )
  VALUES (
    (p_row->>'batch_queue_id')::uuid,
    p_row->>'source_type',
    p_row->>'source_id',
    p_row->>'post_copy',
    p_row->'image_urls',
    p_row->>'affiliate_url',
    p_row->'fb_media_ids',
    COALESCE(p_row->>'channel', 'facebook'),
    (p_row->>'urgency')::int,
    p_row->>'tier',
    p_row->>'mobile_suit',
    p_row->'tags',
    (p_row->>'scheduled_for')::timestamptz,
    p_row->>'content_hash',
    p_row->>'ingested_by',
    p_row->>'source_system',
    COALESCE(p_row->>'stg_status', 'raw'),
    p_row->>'name',
    p_row->>'stock',

    -- raw product fields from p_row
    p_row->>'sku',
    p_row->>'gradescale',
    nullif(p_row->>'scraped_at', '')::timestamptz,
    p_row->>'image_url',

    -- pricing fields from p_row
    COALESCE(p_row->>'currency_source', 'JPY'),
    nullif(
      regexp_replace(
        COALESCE(p_row->>'price_jpy', ''),
        '[^0-9.\-]',
        '',
        'g'
      ),
      ''
    )::numeric,
    nullif(p_row->>'price_php', '')::numeric,
    nullif(p_row->>'price_usd', '')::numeric,
    nullif(p_row->>'price_sgd', '')::numeric,
    nullif(p_row->>'price_myr', '')::numeric,
    nullif(p_row->>'price_thb', '')::numeric,
    nullif(p_row->>'price_idr', '')::numeric
  )
  -- Unique index on content_hash; this should be hit only in rare race conditions now
  ON CONFLICT (content_hash) DO NOTHING
  RETURNING to_jsonb(post_queue_stg.*) INTO v_result;

  IF v_result IS NULL THEN
    -- Extremely rare race: another process inserted between our SELECT and INSERT.
    -- In that case, surface it as duplicate_hash_race with the latest staging row.
    SELECT to_jsonb(s.*)
    INTO v_result
    FROM public.post_queue_stg s
    WHERE s.content_hash = p_row->>'content_hash'
    ORDER BY s.created_at DESC
    LIMIT 1;

    RETURN jsonb_build_object(
      'inserted',            false,
      'reason',              'duplicate_hash_race',
      'source_id',           p_row->>'source_id',
      'source_type',         p_row->>'source_type',
      'content_hash',        p_row->>'content_hash',
      'existing_stg_id',     v_result->>'id',
      'existing_stg_status', v_result->>'stg_status',
      'first_ingested_at',   v_result->>'created_at'
    );
  END IF;

  -- Success: new row inserted
  RETURN v_result || jsonb_build_object('inserted', true, 'reason', 'new');
END;
$$;


--
-- Name: match_documents(public.vector, double precision, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.match_documents(query_embedding public.vector, match_threshold double precision DEFAULT 0.7, match_count integer DEFAULT 5) RETURNS TABLE(id bigint, content text, metadata jsonb, similarity double precision)
    LANGUAGE sql STABLE
    AS $$
  SELECT
    documents.id,
    documents.content,
    documents.metadata,
    1 - (documents.embedding <=> query_embedding) AS similarity
  FROM documents
  WHERE 1 - (documents.embedding <=> query_embedding) > match_threshold
  ORDER BY documents.embedding <=> query_embedding
  LIMIT match_count;
$$;


--
-- Name: match_gunpla(public.vector, double precision, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.match_gunpla(query_emb public.vector, threshold double precision DEFAULT 0.7, match_count integer DEFAULT 5) RETURNS TABLE(id bigint, title text, content text, score double precision, similarity double precision)
    LANGUAGE sql STABLE
    AS $$
  SELECT id, title, content, score,
         1 - (embedding <=> query_emb) AS similarity
  FROM news_backlog
  WHERE embedding IS NOT NULL
    AND 1 - (embedding <=> query_emb) > threshold
  ORDER BY embedding <=> query_emb
  LIMIT match_count;
$$;


--
-- Name: match_scraped_to_catalog(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.match_scraped_to_catalog() RETURNS TABLE(scraped_id uuid, catalog_id uuid, confidence numeric)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
  RETURN QUERY
  UPDATE scraped_products sp
  SET
    catalog_id = best_match.id,
    match_confidence = best_match.confidence
  FROM (
    SELECT DISTINCT ON (sp2.id)
      sp2.id as scraped_id,
      gc.id,
      similarity(sp2.productname, gc.product_name) as confidence
    FROM scraped_products sp2
    CROSS JOIN gunpla_catalog gc
    WHERE similarity(sp2.productname, gc.product_name) > 0.3
    ORDER BY sp2.id, similarity(sp2.productname, gc.product_name) DESC
  ) as best_match
  WHERE sp.id = best_match.scraped_id
  RETURNING sp.id, sp.catalog_id, sp.match_confidence;
END;
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
begin
  new.updated_at = now();
  return new;
end;
$$;


--
-- Name: update_scraped_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_scraped_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.scraped_at = NOW();
  RETURN NEW;
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_drafts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_drafts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sku text NOT NULL,
    name text,
    source_system text DEFAULT 'hlj-lowstock-agent'::text NOT NULL,
    source_type text DEFAULT 'hlj'::text NOT NULL,
    scraped_at timestamp with time zone,
    content_hash text,
    raw_item jsonb,
    is_gunpla boolean,
    grade_normalized text,
    scale_ai text,
    product_type_ai text,
    brand_ai text,
    audience_ai text,
    classification_confidence numeric(3,2),
    ai_notes text,
    posted_recently boolean,
    last_posted_at timestamp with time zone,
    post_count_30d integer,
    stock text,
    stock_urgency integer,
    deal_signal text,
    price_delta_pct numeric,
    stock_trend text,
    is_real_deal boolean,
    deal_confidence numeric(3,2),
    post_copy text,
    short_link text,
    suggested_caption text,
    suggested_hashtags jsonb DEFAULT '[]'::jsonb,
    caption_tone text,
    image_urls jsonb DEFAULT '[]'::jsonb,
    affiliate_url text,
    qualified boolean,
    gate_reason text,
    status text DEFAULT 'draft'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: app_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_config (
    key text NOT NULL,
    value text
);


--
-- Name: bandai_kits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bandai_kits (
    id integer NOT NULL,
    bandai_manual_id integer NOT NULL,
    name_jp text,
    name_en text,
    part_no text,
    release_date date,
    brand text,
    series_jp text,
    series_en text,
    source_url text,
    scraped_at timestamp with time zone DEFAULT now()
);


--
-- Name: bandai_kits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bandai_kits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bandai_kits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bandai_kits_id_seq OWNED BY public.bandai_kits.id;


--
-- Name: boxingposts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.boxingposts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    fight_id uuid NOT NULL,
    hook text,
    caption text,
    visualtext text,
    cta text,
    tone text,
    source_summary text,
    status public.post_status DEFAULT 'needs_review'::public.post_status NOT NULL,
    reviewer_note text,
    hook_template_id uuid,
    model text,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    approved_at timestamp with time zone,
    published_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: color_guide; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.color_guide (
    id integer NOT NULL,
    bandai_manual_id integer,
    part_name text,
    color_name text,
    mix_ratios jsonb,
    paint_brand text
);


--
-- Name: color_guide_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.color_guide_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: color_guide_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.color_guide_id_seq OWNED BY public.color_guide.id;


--
-- Name: country_channels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.country_channels (
    country_code text NOT NULL,
    flag_emoji text NOT NULL,
    channel_type text NOT NULL,
    base_url text NOT NULL,
    shop_id text,
    display_order integer DEFAULT 100 NOT NULL,
    active boolean DEFAULT true NOT NULL
);


--
-- Name: crawler_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.crawler_state (
    key text NOT NULL,
    value text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id bigint NOT NULL,
    filename text,
    chunk_index integer,
    content text NOT NULL,
    metadata jsonb,
    embedding public.vector(384)
);


--
-- Name: documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.documents ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: exchange_rates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exchange_rates (
    base text DEFAULT 'JPY'::text NOT NULL,
    php numeric NOT NULL,
    sgd numeric NOT NULL,
    myr numeric NOT NULL,
    thb numeric NOT NULL,
    usd numeric NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    created_by text DEFAULT 'n8n'::text NOT NULL,
    updated_by text DEFAULT 'n8n'::text NOT NULL,
    idr numeric
);


--
-- Name: fight_library; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fight_library (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    fight_id text,
    fighter_1 text,
    fighter_2 text,
    result text,
    ko_round text,
    fight_date date,
    raw_data jsonb,
    used_count integer DEFAULT 0,
    last_used_at timestamp with time zone,
    source text,
    event_title text
);


--
-- Name: fightlibrary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fightlibrary (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source text NOT NULL,
    source_event_id text,
    event_title text NOT NULL,
    fighter_a text,
    fighter_b text,
    event_date date,
    venue text,
    result text,
    ko_round integer,
    weight_class text,
    title_stakes text,
    raw jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: framework_knowledge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.framework_knowledge (
    id bigint NOT NULL,
    partition text NOT NULL,
    source_type text NOT NULL,
    title text,
    content text,
    metadata jsonb,
    embedding public.vector(384),
    relevance_score double precision DEFAULT 0.0,
    access_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: framework_knowledge_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.framework_knowledge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: framework_knowledge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.framework_knowledge_id_seq OWNED BY public.framework_knowledge.id;


--
-- Name: frameworkknowledge; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.frameworkknowledge (
    id integer NOT NULL,
    category text NOT NULL,
    content text NOT NULL,
    embedding public.vector(384),
    metadata jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: frameworkknowledge_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.frameworkknowledge_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: frameworkknowledge_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.frameworkknowledge_id_seq OWNED BY public.frameworkknowledge.id;


--
-- Name: gunpla_catalog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gunpla_catalog (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    sku text NOT NULL,
    product_name text NOT NULL,
    grade character varying(20),
    scale character varying(20) DEFAULT '1/144'::character varying,
    series character varying(100),
    mobile_suit_model character varying(50),
    bandai_sku character varying(50),
    release_date date,
    original_price_jpy numeric(10,2),
    manufacturer character varying(50) DEFAULT 'Bandai'::character varying,
    distribution_type character varying(50) NOT NULL,
    region_restrictions text,
    special_edition character varying(100),
    coating_type character varying(50),
    attributes jsonb,
    is_discontinued boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: hlj_posts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hlj_posts (
    id integer NOT NULL,
    sku text NOT NULL,
    name text,
    price_php numeric,
    stock text,
    affiliate_url text,
    status text DEFAULT 'staged'::text,
    price_jpy numeric,
    price_sgd numeric,
    price_usd numeric,
    price_myr numeric,
    price_thb numeric,
    price_idr numeric,
    image_url text,
    grade_scale text,
    scraped_at timestamp with time zone DEFAULT now(),
    posted_at timestamp with time zone,
    created_by text DEFAULT 'MEGALLANICA'::text,
    updated_by text DEFAULT 'MEGALLANICA'::text,
    notes text,
    image_urls text
);


--
-- Name: hlj_posts_bk_411; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hlj_posts_bk_411 (
    id integer,
    sku text,
    name text,
    price_php numeric,
    stock text,
    affiliate_url text,
    status text,
    price_jpy numeric,
    price_sgd numeric,
    price_usd numeric,
    price_myr numeric,
    price_thb numeric,
    price_idr numeric,
    image_url text,
    grade_scale text,
    scraped_at timestamp with time zone,
    posted_at timestamp with time zone,
    created_by text,
    updated_by text,
    notes text,
    image_urls text
);


--
-- Name: hlj_posts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.hlj_posts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hlj_posts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.hlj_posts_id_seq OWNED BY public.hlj_posts.id;


--
-- Name: hook_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hook_templates (
    id integer NOT NULL,
    template text,
    last_used_at timestamp with time zone
);


--
-- Name: hook_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.hook_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hook_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.hook_templates_id_seq OWNED BY public.hook_templates.id;


--
-- Name: hooktemplates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hooktemplates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    label text NOT NULL,
    pattern text NOT NULL,
    tone text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: mecha_specs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mecha_specs (
    id integer NOT NULL,
    bandai_manual_id integer,
    model_number text,
    classification text,
    head_height text,
    weight_empty text,
    weight_total text,
    generator_output text,
    thruster_output text,
    material text,
    armaments text[],
    raw_page1_text text,
    extracted_at timestamp with time zone DEFAULT now()
);


--
-- Name: mecha_specs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.mecha_specs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mecha_specs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.mecha_specs_id_seq OWNED BY public.mecha_specs.id;


--
-- Name: n8nexecutions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.n8nexecutions (
    id integer NOT NULL,
    workflow_id text NOT NULL,
    node_name text,
    error_type text,
    error_message text,
    solution_applied text,
    success_status boolean,
    executed_at timestamp with time zone DEFAULT now()
);


--
-- Name: n8nexecutions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.n8nexecutions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: n8nexecutions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.n8nexecutions_id_seq OWNED BY public.n8nexecutions.id;


--
-- Name: news_backlog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_backlog (
    id integer NOT NULL,
    source text NOT NULL,
    title text NOT NULL,
    content text,
    score integer,
    scraped_at timestamp without time zone DEFAULT now(),
    created_by text DEFAULT 'industrial-7'::text,
    updated_at timestamp without time zone DEFAULT now(),
    embedding public.vector(384),
    status text DEFAULT 'pending'::text,
    url text,
    content_hash text,
    content_type text DEFAULT 'news'::text NOT NULL,
    post_copy text,
    image_url text,
    approved_at timestamp with time zone,
    posted_at timestamp with time zone,
    fb_post_id text
);


--
-- Name: news_backlog_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.news_backlog_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: news_backlog_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.news_backlog_id_seq OWNED BY public.news_backlog.id;


--
-- Name: post_queue; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.post_queue (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    batch_queue_id uuid,
    source_type text NOT NULL,
    source_id text,
    post_copy text NOT NULL,
    image_urls jsonb DEFAULT '[]'::jsonb,
    affiliate_url text,
    fb_media_ids jsonb DEFAULT '[]'::jsonb,
    status text DEFAULT 'pending'::text,
    approved_by text,
    approved_at timestamp with time zone,
    scheduled_for timestamp with time zone,
    channel text DEFAULT 'facebook'::text,
    urgency integer,
    tier text,
    mobile_suit text,
    tags jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    posted_at timestamp with time zone,
    created_by text,
    updated_by text,
    fb_post_id text
);


--
-- Name: post_queue_batch; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.post_queue_batch (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    channel text DEFAULT 'facebook'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    message text,
    fb_post_id text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    posted_at timestamp with time zone,
    posted_by text,
    created_by text,
    updated_by text
);


--
-- Name: post_queue_import_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.post_queue_import_log (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_type text,
    source_id text,
    batch_queue_id uuid,
    outcome text NOT NULL,
    reason text,
    post_queue_id uuid,
    sqlstate text,
    error_message text,
    input_payload jsonb NOT NULL,
    CONSTRAINT post_queue_import_log_outcome_check CHECK ((outcome = ANY (ARRAY['inserted'::text, 'duplicate_skipped'::text, 'error'::text])))
);


--
-- Name: post_queue_import_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.post_queue_import_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: post_queue_import_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.post_queue_import_log_id_seq OWNED BY public.post_queue_import_log.id;


--
-- Name: post_queue_stg; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.post_queue_stg (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    stg_status text DEFAULT 'raw'::text NOT NULL,
    post_queue_id uuid,
    ingested_at timestamp with time zone DEFAULT now(),
    ingested_by text,
    source_system text,
    validation_errors jsonb DEFAULT '[]'::jsonb,
    rejected_reason text,
    reviewed_at timestamp with time zone,
    reviewed_by text,
    content_hash text,
    batch_queue_id uuid,
    source_type text,
    source_id text,
    post_copy text,
    image_urls jsonb DEFAULT '[]'::jsonb,
    affiliate_url text,
    fb_media_ids jsonb DEFAULT '[]'::jsonb,
    channel text DEFAULT 'facebook'::text,
    urgency integer,
    tier text,
    mobile_suit text,
    tags jsonb DEFAULT '[]'::jsonb,
    scheduled_for timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    name text,
    stock text,
    grade_normalized text,
    scale_ai text,
    product_type_ai text,
    brand_ai text,
    audience_ai text,
    classification_confidence numeric(3,2),
    ai_notes text,
    ai_processed boolean DEFAULT false NOT NULL,
    classified_at timestamp with time zone,
    sku text,
    gradescale text,
    scraped_at timestamp with time zone,
    image_url text,
    currency_source text DEFAULT 'JPY'::text,
    price_jpy numeric(12,2),
    price_php numeric(12,2),
    price_usd numeric(12,2),
    price_sgd numeric(12,2),
    price_myr numeric(12,2),
    price_thb numeric(12,2),
    price_idr numeric(14,2)
)
WITH (autovacuum_vacuum_scale_factor='0.05', autovacuum_analyze_scale_factor='0.02');


--
-- Name: post_queue_stg_sorted; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.post_queue_stg_sorted AS
 SELECT id,
    stg_status,
    post_queue_id,
    ingested_at,
    ingested_by,
    source_system,
    validation_errors,
    rejected_reason,
    reviewed_at,
    reviewed_by,
    content_hash,
    batch_queue_id,
    source_type,
    source_id,
    post_copy,
    image_urls,
    affiliate_url,
    fb_media_ids,
    channel,
    urgency,
    tier,
    mobile_suit,
    tags,
    scheduled_for,
    created_at,
    updated_at,
    name,
    stock,
    grade_normalized,
    scale_ai,
    product_type_ai,
    brand_ai,
    audience_ai,
    classification_confidence,
    ai_notes,
    ai_processed,
    classified_at,
    sku,
    gradescale,
    scraped_at,
    image_url,
    currency_source,
    price_jpy,
    price_php,
    price_usd,
    price_sgd,
    price_myr,
    price_thb,
    price_idr,
        CASE
            WHEN (stock ~~* 'Only % left in stock%'::text) THEN ("substring"(stock, 'Only (\d+) left'::text))::integer
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Jan'::text, 'January'::text])) THEN 101
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Feb'::text, 'February'::text])) THEN 102
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Mar'::text, 'March'::text])) THEN 103
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Apr'::text, 'April'::text])) THEN 104
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = 'May'::text) THEN 105
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Jun'::text, 'June'::text])) THEN 106
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Jul'::text, 'July'::text])) THEN 107
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Aug'::text, 'August'::text])) THEN 108
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Sep'::text, 'Sept'::text, 'September'::text])) THEN 109
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Oct'::text, 'October'::text])) THEN 110
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Nov'::text, 'November'::text])) THEN 111
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Dec'::text, 'December'::text])) THEN 112
            ELSE 199
        END AS stock_sort_order
   FROM public.post_queue_stg
  WHERE ((stock ~~* 'Only % left in stock%'::text) OR ((
        CASE TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text))
            WHEN 'Jan'::text THEN 1
            WHEN 'January'::text THEN 1
            WHEN 'Feb'::text THEN 2
            WHEN 'February'::text THEN 2
            WHEN 'Mar'::text THEN 3
            WHEN 'March'::text THEN 3
            WHEN 'Apr'::text THEN 4
            WHEN 'April'::text THEN 4
            WHEN 'May'::text THEN 5
            WHEN 'Jun'::text THEN 6
            WHEN 'June'::text THEN 6
            WHEN 'Jul'::text THEN 7
            WHEN 'July'::text THEN 7
            WHEN 'Aug'::text THEN 8
            WHEN 'August'::text THEN 8
            WHEN 'Sep'::text THEN 9
            WHEN 'Sept'::text THEN 9
            WHEN 'September'::text THEN 9
            WHEN 'Oct'::text THEN 10
            WHEN 'October'::text THEN 10
            WHEN 'Nov'::text THEN 11
            WHEN 'November'::text THEN 11
            WHEN 'Dec'::text THEN 12
            WHEN 'December'::text THEN 12
            ELSE 99
        END)::numeric >= EXTRACT(month FROM CURRENT_DATE)))
  ORDER BY
        CASE
            WHEN (stock ~~* 'Only % left in stock%'::text) THEN ("substring"(stock, 'Only (\d+) left'::text))::integer
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Jan'::text, 'January'::text])) THEN 101
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Feb'::text, 'February'::text])) THEN 102
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Mar'::text, 'March'::text])) THEN 103
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Apr'::text, 'April'::text])) THEN 104
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = 'May'::text) THEN 105
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Jun'::text, 'June'::text])) THEN 106
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Jul'::text, 'July'::text])) THEN 107
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Aug'::text, 'August'::text])) THEN 108
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Sep'::text, 'Sept'::text, 'September'::text])) THEN 109
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Oct'::text, 'October'::text])) THEN 110
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Nov'::text, 'November'::text])) THEN 111
            WHEN (TRIM(BOTH FROM "substring"(stock, '^[A-Za-z]+'::text)) = ANY (ARRAY['Dec'::text, 'December'::text])) THEN 112
            ELSE 199
        END;


--
-- Name: price_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.price_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sku text NOT NULL,
    name text,
    price_jpy numeric,
    prices jsonb DEFAULT '{}'::jsonb,
    stock_raw text,
    stock_count integer,
    in_stock boolean,
    scraped_at timestamp with time zone NOT NULL,
    captured_at timestamp with time zone DEFAULT now(),
    source text DEFAULT 'hlj-lowstock-agent'::text
);


--
-- Name: resolve_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resolve_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    backlog_id integer,
    status text DEFAULT 'pending'::text NOT NULL,
    product_title text,
    official_url text,
    keyword text,
    shops jsonb DEFAULT '[]'::jsonb NOT NULL,
    results jsonb DEFAULT '{}'::jsonb NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    claimed_at timestamp with time zone,
    resolved_at timestamp with time zone,
    expires_at timestamp with time zone DEFAULT (now() + '18:00:00'::interval) NOT NULL
);


--
-- Name: scrape_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scrape_logs (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    store_name text,
    status text,
    error_message text,
    products_scraped integer,
    duration_seconds numeric,
    scraped_at timestamp without time zone DEFAULT now()
);


--
-- Name: scraped_products; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scraped_products (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    product_name text NOT NULL,
    grade text,
    scale text,
    series text,
    special_edition text,
    bandai_sku text,
    first_seen timestamp without time zone DEFAULT now(),
    last_updated timestamp without time zone DEFAULT now(),
    brand text,
    image_url text,
    on_sale boolean DEFAULT false,
    sku text,
    catalog_id uuid,
    match_confidence numeric(3,2),
    distribution_type text DEFAULT 'web'::text,
    store_id text
);


--
-- Name: COLUMN scraped_products.catalog_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scraped_products.catalog_id IS 'Foreign key linking to master gunpla_catalog';


--
-- Name: COLUMN scraped_products.match_confidence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.scraped_products.match_confidence IS 'Fuzzy matching confidence score (0.00-1.00, 0.80+ recommended)';


--
-- Name: store_prices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.store_prices (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    product_id uuid,
    store_name text NOT NULL,
    price numeric(10,2),
    currency text DEFAULT 'PHP'::text,
    stock_status text,
    product_url text,
    scraped_at timestamp without time zone DEFAULT now(),
    store_id uuid,
    distribution_type text DEFAULT 'web'::text
);


--
-- Name: stores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stores (
    id uuid DEFAULT extensions.uuid_generate_v4() NOT NULL,
    store_name text NOT NULL,
    store_url text,
    country text DEFAULT 'PH'::text,
    is_active boolean DEFAULT true,
    last_scraped timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: tracker_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tracker_logs (
    id bigint NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now(),
    run_type character varying(50),
    status character varying(20),
    error_msg text,
    metrics jsonb,
    raw_data jsonb,
    duration_ms integer
);


--
-- Name: tracker_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tracker_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tracker_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tracker_logs_id_seq OWNED BY public.tracker_logs.id;


--
-- Name: vw_availability_status; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.vw_availability_status AS
 SELECT c.id AS catalog_id,
    c.sku,
    c.product_name,
    c.grade,
    count(DISTINCT sp.store_name) AS total_stores,
    sum(
        CASE
            WHEN ((sp.stock_status ~~* '%order now%'::text) OR (sp.stock_status ~~* '%in stock%'::text)) THEN 1
            ELSE 0
        END) AS in_stock_count,
    sum(
        CASE
            WHEN ((sp.stock_status ~~* '%out of stock%'::text) OR (sp.stock_status ~~* '%sold out%'::text)) THEN 1
            ELSE 0
        END) AS out_of_stock_count,
    sum(
        CASE
            WHEN ((sp.stock_status ~~* '%preorder%'::text) OR (sp.stock_status ~~* '%pre-order%'::text)) THEN 1
            ELSE 0
        END) AS preorder_count
   FROM (public.gunpla_catalog c
     LEFT JOIN public.store_prices sp ON ((c.id = sp.product_id)))
  GROUP BY c.id, c.sku, c.product_name, c.grade;


--
-- Name: vw_latest_prices; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.vw_latest_prices AS
 SELECT c.id AS catalog_id,
    c.sku,
    c.product_name,
    c.grade,
    c.series,
    sp.store_name,
    sp.price,
    sp.currency,
    sp.stock_status,
    sp.product_url,
    sp.scraped_at,
    row_number() OVER (PARTITION BY c.id, sp.store_name ORDER BY sp.scraped_at DESC) AS rn
   FROM (public.gunpla_catalog c
     LEFT JOIN public.store_prices sp ON ((c.id = sp.product_id)))
  WHERE (sp.scraped_at IS NOT NULL);


--
-- Name: vw_price_comparison; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.vw_price_comparison AS
 SELECT catalog_id,
    sku,
    product_name,
    min(price) AS min_price,
    max(price) AS max_price,
    avg(price) AS avg_price,
    count(DISTINCT store_name) AS store_count,
    currency
   FROM public.vw_latest_prices
  WHERE ((rn = 1) AND (price IS NOT NULL))
  GROUP BY catalog_id, sku, product_name, currency;


--
-- Name: bandai_kits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bandai_kits ALTER COLUMN id SET DEFAULT nextval('public.bandai_kits_id_seq'::regclass);


--
-- Name: color_guide id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.color_guide ALTER COLUMN id SET DEFAULT nextval('public.color_guide_id_seq'::regclass);


--
-- Name: framework_knowledge id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.framework_knowledge ALTER COLUMN id SET DEFAULT nextval('public.framework_knowledge_id_seq'::regclass);


--
-- Name: frameworkknowledge id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.frameworkknowledge ALTER COLUMN id SET DEFAULT nextval('public.frameworkknowledge_id_seq'::regclass);


--
-- Name: hlj_posts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hlj_posts ALTER COLUMN id SET DEFAULT nextval('public.hlj_posts_id_seq'::regclass);


--
-- Name: hook_templates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hook_templates ALTER COLUMN id SET DEFAULT nextval('public.hook_templates_id_seq'::regclass);


--
-- Name: mecha_specs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mecha_specs ALTER COLUMN id SET DEFAULT nextval('public.mecha_specs_id_seq'::regclass);


--
-- Name: n8nexecutions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.n8nexecutions ALTER COLUMN id SET DEFAULT nextval('public.n8nexecutions_id_seq'::regclass);


--
-- Name: news_backlog id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backlog ALTER COLUMN id SET DEFAULT nextval('public.news_backlog_id_seq'::regclass);


--
-- Name: post_queue_import_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post_queue_import_log ALTER COLUMN id SET DEFAULT nextval('public.post_queue_import_log_id_seq'::regclass);


--
-- Name: tracker_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tracker_logs ALTER COLUMN id SET DEFAULT nextval('public.tracker_logs_id_seq'::regclass);


--
-- Name: agent_drafts agent_drafts_content_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_drafts
    ADD CONSTRAINT agent_drafts_content_hash_key UNIQUE (content_hash);


--
-- Name: agent_drafts agent_drafts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_drafts
    ADD CONSTRAINT agent_drafts_pkey PRIMARY KEY (id);


--
-- Name: app_config app_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_config
    ADD CONSTRAINT app_config_pkey PRIMARY KEY (key);


--
-- Name: bandai_kits bandai_kits_bandai_manual_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bandai_kits
    ADD CONSTRAINT bandai_kits_bandai_manual_id_key UNIQUE (bandai_manual_id);


--
-- Name: bandai_kits bandai_kits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bandai_kits
    ADD CONSTRAINT bandai_kits_pkey PRIMARY KEY (id);


--
-- Name: boxingposts boxingposts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boxingposts
    ADD CONSTRAINT boxingposts_pkey PRIMARY KEY (id);


--
-- Name: color_guide color_guide_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.color_guide
    ADD CONSTRAINT color_guide_pkey PRIMARY KEY (id);


--
-- Name: country_channels country_channels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.country_channels
    ADD CONSTRAINT country_channels_pkey PRIMARY KEY (country_code);


--
-- Name: crawler_state crawler_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crawler_state
    ADD CONSTRAINT crawler_state_pkey PRIMARY KEY (key);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: exchange_rates exchange_rates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exchange_rates
    ADD CONSTRAINT exchange_rates_pkey PRIMARY KEY (base);


--
-- Name: fight_library fight_library_fight_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fight_library
    ADD CONSTRAINT fight_library_fight_id_key UNIQUE (fight_id);


--
-- Name: fight_library fight_library_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fight_library
    ADD CONSTRAINT fight_library_pkey PRIMARY KEY (id);


--
-- Name: fightlibrary fightlibrary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fightlibrary
    ADD CONSTRAINT fightlibrary_pkey PRIMARY KEY (id);


--
-- Name: fightlibrary fightlibrary_source_source_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fightlibrary
    ADD CONSTRAINT fightlibrary_source_source_event_id_key UNIQUE (source, source_event_id);


--
-- Name: framework_knowledge framework_knowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.framework_knowledge
    ADD CONSTRAINT framework_knowledge_pkey PRIMARY KEY (id);


--
-- Name: frameworkknowledge frameworkknowledge_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.frameworkknowledge
    ADD CONSTRAINT frameworkknowledge_pkey PRIMARY KEY (id);


--
-- Name: gunpla_catalog gunpla_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gunpla_catalog
    ADD CONSTRAINT gunpla_catalog_pkey PRIMARY KEY (id);


--
-- Name: gunpla_catalog gunpla_catalog_sku_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gunpla_catalog
    ADD CONSTRAINT gunpla_catalog_sku_key UNIQUE (sku);


--
-- Name: hlj_posts hlj_posts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hlj_posts
    ADD CONSTRAINT hlj_posts_pkey PRIMARY KEY (id);


--
-- Name: hlj_posts hlj_posts_sku_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hlj_posts
    ADD CONSTRAINT hlj_posts_sku_key UNIQUE (sku);


--
-- Name: hook_templates hook_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hook_templates
    ADD CONSTRAINT hook_templates_pkey PRIMARY KEY (id);


--
-- Name: hooktemplates hooktemplates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hooktemplates
    ADD CONSTRAINT hooktemplates_pkey PRIMARY KEY (id);


--
-- Name: mecha_specs mecha_specs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mecha_specs
    ADD CONSTRAINT mecha_specs_pkey PRIMARY KEY (id);


--
-- Name: n8nexecutions n8nexecutions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.n8nexecutions
    ADD CONSTRAINT n8nexecutions_pkey PRIMARY KEY (id);


--
-- Name: news_backlog news_backlog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backlog
    ADD CONSTRAINT news_backlog_pkey PRIMARY KEY (id);


--
-- Name: post_queue_batch post_queue_batch_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post_queue_batch
    ADD CONSTRAINT post_queue_batch_pkey PRIMARY KEY (id);


--
-- Name: post_queue_import_log post_queue_import_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post_queue_import_log
    ADD CONSTRAINT post_queue_import_log_pkey PRIMARY KEY (id);


--
-- Name: post_queue post_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post_queue
    ADD CONSTRAINT post_queue_pkey PRIMARY KEY (id);


--
-- Name: post_queue_stg post_queue_stg_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post_queue_stg
    ADD CONSTRAINT post_queue_stg_pkey PRIMARY KEY (id);


--
-- Name: price_history price_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.price_history
    ADD CONSTRAINT price_history_pkey PRIMARY KEY (id);


--
-- Name: price_history price_history_sku_scraped_at_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.price_history
    ADD CONSTRAINT price_history_sku_scraped_at_key UNIQUE (sku, scraped_at);


--
-- Name: scraped_products products_bandai_sku_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scraped_products
    ADD CONSTRAINT products_bandai_sku_key UNIQUE (bandai_sku);


--
-- Name: scraped_products products_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scraped_products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: resolve_jobs resolve_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resolve_jobs
    ADD CONSTRAINT resolve_jobs_pkey PRIMARY KEY (id);


--
-- Name: scrape_logs scrape_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scrape_logs
    ADD CONSTRAINT scrape_logs_pkey PRIMARY KEY (id);


--
-- Name: store_prices store_prices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_prices
    ADD CONSTRAINT store_prices_pkey PRIMARY KEY (id);


--
-- Name: stores stores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_pkey PRIMARY KEY (id);


--
-- Name: stores stores_store_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_store_name_key UNIQUE (store_name);


--
-- Name: tracker_logs tracker_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tracker_logs
    ADD CONSTRAINT tracker_logs_pkey PRIMARY KEY (id);


--
-- Name: agent_drafts_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_drafts_created_at_idx ON public.agent_drafts USING btree (created_at DESC);


--
-- Name: agent_drafts_sku_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_drafts_sku_idx ON public.agent_drafts USING btree (sku);


--
-- Name: agent_drafts_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_drafts_status_idx ON public.agent_drafts USING btree (status);


--
-- Name: boxingposts_fight_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boxingposts_fight_idx ON public.boxingposts USING btree (fight_id);


--
-- Name: boxingposts_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boxingposts_status_idx ON public.boxingposts USING btree (status, generated_at DESC);


--
-- Name: documents_embedding_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_embedding_idx ON public.documents USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: fightlibrary_event_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fightlibrary_event_date_idx ON public.fightlibrary USING btree (event_date DESC);


--
-- Name: fightlibrary_fighters_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fightlibrary_fighters_idx ON public.fightlibrary USING btree (fighter_a, fighter_b);


--
-- Name: idx_catalog_attributes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_attributes ON public.gunpla_catalog USING gin (attributes jsonb_path_ops);


--
-- Name: idx_catalog_distribution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_distribution ON public.gunpla_catalog USING btree (distribution_type);


--
-- Name: idx_catalog_grade; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_grade ON public.gunpla_catalog USING btree (grade);


--
-- Name: idx_catalog_grade_distribution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_grade_distribution ON public.gunpla_catalog USING btree (grade, distribution_type);


--
-- Name: idx_catalog_grade_release; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_grade_release ON public.gunpla_catalog USING btree (grade, release_date DESC);


--
-- Name: idx_catalog_release_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_release_date ON public.gunpla_catalog USING btree (release_date DESC);


--
-- Name: idx_catalog_series; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_series ON public.gunpla_catalog USING btree (series);


--
-- Name: idx_catalog_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_catalog_sku ON public.gunpla_catalog USING btree (sku);


--
-- Name: idx_distribution_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distribution_type ON public.store_prices USING btree (distribution_type);


--
-- Name: idx_knowledge_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_embedding ON public.frameworkknowledge USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_post_queue_active_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_post_queue_active_sku ON public.post_queue USING btree (source_type, source_id) WHERE (status <> ALL (ARRAY['posted'::text, 'rejected'::text, 'archived'::text]));


--
-- Name: idx_post_queue_import_log_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_post_queue_import_log_created_at ON public.post_queue_import_log USING btree (created_at DESC);


--
-- Name: idx_post_queue_import_log_outcome; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_post_queue_import_log_outcome ON public.post_queue_import_log USING btree (outcome, created_at DESC);


--
-- Name: idx_post_queue_import_log_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_post_queue_import_log_source ON public.post_queue_import_log USING btree (source_type, source_id);


--
-- Name: idx_post_queue_stg_content_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_post_queue_stg_content_hash ON public.post_queue_stg USING btree (content_hash);


--
-- Name: idx_post_queue_stg_post_queue_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_post_queue_stg_post_queue_id ON public.post_queue_stg USING btree (post_queue_id);


--
-- Name: idx_post_queue_stg_publishable; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_post_queue_stg_publishable ON public.post_queue_stg USING btree (price_jpy DESC NULLS LAST) WHERE ((stg_status = ANY (ARRAY['ready'::text, 'raw'::text])) AND (affiliate_url IS NOT NULL));


--
-- Name: idx_post_queue_stg_stg_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_post_queue_stg_stg_status ON public.post_queue_stg USING btree (stg_status);


--
-- Name: idx_product_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_product_name ON public.gunpla_catalog USING btree (product_name);


--
-- Name: idx_products_bandai_sku; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_bandai_sku ON public.scraped_products USING btree (bandai_sku);


--
-- Name: idx_products_brand; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_brand ON public.scraped_products USING btree (brand);


--
-- Name: idx_products_grade; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_products_grade ON public.scraped_products USING btree (grade);


--
-- Name: idx_scrape_logs_store; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scrape_logs_store ON public.scrape_logs USING btree (store_name, scraped_at);


--
-- Name: idx_scraped_products_catalog_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scraped_products_catalog_id ON public.scraped_products USING btree (catalog_id);


--
-- Name: idx_store_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_store_name ON public.store_prices USING btree (store_name);


--
-- Name: idx_store_prices_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_store_prices_product_id ON public.store_prices USING btree (product_id);


--
-- Name: idx_store_prices_scraped_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_store_prices_scraped_at ON public.store_prices USING btree (scraped_at);


--
-- Name: idx_store_prices_store_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_store_prices_store_id ON public.store_prices USING btree (store_id);


--
-- Name: idx_tracker_logs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tracker_logs_status ON public.tracker_logs USING btree (status);


--
-- Name: idx_tracker_logs_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tracker_logs_timestamp ON public.tracker_logs USING btree ("timestamp");


--
-- Name: knowledge_embedding_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX knowledge_embedding_idx ON public.framework_knowledge USING ivfflat (embedding public.vector_cosine_ops);


--
-- Name: news_backlog_content_hash_uq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX news_backlog_content_hash_uq ON public.news_backlog USING btree (content_hash) WHERE (content_hash IS NOT NULL);


--
-- Name: news_backlog_embedding_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_backlog_embedding_idx ON public.news_backlog USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: news_backlog_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_backlog_status_idx ON public.news_backlog USING btree (status, content_type);


--
-- Name: price_history_sku_scraped_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX price_history_sku_scraped_idx ON public.price_history USING btree (sku, scraped_at DESC);


--
-- Name: resolve_jobs_backlog_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX resolve_jobs_backlog_idx ON public.resolve_jobs USING btree (backlog_id);


--
-- Name: resolve_jobs_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX resolve_jobs_status_idx ON public.resolve_jobs USING btree (status, created_at);


--
-- Name: boxingposts boxingposts_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER boxingposts_updated_at BEFORE UPDATE ON public.boxingposts FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: fightlibrary fightlibrary_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER fightlibrary_updated_at BEFORE UPDATE ON public.fightlibrary FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_backlog trg_news_backlog_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_news_backlog_update BEFORE UPDATE ON public.news_backlog FOR EACH ROW EXECUTE FUNCTION public.update_scraped_at();


--
-- Name: post_queue_stg trg_post_queue_stg_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_post_queue_stg_updated_at BEFORE UPDATE ON public.post_queue_stg FOR EACH ROW EXECUTE FUNCTION extensions.moddatetime('updated_at');


--
-- Name: gunpla_catalog update_gunpla_catalog_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_gunpla_catalog_updated_at BEFORE UPDATE ON public.gunpla_catalog FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: boxingposts boxingposts_fight_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boxingposts
    ADD CONSTRAINT boxingposts_fight_id_fkey FOREIGN KEY (fight_id) REFERENCES public.fightlibrary(id) ON DELETE CASCADE;


--
-- Name: boxingposts boxingposts_hook_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boxingposts
    ADD CONSTRAINT boxingposts_hook_template_id_fkey FOREIGN KEY (hook_template_id) REFERENCES public.hooktemplates(id);


--
-- Name: color_guide color_guide_bandai_manual_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.color_guide
    ADD CONSTRAINT color_guide_bandai_manual_id_fkey FOREIGN KEY (bandai_manual_id) REFERENCES public.bandai_kits(bandai_manual_id);


--
-- Name: mecha_specs mecha_specs_bandai_manual_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mecha_specs
    ADD CONSTRAINT mecha_specs_bandai_manual_id_fkey FOREIGN KEY (bandai_manual_id) REFERENCES public.bandai_kits(bandai_manual_id);


--
-- Name: post_queue post_queue_batch_queue_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.post_queue
    ADD CONSTRAINT post_queue_batch_queue_id_fkey FOREIGN KEY (batch_queue_id) REFERENCES public.post_queue_batch(id);


--
-- Name: resolve_jobs resolve_jobs_backlog_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resolve_jobs
    ADD CONSTRAINT resolve_jobs_backlog_id_fkey FOREIGN KEY (backlog_id) REFERENCES public.news_backlog(id);


--
-- Name: scraped_products scraped_products_catalog_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scraped_products
    ADD CONSTRAINT scraped_products_catalog_id_fkey FOREIGN KEY (catalog_id) REFERENCES public.gunpla_catalog(id) ON DELETE SET NULL;


--
-- Name: store_prices store_prices_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_prices
    ADD CONSTRAINT store_prices_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.scraped_products(id) ON DELETE CASCADE;


--
-- Name: store_prices store_prices_store_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.store_prices
    ADD CONSTRAINT store_prices_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);


--
-- Name: hlj_posts Allow anon on hlj_posts; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow anon on hlj_posts" ON public.hlj_posts USING (true) WITH CHECK (true);


--
-- Name: gunpla_catalog Allow insert on gunpla_catalog; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow insert on gunpla_catalog" ON public.gunpla_catalog FOR INSERT TO authenticated, anon, service_role WITH CHECK (true);


--
-- Name: store_prices Allow insert on store_prices; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow insert on store_prices" ON public.store_prices FOR INSERT TO authenticated, anon, service_role WITH CHECK (true);


--
-- Name: gunpla_catalog Public read gunpla_catalog; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Public read gunpla_catalog" ON public.gunpla_catalog FOR SELECT USING (true);


--
-- Name: scrape_logs Public read scrape_logs; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Public read scrape_logs" ON public.scrape_logs FOR SELECT USING (true);


--
-- Name: scraped_products Public read scraped_products; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Public read scraped_products" ON public.scraped_products FOR SELECT USING (true);


--
-- Name: store_prices Public read store_prices; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Public read store_prices" ON public.store_prices FOR SELECT USING (true);


--
-- Name: stores Public read stores; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Public read stores" ON public.stores FOR SELECT USING (true);


--
-- Name: crawler_state; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.crawler_state ENABLE ROW LEVEL SECURITY;

--
-- Name: fight_library; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.fight_library ENABLE ROW LEVEL SECURITY;

--
-- Name: framework_knowledge; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.framework_knowledge ENABLE ROW LEVEL SECURITY;

--
-- Name: frameworkknowledge; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.frameworkknowledge ENABLE ROW LEVEL SECURITY;

--
-- Name: hlj_posts; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.hlj_posts ENABLE ROW LEVEL SECURITY;

--
-- Name: hook_templates; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.hook_templates ENABLE ROW LEVEL SECURITY;

--
-- Name: n8nexecutions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.n8nexecutions ENABLE ROW LEVEL SECURITY;

--
-- Name: post_queue_import_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.post_queue_import_log ENABLE ROW LEVEL SECURITY;

--
-- Name: scrape_logs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.scrape_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: scraped_products; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.scraped_products ENABLE ROW LEVEL SECURITY;

--
-- Name: bandai_kits service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY service_role_all ON public.bandai_kits USING (true) WITH CHECK (true);


--
-- Name: color_guide service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY service_role_all ON public.color_guide USING (true) WITH CHECK (true);


--
-- Name: mecha_specs service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY service_role_all ON public.mecha_specs USING (true) WITH CHECK (true);


--
-- Name: stores; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;

--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA public TO service_role;


--
-- Name: FUNCTION assign_all_batches(p_max integer, p_message text); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.assign_all_batches(p_max integer, p_message text) TO anon;
GRANT ALL ON FUNCTION public.assign_all_batches(p_max integer, p_message text) TO authenticated;
GRANT ALL ON FUNCTION public.assign_all_batches(p_max integer, p_message text) TO service_role;


--
-- Name: FUNCTION assign_batch(p_max integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.assign_batch(p_max integer) TO anon;
GRANT ALL ON FUNCTION public.assign_batch(p_max integer) TO authenticated;
GRANT ALL ON FUNCTION public.assign_batch(p_max integer) TO service_role;


--
-- Name: FUNCTION check_repost_cooldown(p_source_type text, p_source_id text, p_days integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.check_repost_cooldown(p_source_type text, p_source_id text, p_days integer) TO anon;
GRANT ALL ON FUNCTION public.check_repost_cooldown(p_source_type text, p_source_id text, p_days integer) TO authenticated;
GRANT ALL ON FUNCTION public.check_repost_cooldown(p_source_type text, p_source_id text, p_days integer) TO service_role;


--
-- Name: FUNCTION import_post_queue(p_row jsonb); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.import_post_queue(p_row jsonb) TO anon;
GRANT ALL ON FUNCTION public.import_post_queue(p_row jsonb) TO authenticated;
GRANT ALL ON FUNCTION public.import_post_queue(p_row jsonb) TO service_role;


--
-- Name: FUNCTION import_post_queue_stg(p_row jsonb); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.import_post_queue_stg(p_row jsonb) TO anon;
GRANT ALL ON FUNCTION public.import_post_queue_stg(p_row jsonb) TO authenticated;
GRANT ALL ON FUNCTION public.import_post_queue_stg(p_row jsonb) TO service_role;


--
-- Name: FUNCTION import_post_queue_stg(p_row jsonb, p_repost_days integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.import_post_queue_stg(p_row jsonb, p_repost_days integer) TO anon;
GRANT ALL ON FUNCTION public.import_post_queue_stg(p_row jsonb, p_repost_days integer) TO authenticated;
GRANT ALL ON FUNCTION public.import_post_queue_stg(p_row jsonb, p_repost_days integer) TO service_role;


--
-- Name: FUNCTION match_documents(query_embedding public.vector, match_threshold double precision, match_count integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.match_documents(query_embedding public.vector, match_threshold double precision, match_count integer) TO anon;
GRANT ALL ON FUNCTION public.match_documents(query_embedding public.vector, match_threshold double precision, match_count integer) TO authenticated;
GRANT ALL ON FUNCTION public.match_documents(query_embedding public.vector, match_threshold double precision, match_count integer) TO service_role;


--
-- Name: FUNCTION match_gunpla(query_emb public.vector, threshold double precision, match_count integer); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.match_gunpla(query_emb public.vector, threshold double precision, match_count integer) TO anon;
GRANT ALL ON FUNCTION public.match_gunpla(query_emb public.vector, threshold double precision, match_count integer) TO authenticated;
GRANT ALL ON FUNCTION public.match_gunpla(query_emb public.vector, threshold double precision, match_count integer) TO service_role;


--
-- Name: FUNCTION match_scraped_to_catalog(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.match_scraped_to_catalog() TO anon;
GRANT ALL ON FUNCTION public.match_scraped_to_catalog() TO authenticated;
GRANT ALL ON FUNCTION public.match_scraped_to_catalog() TO service_role;


--
-- Name: FUNCTION set_updated_at(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.set_updated_at() TO anon;
GRANT ALL ON FUNCTION public.set_updated_at() TO authenticated;
GRANT ALL ON FUNCTION public.set_updated_at() TO service_role;


--
-- Name: FUNCTION update_scraped_at(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.update_scraped_at() TO anon;
GRANT ALL ON FUNCTION public.update_scraped_at() TO authenticated;
GRANT ALL ON FUNCTION public.update_scraped_at() TO service_role;


--
-- Name: FUNCTION update_updated_at_column(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.update_updated_at_column() TO anon;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO authenticated;
GRANT ALL ON FUNCTION public.update_updated_at_column() TO service_role;


--
-- Name: TABLE agent_drafts; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.agent_drafts TO anon;
GRANT ALL ON TABLE public.agent_drafts TO authenticated;
GRANT ALL ON TABLE public.agent_drafts TO service_role;


--
-- Name: TABLE app_config; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.app_config TO anon;
GRANT ALL ON TABLE public.app_config TO authenticated;
GRANT ALL ON TABLE public.app_config TO service_role;


--
-- Name: TABLE bandai_kits; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.bandai_kits TO anon;
GRANT ALL ON TABLE public.bandai_kits TO authenticated;
GRANT ALL ON TABLE public.bandai_kits TO service_role;


--
-- Name: SEQUENCE bandai_kits_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.bandai_kits_id_seq TO anon;
GRANT ALL ON SEQUENCE public.bandai_kits_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.bandai_kits_id_seq TO service_role;


--
-- Name: TABLE boxingposts; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.boxingposts TO anon;
GRANT ALL ON TABLE public.boxingposts TO authenticated;
GRANT ALL ON TABLE public.boxingposts TO service_role;


--
-- Name: TABLE color_guide; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.color_guide TO anon;
GRANT ALL ON TABLE public.color_guide TO authenticated;
GRANT ALL ON TABLE public.color_guide TO service_role;


--
-- Name: SEQUENCE color_guide_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.color_guide_id_seq TO anon;
GRANT ALL ON SEQUENCE public.color_guide_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.color_guide_id_seq TO service_role;


--
-- Name: TABLE country_channels; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.country_channels TO anon;
GRANT ALL ON TABLE public.country_channels TO authenticated;
GRANT ALL ON TABLE public.country_channels TO service_role;


--
-- Name: TABLE crawler_state; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.crawler_state TO anon;
GRANT ALL ON TABLE public.crawler_state TO authenticated;
GRANT ALL ON TABLE public.crawler_state TO service_role;


--
-- Name: TABLE documents; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.documents TO anon;
GRANT ALL ON TABLE public.documents TO authenticated;
GRANT ALL ON TABLE public.documents TO service_role;


--
-- Name: SEQUENCE documents_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.documents_id_seq TO anon;
GRANT ALL ON SEQUENCE public.documents_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.documents_id_seq TO service_role;


--
-- Name: TABLE exchange_rates; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.exchange_rates TO anon;
GRANT ALL ON TABLE public.exchange_rates TO authenticated;
GRANT ALL ON TABLE public.exchange_rates TO service_role;


--
-- Name: TABLE fight_library; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.fight_library TO anon;
GRANT ALL ON TABLE public.fight_library TO authenticated;
GRANT ALL ON TABLE public.fight_library TO service_role;


--
-- Name: TABLE fightlibrary; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.fightlibrary TO anon;
GRANT ALL ON TABLE public.fightlibrary TO authenticated;
GRANT ALL ON TABLE public.fightlibrary TO service_role;


--
-- Name: TABLE framework_knowledge; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.framework_knowledge TO anon;
GRANT ALL ON TABLE public.framework_knowledge TO authenticated;
GRANT ALL ON TABLE public.framework_knowledge TO service_role;


--
-- Name: SEQUENCE framework_knowledge_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.framework_knowledge_id_seq TO anon;
GRANT ALL ON SEQUENCE public.framework_knowledge_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.framework_knowledge_id_seq TO service_role;


--
-- Name: TABLE frameworkknowledge; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.frameworkknowledge TO anon;
GRANT ALL ON TABLE public.frameworkknowledge TO authenticated;
GRANT ALL ON TABLE public.frameworkknowledge TO service_role;


--
-- Name: SEQUENCE frameworkknowledge_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.frameworkknowledge_id_seq TO anon;
GRANT ALL ON SEQUENCE public.frameworkknowledge_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.frameworkknowledge_id_seq TO service_role;


--
-- Name: TABLE gunpla_catalog; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.gunpla_catalog TO anon;
GRANT ALL ON TABLE public.gunpla_catalog TO authenticated;
GRANT ALL ON TABLE public.gunpla_catalog TO service_role;


--
-- Name: TABLE hlj_posts; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hlj_posts TO anon;
GRANT ALL ON TABLE public.hlj_posts TO authenticated;
GRANT ALL ON TABLE public.hlj_posts TO service_role;


--
-- Name: TABLE hlj_posts_bk_411; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hlj_posts_bk_411 TO anon;
GRANT ALL ON TABLE public.hlj_posts_bk_411 TO authenticated;
GRANT ALL ON TABLE public.hlj_posts_bk_411 TO service_role;


--
-- Name: SEQUENCE hlj_posts_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.hlj_posts_id_seq TO anon;
GRANT ALL ON SEQUENCE public.hlj_posts_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.hlj_posts_id_seq TO service_role;


--
-- Name: TABLE hook_templates; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hook_templates TO anon;
GRANT ALL ON TABLE public.hook_templates TO authenticated;
GRANT ALL ON TABLE public.hook_templates TO service_role;


--
-- Name: SEQUENCE hook_templates_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.hook_templates_id_seq TO anon;
GRANT ALL ON SEQUENCE public.hook_templates_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.hook_templates_id_seq TO service_role;


--
-- Name: TABLE hooktemplates; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.hooktemplates TO anon;
GRANT ALL ON TABLE public.hooktemplates TO authenticated;
GRANT ALL ON TABLE public.hooktemplates TO service_role;


--
-- Name: TABLE mecha_specs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.mecha_specs TO anon;
GRANT ALL ON TABLE public.mecha_specs TO authenticated;
GRANT ALL ON TABLE public.mecha_specs TO service_role;


--
-- Name: SEQUENCE mecha_specs_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.mecha_specs_id_seq TO anon;
GRANT ALL ON SEQUENCE public.mecha_specs_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.mecha_specs_id_seq TO service_role;


--
-- Name: TABLE n8nexecutions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.n8nexecutions TO anon;
GRANT ALL ON TABLE public.n8nexecutions TO authenticated;
GRANT ALL ON TABLE public.n8nexecutions TO service_role;


--
-- Name: SEQUENCE n8nexecutions_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.n8nexecutions_id_seq TO anon;
GRANT ALL ON SEQUENCE public.n8nexecutions_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.n8nexecutions_id_seq TO service_role;


--
-- Name: TABLE news_backlog; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.news_backlog TO anon;
GRANT ALL ON TABLE public.news_backlog TO authenticated;
GRANT ALL ON TABLE public.news_backlog TO service_role;


--
-- Name: SEQUENCE news_backlog_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.news_backlog_id_seq TO anon;
GRANT ALL ON SEQUENCE public.news_backlog_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.news_backlog_id_seq TO service_role;


--
-- Name: TABLE post_queue; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.post_queue TO anon;
GRANT ALL ON TABLE public.post_queue TO authenticated;
GRANT ALL ON TABLE public.post_queue TO service_role;


--
-- Name: TABLE post_queue_batch; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.post_queue_batch TO anon;
GRANT ALL ON TABLE public.post_queue_batch TO authenticated;
GRANT ALL ON TABLE public.post_queue_batch TO service_role;


--
-- Name: TABLE post_queue_import_log; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.post_queue_import_log TO anon;
GRANT ALL ON TABLE public.post_queue_import_log TO authenticated;
GRANT ALL ON TABLE public.post_queue_import_log TO service_role;


--
-- Name: SEQUENCE post_queue_import_log_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.post_queue_import_log_id_seq TO anon;
GRANT ALL ON SEQUENCE public.post_queue_import_log_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.post_queue_import_log_id_seq TO service_role;


--
-- Name: TABLE post_queue_stg; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.post_queue_stg TO anon;
GRANT ALL ON TABLE public.post_queue_stg TO authenticated;
GRANT ALL ON TABLE public.post_queue_stg TO service_role;


--
-- Name: TABLE post_queue_stg_sorted; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.post_queue_stg_sorted TO anon;
GRANT ALL ON TABLE public.post_queue_stg_sorted TO authenticated;
GRANT ALL ON TABLE public.post_queue_stg_sorted TO service_role;


--
-- Name: TABLE price_history; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.price_history TO anon;
GRANT ALL ON TABLE public.price_history TO authenticated;
GRANT ALL ON TABLE public.price_history TO service_role;


--
-- Name: TABLE resolve_jobs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.resolve_jobs TO anon;
GRANT ALL ON TABLE public.resolve_jobs TO authenticated;
GRANT ALL ON TABLE public.resolve_jobs TO service_role;


--
-- Name: TABLE scrape_logs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.scrape_logs TO anon;
GRANT ALL ON TABLE public.scrape_logs TO authenticated;
GRANT ALL ON TABLE public.scrape_logs TO service_role;


--
-- Name: TABLE scraped_products; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.scraped_products TO anon;
GRANT ALL ON TABLE public.scraped_products TO authenticated;
GRANT ALL ON TABLE public.scraped_products TO service_role;


--
-- Name: TABLE store_prices; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.store_prices TO anon;
GRANT ALL ON TABLE public.store_prices TO authenticated;
GRANT ALL ON TABLE public.store_prices TO service_role;


--
-- Name: TABLE stores; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.stores TO anon;
GRANT ALL ON TABLE public.stores TO authenticated;
GRANT ALL ON TABLE public.stores TO service_role;


--
-- Name: TABLE tracker_logs; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.tracker_logs TO anon;
GRANT ALL ON TABLE public.tracker_logs TO authenticated;
GRANT ALL ON TABLE public.tracker_logs TO service_role;


--
-- Name: SEQUENCE tracker_logs_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.tracker_logs_id_seq TO anon;
GRANT ALL ON SEQUENCE public.tracker_logs_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.tracker_logs_id_seq TO service_role;


--
-- Name: TABLE vw_availability_status; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.vw_availability_status TO anon;
GRANT ALL ON TABLE public.vw_availability_status TO authenticated;
GRANT ALL ON TABLE public.vw_availability_status TO service_role;


--
-- Name: TABLE vw_latest_prices; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.vw_latest_prices TO anon;
GRANT ALL ON TABLE public.vw_latest_prices TO authenticated;
GRANT ALL ON TABLE public.vw_latest_prices TO service_role;


--
-- Name: TABLE vw_price_comparison; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.vw_price_comparison TO anon;
GRANT ALL ON TABLE public.vw_price_comparison TO authenticated;
GRANT ALL ON TABLE public.vw_price_comparison TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO service_role;


--
-- PostgreSQL database dump complete
--

