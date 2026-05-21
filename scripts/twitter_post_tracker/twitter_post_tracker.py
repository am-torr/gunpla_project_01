import requests
import json
import os
import time
from datetime import datetime, timezone

# ── CONFIG ────────────────────────────────────────────────
APIFY_TOKEN  = ""
ACTOR_ID     = "wAusCMrm284Voaw86"
TARGET_USER  = "yoshi115t"
KEYWORD      = "実物大ユニコーン"
DATE_FROM    = "2017-04-01"
DATE_TO      = "2017-09-31"
MAX_ITEMS    = 15
DELAY_SECS   = 3
FRESH_START  = True    # flip to False after first clean run
SORT_ORDER   = "asc"  # "desc" = newest first | "asc" = oldest first
RESULTS_FILE = os.path.expanduser("~/Documents/x_results.json")
BASE_URL     = "https://api.apify.com/v2"
# ─────────────────────────────────────────────────────────


def build_search_url(user, keyword, date_from, date_to):
    full_query = f"from:{user} {keyword} since:{date_from} until:{date_to}"
    return f"https://x.com/search?q={requests.utils.quote(full_query)}&src=typed_query"

def get_tweet_id(tweet):
    return (
        tweet.get("id")
        or tweet.get("tweetId")
        or tweet.get("rest_id")
        or tweet.get("url", "").split("/")[-1]
        or ""
    )

def get_user(tweet):
    return (
        tweet.get("author", {}).get("userName")
        or tweet.get("author", {}).get("username")
        or tweet.get("user", {}).get("screen_name")
        or tweet.get("username")
        or tweet.get("twitterUrl", "").split("/")[-1]
        or "?"
    )

def get_image_urls(tweet):
    return [
        m.get("url") or m.get("media_url_https", "")
        for m in tweet.get("media", [])
        if m.get("type") == "photo"
    ]

def get_best_video_url(tweet):
    for m in tweet.get("media", []):
        if m.get("type") == "video":
            mp4s = [
                v for v in m.get("video_info", {}).get("variants", [])
                if v.get("content_type") == "video/mp4"
            ]
            if mp4s:
                return max(mp4s, key=lambda v: v.get("bitrate", 0)).get("url", "")
    return ""

def normalize(tweet):
    image_urls = get_image_urls(tweet)
    author     = tweet.get("author", {})
    return {
        # ── original fields unchanged ──
        "id":            get_tweet_id(tweet),
        "text":          tweet.get("text") or tweet.get("fullText", ""),
        "type":          tweet.get("type", ""),
        "createdAt":     tweet.get("createdAt", ""),
        "retweetCount":  tweet.get("retweetCount", 0),
        "replyCount":    tweet.get("replyCount", 0),
        "likeCount":     tweet.get("likeCount", 0),
        "quoteCount":    tweet.get("quoteCount", 0),
        "viewCount":     tweet.get("viewCount", 0),
        "bookmarkCount": tweet.get("bookmarkCount", 0),
        "url":           tweet.get("url", ""),
        "lang":          tweet.get("lang", ""),
        "isReply":       tweet.get("isReply", False),
        "author":        author,
        # ── added fields only ──
        "image_url":     image_urls[0] if image_urls else "",
        "image_urls":    image_urls,
        "video_url":     get_best_video_url(tweet),
        "scraped_at":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "notes":         ""
    }

def load_existing():
    if FRESH_START:
        print("    Fresh start — ignoring existing file.")
        return []
    if not os.path.exists(RESULTS_FILE):
        return []
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else data.get("items", [])
    return [t for t in items if not str(t.get("id", "")).startswith("diag:")]

def save_results(items):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)
    print(f"    Saved to: {RESULTS_FILE}")

def dedupe(existing, new_items):
    seen = {get_tweet_id(t) for t in existing}
    return [t for t in new_items if get_tweet_id(t) not in seen]

def filter_by_year(items, date_from, date_to):
    years = [str(y) for y in range(int(date_from[:4]), int(date_to[:4]) + 1)]
    return [
        t for t in items
        if any(y in t.get("createdAt", "") for y in years)
        and not str(t.get("id", "")).startswith("diag:")
    ]

def trigger_run(search_url):
    r = requests.post(
        f"{BASE_URL}/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}",
        json={
            "startUrls":     [{"url": search_url}],
            "maxItems":      MAX_ITEMS,
            "queryType":     "Latest",
            "lang":          "ja",
            "filter:images": True
        },
        timeout=60
    )
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
    return r.json()["data"]["id"]

def wait_for_run(run_id):
    terminal = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
    while True:
        time.sleep(DELAY_SECS)
        s = requests.get(
            f"{BASE_URL}/actor-runs/{run_id}?token={APIFY_TOKEN}",
            timeout=30
        )
        s.raise_for_status()
        data = s.json()["data"]
        print(f"    status: {data['status']}")
        if data["status"] in terminal:
            return data

def fetch_dataset(dataset_id):
    time.sleep(DELAY_SECS)
    resp = requests.get(
        f"{BASE_URL}/datasets/{dataset_id}/items?clean=true&format=json&limit={MAX_ITEMS}&token={APIFY_TOKEN}",
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()

def print_preview(items):
    for i, t in enumerate(items, 1):
        print(f"[{i}] @{get_user(t)} | {t.get('createdAt', '?')}")
        print(f"     {t.get('text', '')[:120]}")
        if t.get("image_url"):
            print(f"     📷 {len(t.get('image_urls', []))} photo(s): {t['image_url']}")
        if t.get("video_url"):
            print(f"     🎬 {t['video_url']}")
        print()


def main():
    print(f"Save path: {RESULTS_FILE}\n")

    print("[1] Loading existing results...")
    existing = load_existing()
    print(f"    {len(existing)} clean tweets loaded.")

    search_url = build_search_url(TARGET_USER, KEYWORD, DATE_FROM, DATE_TO)
    print(f"\n[2] Search URL:\n    {search_url}")

    print(f"\n[3] Triggering actor run...")
    run_id = trigger_run(search_url)
    print(f"    run_id: {run_id}")

    print("\n[4] Waiting for run to complete...")
    run_data = wait_for_run(run_id)

    if run_data["status"] != "SUCCEEDED":
        raise RuntimeError(f"Run ended with status: {run_data['status']}")

    dataset_id = run_data["defaultDatasetId"]
    print(f"\n[5] Fetching dataset {dataset_id}...")
    raw_items = fetch_dataset(dataset_id)
    print(f"    Got {len(raw_items)} raw items.")

    year_filtered = filter_by_year(raw_items, DATE_FROM, DATE_TO)
    print(f"    {len(year_filtered)} after year filter ({DATE_FROM[:4]}–{DATE_TO[:4]}).")

    normalized = [normalize(t) for t in year_filtered]
    normalized.sort(
        key=lambda t: t.get("createdAt", ""),
        reverse=(SORT_ORDER == "desc")
    )

    unique = dedupe(existing, normalized)
    print(f"    {len(unique)} new after dedup.")

    if unique:
        all_items = existing + unique
        save_results(all_items)
        print(f"\n[6] Total: {len(all_items)} tweets saved.")
        print(f"    Sort order: {SORT_ORDER}")
        print("\n── Preview ──")
        print_preview(unique[:5])
    else:
        print("\n[6] Nothing new to save.")
        print("\n── Existing sample ──")
        print_preview(existing[:5])


if __name__ == "__main__":
    main()
