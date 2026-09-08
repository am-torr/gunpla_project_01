# Hermes -> n8n -> MEGALLANICA Facebook Integration -- Handoff / Status

Full design plan: `C:\Users\amtor\.claude\plans\elxplore-agent-c-users-amtor-claude-plan-peaceful-moore.md`
(context, architecture diagram, and verification steps live there -- this file is the
implementation status + the one remaining live-system patch that needs your sign-off).

> **2026-07-10 UPDATE: APPLIED.** Everything below was executed on 2026-07-10 after the user
> refreshed `N8N_API_KEY` and gave the go-ahead. Migration applied to the LOCAL self-host PG
> (the live one n8n uses via `http://kong:8000` -- NOT the cloud project this doc originally
> named). `03` + 2 inactive FB B workflows pinned (4 call sites), `02` patched (3 changes;
> false branch got its own self-contained no-image tail because `Prepare post_queue Update
> Payload` references `$('Assemble Post Record')` by name, which throws for unexecuted nodes),
> `Hermes News Webhook Ingest` imported+active (id `T3USh9UH6qJmiXXW`; needed a `webhookId` on
> the webhook node or n8n 2.8.3 registers only the namespaced path), `03b` imported INACTIVE
> (id `uWftoeBQEneqnnWY`), `jobs.json` patched (survived the cron daemon's rewrite),
> `HERMES_WEBHOOK_SECRET` on the n8n container + `N8N_WEBHOOK_URL`/`N8N_WEBHOOK_SECRET` in
> Hermes's `.env` (URL uses `host.docker.internal:5679` -- Hermes's terminal backend is a
> docker sandbox, so the doc's `localhost` URL would not have worked), and
> `required_environment_variables` added to gunpla-news-gatherer's SKILL.md frontmatter so the
> sandbox env passthrough allows the two vars. End-to-end verified: webhook 401s without the
> secret, stages via `import_post_queue_stg` with it, dedups on replay, and `post_to_n8n.py`
> run from inside the hermes sandbox delivered a row (test rows deleted afterwards).
>
> **2026-07-10 UPDATE 2 — INTERRUPTED mid-credential-fix.** *(SUPERSEDED — all resume steps
> completed in UPDATE 3 below; kept for the credential-trap context.)*
>
> There are **TWO credentials both named "Header Auth account"** — this trap ate several fix
> attempts. State as of 2026-07-10 ~09:20 UTC (17:20 local):
>
> - `CCpTP1R9jjMOly5T` (created Apr 12) — referenced by **all 9 RPC nodes** incl. ACTIVE
>   `01`/`02`/`03`. BROKEN: echo-capture shows it sends header `apikey: =Bearer=<key>`
>   (wrong name AND malformed value) -> requests silently downgrade to anon (200 + empty,
>   no 401), so failures are quiet.
> - `7hIWq6VNQXDObo7j` (created Apr 17) — referenced only by 3 INACTIVE legacy workflows.
>   User fixed its VALUE (echo-verified: exact `Bearer <local service-role key>`), but its
>   header NAME is still `apikey`, and the attempted rename never saved (DB updatedAt stuck
>   at 08:21:45Z).
>
> **Resume steps (in order):**
> 1. n8n UI: open the credential whose browser URL contains `7hIWq6VNQXDObo7j` (NOT the CCpT
>    one), change the **Name** field `apikey` -> `Authorization`, leave Value untouched,
>    **click Save**.
> 2. Verify what it actually sends before trusting it: temp workflow (webhook trigger with a
>    `webhookId`, responseMode lastNode) -> HTTP GET `http://host.docker.internal:<port>` with
>    ONLY this credential attached, against a local header-echo listener. Expect exactly
>    `Authorization: Bearer <SUPABASE_SERVICE_ROLE_KEY from .env>`. Delete temp workflow after.
> 3. Repoint every `httpHeaderAuth` reference `CCpTP1R9jjMOly5T` -> `7hIWq6VNQXDObo7j` across
>    all workflows via the public API (GET each workflow, swap `credentials.httpHeaderAuth.id`,
>    PUT back with `settings` filtered to the API allowlist — extra keys 400 otherwise).
>    9 nodes across 8 workflows; the ACTIVE three are `01` low-stock (Insert Staging Records),
>    `02` (Insert post_queue Record), `03` (Assign Batch Queue Items).
> 4. Read-test through the repointed credential: GET `/rest/v1/post_queue?select=id&limit=1`
>    via a temp workflow -> expect **1 row**; `[]` means still anon; then delete temp workflow.
> 5. Watch `01`'s next 4-hourly tick go green end-to-end, re-run the Hermes webhook curl test,
>    THEN decide on activating `03b` (`uWftoeBQEneqnnWY`, still inactive by design).
> 6. Cosmetic but important: rename/delete the broken `CCpT...` credential afterwards so the
>    duplicate-name trap can't recur.
>
> Also still unverified: the `supabaseApi` credential "Supabase account" (`OZZlfyiNQsAVjZxj`,
> untouched since 2026-03-03) — if its host still points at the cloud project, every
> n8n-nodes-base.supabase node (02/04 updates) writes to the WRONG database post-cutover.
> Check its Host in the UI: should be `http://kong:8000`, secret = raw local service-role key
> (no Bearer prefix).
>
> Note: `gunpla-news-gatherer` SKILL.md was expanded (2026-07-10) — Working Data now mandates
> `confidence`, `source_tier`, `ImageURL1/2/3` fields, which confirms the ingest's extraction
> keys and strengthens the deferred confidence-gate plan below. The
> `required_environment_variables` block (N8N_WEBHOOK_URL/SECRET) survived the edit.
> Related latent bug left in place in `01`/`02`/`03`: manual `Authorization` headers stored as
> `==Bearer {{ ... }}` render as literal `=Bearer ...`; they only work because the credential
> header overrides them -- keep the credential or fix the headers when touching those nodes.
>
> **DEFERRED FOLLOW-UPS (user-approved plan, 2026-07-10 — not yet built):**
> 1. *Persist `working_data`* — ingest workflow currently discards the Working Data JSON after
>    extracting `ImageURL1-3`; stash it on the stg row (`ai_notes`, or a `working_data jsonb`
>    column) so confidence/source metadata is auditable.
> 2. *Confidence gate* — after (1), hold briefs containing low-tier/RUMOR rows at a review
>    status (`stg_status='review'`) instead of auto-staging toward Facebook.
> 3. *Custom image path* — Hermes-generated graphics / user photos are Discord attachments and
>    never reach the pipeline (Discord CDN URLs expire — do not use them). Plan: Hermes uploads
>    to imgbb (`IMGBB_API_KEY` in tracker `.env`) during the cron run, writes the URL into a
>    `CustomImageURL` column, and the ingest's extraction list gains that key.
> 4. *First-real-run check* — confirm the Working Data table headers Hermes actually emits match
>    the ingest's exact extraction keys `ImageURL1`/`ImageURL2`/`ImageURL3`.

> **2026-07-10 UPDATE 3 — CREDENTIAL FIX COMPLETED (~12:00 UTC).** All UPDATE-2 resume steps done,
> plus the unverified `supabaseApi` credential turned out to be a real second defect and was fixed.
>
> - **Step 1 (done, different route):** the n8n UI wasn't needed. `n8n import:credentials` inside
>   the container upserts by id, so `7hIWq6VNQXDObo7j` was updated in place from `.env` values:
>   header name `Authorization`, value `Bearer <local SR key>`, renamed to
>   **"Supabase SR (Authorization header)"** (also kills the duplicate-name trap). Import preserves
>   `updatedAt` — don't use that column to detect this change.
> - **Step 2 (done):** echo-verified via temp workflow against an in-container listener — sends
>   exactly `Authorization: Bearer <local service-role key>`, **no** `apikey` header, exact match
>   to `.env` confirmed programmatically. Temp workflow + listener removed.
> - **Step 3 (done):** all 9 `CCpTP1R9jjMOly5T` references across 8 workflows repointed to
>   `7hIWq6VNQXDObo7j` via the public API (PUT 200 each; settings filtered to the allowlist).
>   Re-scan shows **zero** remaining references. Active `01`/`02`/`03` stayed active.
> - **Step 4 (done):** `GET /rest/v1/post_queue?select=id&limit=1` through the credential via
>   `kong:8000` returned a real row (ground truth: 378 rows) — service-role confirmed, and the
>   running n8n picked up the imported credential without a restart.
> - **Step 6 (done):** `CCpTP1R9jjMOly5T` renamed in the DB (name column is not encrypted) to
>   **"ZZ BROKEN apikey header (do not use)"**. Not deleted — delete whenever.
> - **`supabaseApi` credential (`OZZlfyiNQsAVjZxj`) WAS pointing at the cloud project**
>   (`https://xrtfyzegmyyazuwntkph.supabase.co`, untouched since 2026-03-03) — i.e. every
>   `n8n-nodes-base.supabase` node incl. ACTIVE `02`/`04` was reading/writing the CLOUD DB
>   post-cutover. Fixed in place via the same import: host `http://kong:8000`, serviceRole = raw
>   local key, renamed **"Supabase account (local kong)"**. All ~30 referencing nodes (active and
>   legacy) now hit local.
> - **Hermes webhook re-test (done):** no secret → 401; with secret → 200 `inserted:true`; replay
>   → `duplicate_hash` dedup. Test stg row deleted from local PG afterwards.
> - **Discovery — dead schedules:** `02` (hourly :30) and `03` (2-hourly :03) had fired **zero**
>   times since ~2026-07-09 16:00 UTC; `01`'s last three runs (07-09) errored at
>   `Fetch HLJ Low-Stock Feed` (lowstock container was unreachable; it's up now — unrelated to
>   credentials). The repoint PUTs at 11:49 UTC cycled deactivate→activate on `01`/`02`/`03`,
>   re-registering their triggers. If schedules die silently again after container restarts,
>   suspect this pattern and cycle the workflows.
> - Ingest + `03b` use **manual headers** (single-`=` expressions → render correctly), not the
>   header-auth credential; they were never affected by the broken credential.
> - **Hygiene recommendation (user action):** `/home/node/.n8n/decrypted-creds.json` and
>   `all-credentials.json` from an April debug session still sit in the container volume with
>   decrypted/exported credential data — delete them.
> - `03b` (`uWftoeBQEneqnnWY`) remains **inactive by design** — activating real Facebook posting
>   stays the user's call.

## What's been built (files on disk now)

| File | Status |
|---|---|
| `C:\Users\hermes\AppData\Local\hermes\skills\productivity\gunpla-news-gatherer\scripts\post_to_n8n.py` | Written. Inert until `jobs.json` references it (see below). |
| `D:\project\gunpla-tracker-verified\m-hub-db\database\function\assign_all_batches.sql` | Repo file updated (adds `p_source_type` param, **plus a required `DROP FUNCTION` -- see Corrections**). **Not yet applied** to the live Supabase project. |
| `D:\project\gunpla-tracker-verified\workflows\new\hermes-news-webhook-ingest.json` | New workflow, ready to import. **Not yet imported** into live n8n. |
| `D:\project\gunpla-tracker-verified\workflows\new\03b-batch-and-publish-hermes-news.json` | New workflow, `active:false` by design (this is the one piece that actually posts to Facebook). **Not yet imported.** |
| `D:\project\gunpla-tracker-verified\workflows\new\02-patch-notes.md` | Diff for the existing `02` workflow (2 required node edits + 1 bug fix for stuck image-less rows). **Not yet applied.** |
| `D:\project\gunpla-tracker-verified\workflows\new\03-patch-notes.md` | **NEW, and required.** Pins `03` to `source_type='hlj'`. Without it `03` steals Hermes rows. **Not yet applied.** |
| This file (`hermes-jobs-patch-notes.md`) | The `jobs.json` diff, below. **Not yet applied.** |

## Why nothing live has been touched yet

- Applying the Supabase migration was **blocked by the auto-mode safety classifier** the one time
  I tried it directly -- it's a live-DB change to the production Facebook-posting pipeline and
  needs your explicit review first.
- Importing/editing the live n8n workflows requires the n8n REST API -- `.env`'s `N8N_API_KEY` is
  **stale (401 Unauthorized)** against the running instance. Either generate a fresh key in n8n's
  Settings -> API and hand it to me, or import the two JSON files / apply the `02` patch manually
  via the n8n editor UI.
- Editing Hermes's live `cron\jobs.json` (below) is a real, already-scheduled, unattended system --
  left for your explicit go-ahead rather than applied automatically.

---

# Corrections found on review (2026-07-10)

Two defects in the plan as originally written. Both were verified against the repo and the
`workflows-export.json` snapshot; neither required touching a live system to establish.

## 1. The SQL migration would have broken the live HLJ pipeline

`CREATE OR REPLACE FUNCTION` keys on the function's *argument types*. Adding `p_source_type`
changes the identity from `assign_all_batches(integer, text)` to
`assign_all_batches(integer, text, text)`, so the statement **creates a second overload instead of
replacing the first**. Both then exist.

Live `03` POSTs named args `{"p_max": ..., "p_message": ...}`, and at least one other call site
sends `{"p_max": ...}` alone. Every one of those calls matches *both* overloads (the 3-arg one via
its `DEFAULT NULL`), so Postgres rejects them as ambiguous -- `function ... is not unique` -- and
Facebook posting stops.

Fixed in `assign_all_batches.sql` by dropping the old identity first:

```sql
DROP FUNCTION IF EXISTS public.assign_all_batches(integer, text);
```

The plan's claim of "zero regression risk to the working HLJ flow" was wrong.

## 2. `03` must be pinned to `hlj`, or it will steal Hermes rows

`p_source_type => NULL` means *no filter*, not *hlj only*. `03` runs at :03/:20 and `03b` at :45,
so once `hermes_news` rows reach `status='pending'`, `03` claims them first and `string_agg`s each
brief into an HLJ batch post -- the precise failure `03b` exists to prevent.

See `03-patch-notes.md`. The `03` patch and the SQL migration **must ship in the same maintenance
window**; either one alone breaks posting.

## Blocker status (re-verified 2026-07-10)

- n8n container is up (`/healthz` -> 200), but `N8N_API_KEY` still returns **401**. Confirmed
  stale. Import via the editor UI.
- Supabase project `xrtfyzegmyyazuwntkph` is `ACTIVE_HEALTHY` and reachable over MCP, but the
  auto-mode safety classifier blocks **all** direct queries to it -- including read-only ones --
  absent an explicit permission grant. The migration remains unapplied for that reason, not a
  technical one.

---

# Patch: Hermes `cron\jobs.json` -- NOT YET APPLIED

File: `C:\Users\hermes\AppData\Local\hermes\cron\jobs.json`

This edits Hermes's **live, currently-scheduled** cron config (two active jobs, one of which has
already run successfully once). Left un-applied deliberately -- this is exactly the kind of
"modify a live, unattended, shared system" action that should get your explicit sign-off first,
same reasoning as the Supabase migration below.

