CREATE OR REPLACE FUNCTION public.import_post_queue(p_row jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
  v_result jsonb;
BEGIN
  INSERT INTO post_queue (
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
  VALUES (
    (p_row->>'batch_queue_id')::uuid,
    p_row->>'source_type',
    p_row->>'source_id',
    p_row->>'post_copy',
    (p_row->'image_urls'),
    p_row->>'affiliate_url',
    COALESCE(p_row->>'status', 'new'),
    p_row->>'channel',
    (p_row->>'urgency')::int,
    p_row->>'tier',
    (p_row->'tags')
  )
  ON CONFLICT (source_type, source_id)
  WHERE status NOT IN ('posted', 'rejected', 'archived')
  DO NOTHING
  RETURNING to_jsonb(post_queue.*) INTO v_result;

  -- Return inserted row or empty object if duplicate was skipped
  RETURN COALESCE(v_result, '{}'::jsonb);
END;
$function$