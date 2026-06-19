-- check_repost_cooldown(source_type, source_id, days)
-- ============================================================================
-- READ-ONLY cooldown check for the Claude Agent SDK low-stock pipeline
-- (scripts/lowstock_agent/checks/dedup.py). Reuses the exact join logic from
-- import_post_queue_stg.sql (post_queue -> post_queue_batch on the real
-- posted_at), but performs NO inserts — it only reports whether a SKU was
-- posted within the cooldown window. The agent must never write to the n8n
-- tables; this function lets it read the dedup state without touching them.
--
-- Note: posted low-stock items live in post_queue with source_type = 'hlj'
-- and source_id = SKU.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.check_repost_cooldown(
    p_source_type text,
    p_source_id   text,
    p_days        integer DEFAULT 30
)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $function$
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
$function$;