Append one sentence to the end of the `prompt` field for jobs `903a7fc54a52`
("Monthly Gundam Base Roundup") and `be6ef51056fc` ("Weekly Gundam Base Country Highlight").
Everything else in both jobs (`schedule`, `deliver: "origin"`, `skills`, `state`) stays exactly as
it is today -- Discord delivery is completely unaffected by this change.

Append to both prompts, after the existing final sentence:

```
After generating the brief, run scripts/export_json.py on the Working Data table to produce
data.json, then run scripts/post_to_n8n.py --brief-file brief.txt --data-file data.json
--job-id <this job's id> --run-at <this run's ISO 8601 timestamp>. If this step fails for any
reason, ignore the failure and continue -- it must never block or replace the normal Discord
delivery.
```

(Substitute the literal job id -- `903a7fc54a52` or `be6ef51056fc` -- and the actual run
timestamp per job.)

## Also needed on the Hermes host, once, before this does anything

Two environment variables Hermes's process needs at runtime (wherever Hermes's own env/config is
set -- not part of `jobs.json`):

```
N8N_WEBHOOK_URL=http://localhost:5679/webhook/hermes-gunpla-news
N8N_WEBHOOK_SECRET=<same random string you set as HERMES_WEBHOOK_SECRET on the n8n container>
```

