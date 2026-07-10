-- Hardening applied after restore (Phase 4 of the self-host migration).
-- Every writer authenticates as service_role (bypasses RLS), so
-- RLS-with-no-policy is deliberate deny-by-default for anon.
-- The pre-existing "Public read" policies on gunpla_catalog / store_prices
-- activate when RLS turns on and keep working.

ALTER TABLE public.agent_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.app_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bandai_kits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.boxingposts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.color_guide ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.country_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exchange_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fightlibrary ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gunpla_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hlj_posts_bk_411 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hooktemplates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mecha_specs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.news_backlog ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_queue_batch ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_queue_stg ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.price_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resolve_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.store_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tracker_logs ENABLE ROW LEVEL SECURITY;

-- anon must not be able to call the write-path RPCs.
-- PUBLIC must be revoked too: Postgres grants EXECUTE to PUBLIC on new
-- functions, and these are SECURITY DEFINER, so EXECUTE is the only gate.
REVOKE EXECUTE ON FUNCTION public.import_post_queue(jsonb)             FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.import_post_queue_stg(jsonb)         FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.import_post_queue_stg(jsonb,integer) FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.match_scraped_to_catalog()           FROM PUBLIC, anon;

-- service_role and postgres keep explicit EXECUTE.
GRANT EXECUTE ON FUNCTION public.import_post_queue(jsonb)              TO service_role;
GRANT EXECUTE ON FUNCTION public.import_post_queue_stg(jsonb)          TO service_role;
GRANT EXECUTE ON FUNCTION public.import_post_queue_stg(jsonb,integer)  TO service_role;
GRANT EXECUTE ON FUNCTION public.match_scraped_to_catalog()            TO service_role;
