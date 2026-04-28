"""
RightCompound — Daily Blog Queue Post
========================================
Triggered daily at 3:00 PM Riyadh time (UTC+3 = 12:00 PM UTC).
Posts one article from the blog_queue in post_state.json.
The queue contains existing articles to be drip-posted one per day.
New articles published on the site are handled by monitor_blog.py (immediate).

Cron: 0 12 * * * python3 /home/ubuntu/social_automation/daily_blog_post.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from post_engine import (
    load_state, save_state, post_blog_article, log_post_result
)

STATE_FILE    = Path("/home/ubuntu/social_automation/post_state.json")
BLOG_DATA_FILE = Path("/home/ubuntu/social_automation/blog_data.json")


def build_blog_queue(state: dict) -> list:
    """
    Build the blog queue from blog_data.json, excluding already-posted URLs.
    Returns list of article dicts in order.
    """
    if not BLOG_DATA_FILE.exists():
        return []

    with open(BLOG_DATA_FILE, "r") as f:
        all_articles = json.load(f)

    # Already posted via the queue (tracked separately from monitor posts)
    queued_posted = set(state.get("blog_queue_posted_urls", []))

    # Return articles not yet posted via the queue
    return [a for a in all_articles if a["url"] not in queued_posted]


def main():
    print("=" * 60)
    print("  RightCompound — Daily Blog Queue Post")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    state = load_state()

    # Build queue of unposted articles
    queue = build_blog_queue(state)

    if not queue:
        print("Blog queue is empty. All existing articles have been posted.")
        sys.exit(0)

    # Pick the first article in the queue
    article = queue[0]
    print(f"\nSelected article: {article['title']}")
    print(f"  URL: {article['url']}")
    print(f"  Remaining in queue after this: {len(queue) - 1}")

    # Post to all platforms
    result = post_blog_article(article)

    # Mark as posted in queue tracker
    state.setdefault("blog_queue_posted_urls", []).append(article["url"])
    state["last_blog_queue_post_date"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # Log result
    log_post_result(result)

    # Summary
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    for p in result["platforms"]:
        icon = "OK" if p["status"] == "success" else ("--" if p["status"] == "skipped" else "XX")
        name = p.get("page") or p.get("account") or p.get("platform", "")
        print(f"  [{icon}] {p['platform']} {name}")

    success = sum(1 for p in result["platforms"] if p["status"] == "success")
    failed  = sum(1 for p in result["platforms"] if p["status"] == "error")
    print(f"\n  Success: {success} | Failed: {failed}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
