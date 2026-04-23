CREATE OR REPLACE FUNCTION public.import_post_queue_stg(p_row jsonb, p_repost_days integer DEFAULT 30)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  v_result             jsonb;
  v_recently_posted    boolean := false;
  v_last_posted_at     timestamptz;
  v_existing_stg_id    uuid;
BEGIN

  -- ============================================================
  -- REPOST COOLDOWN CHECK
  -- Join post_queue → batch_queue to get real posted_at
  -- because post_queue.posted_at is not written back (always null),
  -- but batch_queue.posted_at IS populated when the batch completes.
  -- ============================================================
  IF p_repost_days > 0 THEN
    SELECT bq.posted_at INTO v_last_posted_at
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

  -- ============================================================
  -- INSERT INTO STAGING (idempotent via content_hash)
  -- ============================================================
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
    stock
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
    p_row->>'stock'
  )
  ON CONFLICT (content_hash) DO NOTHING
  RETURNING to_jsonb(post_queue_stg.*) INTO v_result;

  -- Duplicate hash: fetch existing stg row for debugging
  IF v_result IS NULL THEN
    SELECT to_jsonb(post_queue_stg.*) INTO v_result
    FROM public.post_queue_stg
    WHERE content_hash = p_row->>'content_hash';

    RETURN jsonb_build_object(
      'inserted',            false,
      'reason',              'duplicate_hash',
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
$function$
