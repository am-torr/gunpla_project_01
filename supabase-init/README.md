# supabase-init — self-hosted database bootstrap

Captured from Supabase Cloud project `xrtfyzegmyyazuwntkph` on 2026-07-10 via the
session pooler (`pg_dump` 17.5). Restores into `supabase/postgres:17.6.1.143`.

**Do not mount this dir into `/docker-entrypoint-initdb.d`** — the supabase/postgres
image runs its own role/extension init and ordering is not guaranteed. Apply
manually, in order, after `docker compose up -d supabase`:

```bash
docker cp supabase-init gunpla-supabase:/tmp/init

# 1. Extensions (superuser)
docker exec gunpla-supabase psql -U supabase_admin -h localhost -d postgres \
  -v ON_ERROR_STOP=1 -f /tmp/init/00-extensions.sql

# 2. Schema (as postgres, to keep cloud-like ownership).
#    Expected: exactly 12 "permission denied to change default privileges"
#    errors on the ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin lines.
docker exec gunpla-supabase bash -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -U postgres -h localhost -d postgres -f /tmp/init/10-schema.sql'

# 2b. Re-run those 12 lines as superuser:
grep "^ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin" supabase-init/10-schema.sql \
  | docker exec -i gunpla-supabase psql -U supabase_admin -h localhost -d postgres

# 3. Data (superuser — the dump uses DISABLE TRIGGER ALL)
docker exec gunpla-supabase psql -U supabase_admin -h localhost -d postgres -f /tmp/init/20-data.sql

# 4. RLS hardening + RPC revokes
docker exec gunpla-supabase psql -U supabase_admin -h localhost -d postgres \
  -v ON_ERROR_STOP=1 -f /tmp/init/30-rls.sql

# 5. REQUIRED: the image does NOT sync the authenticator password to
#    POSTGRES_PASSWORD; PostgREST will crash-loop with auth failures until:
docker exec gunpla-supabase bash -c \
  "psql -U supabase_admin -h localhost -d postgres -c \"ALTER ROLE authenticator WITH LOGIN PASSWORD '\$POSTGRES_PASSWORD';\""
docker compose restart rest
```

Keys: self-hosted anon/service_role JWTs are HS256 tokens signed with `JWT_SECRET`
from `.env` (`{"role":"anon"|"service_role","iss":"supabase","iat":…,"exp":…}`).
PostgREST validates them via `PGRST_JWT_SECRET`; Kong is only a router.
