# Patch: `02 - Create Post Queue Candidates` (id `RL5PwXYQRkv2ot4l`, currently `active: false`)

Not yet applied to the live n8n instance (API key in `.env` returned 401; apply manually via the
n8n editor, or re-run once a fresh API key is available). Two node edits, both required --
patching only the first one leaves `source_type` hardcoded to `"hlj"` for every row that passes
through this workflow, which would silently break `03b`'s `p_source_type='hermes_news'` filter.
A third change (new IF branch) fixes a real stuck-row bug for image-less posts, uncovered while
extracting the live node JSON for this patch.

## 1. Node `Build Facebook Post Copy` (id `6870f3c0-f341-4e74-b205-c6284d4bb108`) -- jsCode

Add an early-return branch for non-`hlj` rows before the existing HLJ-specific logic. Existing
logic is otherwise byte-for-byte unchanged.

```js
const item = $('Process Each Staged Item').first().json;

if (item.source_type !== 'hlj') {
  const link = item.affiliate_url || '';
  const message = link ? `${item.post_copy}\n\n${link}` : item.post_copy;
  return $input.all().map(i => ({ json: { ...i.json, message, link } }));
}

const bitly    = $('Create Bitly Short Link').first()?.json?.link || '';
const tinyurl  = $('Create TinyURL Fallback Link').first()?.json?.data || '';
const affiliate = item.affiliate_url;
const link     = bitly || tinyurl || affiliate;

const symbolMap = {
  jpy: '¥', php: '₱', sgd: 'S$', usd: '$', myr: 'RM', thb: '฿', idr: 'Rp'
};

const priceLines = Object.keys(item)
  .filter(k => k.startsWith('price_'))
  .map(k => {
    const currency = k.split('_').pop();
    const symbol = symbolMap[currency] || '';
    let value = item[k];
    if (currency === 'jpy' && typeof value === 'string') {
      value = value.replace(/[^0-9.]/g, '');
    }
    if (currency === 'idr') value = Number(value).toLocaleString();
    return `${symbol}${value}`;
  })
  .join(' · ');

const stock = item.stock;
const stockNum = parseInt((stock || '').match(/\d+/)?.[0] || '0');
const urgency = stockNum === 1 ? '1 left' : `${stockNum} left`;

const grade = item.grade_scale && item.grade_scale !== 'Unknown'
  ? ` (${item.grade_scale})` : '';

const message = `${item.name}${grade}\n${priceLines}\n${urgency} · ${link}`;

return $input.all().map(i => ({
  json: { ...i.json, message, link }
}));
```

Note: the Bitly/TinyURL HTTP nodes upstream still fire unconditionally for every item (HLJ or
not) -- for a Hermes row with `affiliate_url: null` those calls will 4xx and `continueRegularOutput`
carries an empty result through, which this new branch simply ignores (`item.affiliate_url` is
used directly instead). Two harmless wasted API calls per Hermes item; not worth the extra IF-node
complexity to skip them.

## 2. Node `Prepare post_queue Insert Payload` (id `af788785-4c9c-4660-b1b1-a85430e557f9`) -- jsonOutput (raw mode)

**Original hardcodes `"source_type": "hlj"` unconditionally** -- this is the actual bug that would
have broken the integration silently. Fix: pass `source_type` through from the staged row, and
make `tier`/`mobile_suit`/`tags` source-aware instead of HLJ-only literals.

```
=={{
  {
    "batch_queue_id": null,
    "source_type": $('Process Each Staged Item').first().json.source_type,
    "source_id": $('Process Each Staged Item').first().json.source_id,
    "post_copy": $('Build Facebook Post Copy').first().json.message,
    "image_urls": $('Filter Queue-Eligible Items').first().json.images,
    "affiliate_url": $('Process Each Staged Item').first().json.affiliate_url,
    "status": "new",
    "channel": "facebook",
    "urgency": 5,
    "tier": $('Process Each Staged Item').first().json.source_type === 'hlj' ? "2" : null,
    "mobile_suit": $('Process Each Staged Item').first().json.source_type === 'hlj' ? $json.name : null,
    "tags": $('Process Each Staged Item').first().json.source_type === 'hlj' ? ["hlj", "low-stock"] : ["hermes", "news"]
  }
}}
```

## 3. NEW: image-count guard (fixes a stuck-row bug, not just a Hermes-specific tweak)

`Extract Image List` (`n8n-nodes-base.splitOut` on `image_list`) produces **zero output items**
when `images` is an empty array. Since n8n's per-item execution model means zero items = the rest
of the branch (`Upload Image to Facebook` -> ... -> `Update post_queue Record` ->
`Update post_queue_stg Record`) never runs for that staged item, **any row with no images gets
permanently stuck** at `post_queue.status='new'` / `post_queue_stg.stg_status='raw'` -- it never
reaches a terminal status. This was always latently true for `01`/`02` (an HLJ item somehow
missing `image_url` would hit the same bug) but becomes a live risk here because a Hermes brief
(e.g. a country/location highlight) can legitimately have zero images.

Add one IF node right after `Prepare Shared Content Inputs`, splitting on
`{{ $json.image_list.length > 0 }}`:
- **true branch** (has images): connect to `Extract Image List` exactly as today -- no change to
  that path.
- **false branch** (no images): connect directly to a new Code node `Skip Photo Upload` that
  produces the same shape `Assemble Post Record` currently expects from the photo-upload branch,
  with empty media:
  ```js
  return [{
    json: {
      post_queue_id: $('Insert post_queue Record').first().json.id,
      message: $('Build Facebook Post Copy').first().json.message,
      attached_media: [],
      fb_media_ids: []
    }
  }];
  ```
  then connect that directly into `Prepare post_queue Update Payload` (bypassing
  `Evaluate Facebook Upload Response` / `Check Facebook Upload Success` / `Evaluate Post Status`
  entirely, since there's nothing to evaluate when no upload happened -- `Evaluate Post Status`'s
  `hasError` check would otherwise see no `id`/`postId` and wrongly mark a successful text-only
  post as `'failed'`).

This only changes behavior for rows with zero images; existing HLJ rows (which always have
`image_url`) are unaffected.