`post_to_n8n.py` (already written to
`skills\productivity\gunpla-news-gatherer\scripts\post_to_n8n.py`, inert until this prompt change
references it) fails soft and logs to stderr if these aren't set or the webhook is unreachable --
it will never fail the cron job or block Discord delivery.

## Suggested order of operations (safest first)

Revised 2026-07-10. Steps 1 and 2 are now a single atomic window -- see Corrections.

1. **Together, in one maintenance window** (either alone breaks live Facebook posting):
   a. Apply the `assign_all_batches` migration, including the new `DROP FUNCTION` line.
   b. Apply `03-patch-notes.md` -- pin `03` (and every other `rpc/assign_all_batches` call site)
      to an explicit `p_source_type`.
   Verify immediately: manually trigger `03` and confirm it still batches and posts HLJ rows.
2. Apply `02-patch-notes.md` (source_type passthrough + the image-less stuck-row IF guard).
3. Import `hermes-news-webhook-ingest.json` into n8n, create the `HERMES_WEBHOOK_SECRET` env var,
   activate it.
4. Curl-test the webhook directly (verification step 1 in the plan) before touching Hermes at all.
5. Only then apply this `jobs.json` patch and set the two env vars on the Hermes host.
6. Trigger one job manually (not waiting for the weekly/monthly schedule) and confirm Discord
   delivery still works exactly as before, and a `post_queue_stg` row appears.
7. Import `03b-batch-and-publish-hermes-news.json` (stays `active:false` until you're ready for
   real Facebook posts) and activate it last, once everything upstream is verified.

## Rollback

The migration is the only step that is awkward to reverse. To restore the pre-patch function:

```sql
DROP FUNCTION IF EXISTS public.assign_all_batches(integer, text, text);
-- then re-apply the two-arg body from git:
--   git show HEAD:m-hub-db/database/function/assign_all_batches.sql
```

Revert the `03` node edits at the same time, or `03` will 404 against the schema cache.
