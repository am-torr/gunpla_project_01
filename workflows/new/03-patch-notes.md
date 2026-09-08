# Patch: `03 - Batch and Publish Queue Items` -- REQUIRED, NOT YET APPLIED

Not yet applied to the live n8n instance (`N8N_API_KEY` in `.env` returns 401 -- apply manually via
the n8n editor UI).

## Why this patch exists

This edit is **not** in the original design plan. The plan asserted:

> Default `NULL` preserves today's behavior for `03` untouched -- zero regression risk to the
> working HLJ flow.

That is true only for as long as `post_queue` contains no `hermes_news` rows. It stops being true
the moment the integration starts working, and the consequence is the exact bug `03b` was created
to prevent.

**The race:** `assign_all_batches(p_source_type => NULL)` means *no filter* -- it batches every
`status='pending'` row regardless of `source_type`. `03` fires hourly at :03/:20; `03b` fires at
:45. So `03` reaches the pending `hermes_news` rows first, pools them with unrelated HLJ low-stock
spotlights via `string_agg(pq.post_copy, E'\n---\n')`, and posts one mashed-up Facebook post. By
the time `03b` runs at :45 there is nothing left for it to claim.

`03` must therefore be pinned to `source_type='hlj'` explicitly. Its previous behavior ("batch
everything") was only ever correct because `hlj` was the only source that existed.

## Node `Load Batch Configuration` (id `8dde4b88-a73d-47b3-b09b-cadc0ad1e165`) -- Set node

Add one assignment alongside the existing `items_per_batch` / `message` fields:

| name | value | type |
|---|---|---|
| `p_source_type` | `hlj` | string |

## Node `Assign All Batches` -- httpRequest, `jsonBody`

Current live body sends two named args:

```
={
  "p_max": {{ $('Load Batch Configuration').item.json.items_per_batch }},
  "p_message": {{ JSON.stringify($('Load Batch Configuration').item.json.message) }}
}
```

Change to three:

```
={
  "p_max": {{ $('Load Batch Configuration').item.json.items_per_batch }},
  "p_message": {{ JSON.stringify($('Load Batch Configuration').item.json.message) }},
  "p_source_type": {{ JSON.stringify($('Load Batch Configuration').item.json.p_source_type) }}
}
```

## Other `assign_all_batches` call sites

`workflows-export.json` (Jul 7 snapshot) shows **four** nodes POSTing to
`/rest/v1/rpc/assign_all_batches`, not one. Two belong to `03`-family workflows keyed off a
`Config` node, and at least one sends `{"p_max": ...}` **only** -- no `p_message`.

Before applying, search the live instance for every `rpc/assign_all_batches` node and give each an
explicit `p_source_type`. Any call site left without one will silently batch across all sources
again. The known names to check: `Config`-driven callers in
`02 - 03 - Process and Post to Facebook` and the manual-trigger test workflow.

## Ordering constraint

Apply this patch **in the same maintenance window as** the `assign_all_batches` SQL migration.

- Migration applied but `03` not patched -> `03` steals Hermes rows into HLJ posts.
- `03` patched but migration not applied -> `03` sends `p_source_type` to a function that has no
  such parameter; PostgREST returns `404 Could not find the function ... in the schema cache` and
  `03` stops posting entirely.

Neither half is safe alone.
