-- Argument list changed (added p_source_type), so CREATE OR REPLACE would add a
-- second overload rather than replace. Both would then match a 2-arg call and
-- Postgres would reject it as ambiguous. Drop the old identity first.
DROP FUNCTION IF EXISTS public.assign_all_batches(integer, text);

CREATE OR REPLACE FUNCTION public.assign_all_batches(p_max integer DEFAULT 10, p_message text DEFAULT NULL::text, p_source_type text DEFAULT NULL::text)
 RETURNS TABLE(batch_id uuid, message text, copy_message text, attached_media jsonb)
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_batch_id uuid;
  v_remaining INT;
  v_status text;
BEGIN
  v_status := 'pending';
  LOOP
    SELECT COUNT(*) INTO v_remaining
    FROM post_queue
    WHERE status = v_status AND batch_queue_id IS NULL
      AND (p_source_type IS NULL OR source_type = p_source_type);
    EXIT WHEN v_remaining = 0;
    v_batch_id := gen_random_uuid();
    INSERT INTO post_queue_batch (id, message)
    VALUES (v_batch_id, p_message);
    UPDATE post_queue
    SET batch_queue_id = v_batch_id
    WHERE id IN (
      SELECT id FROM post_queue
      WHERE status = v_status AND batch_queue_id IS NULL
        AND (p_source_type IS NULL OR source_type = p_source_type)
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
$function$