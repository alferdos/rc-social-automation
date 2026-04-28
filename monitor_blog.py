"""
RightCompound — Blog Article Monitor
======================================
Polls rightcompound.com/blog every 60 minutes.
When a new article URL is detected, posts immediately to all platforms
with an engaging hook and link.

Run as a background daemon: python3 monitor_blog.py
"""

import json
import sys
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).parent))
from post_engine import (
    load_state, save_state, post_blog_article, log_post_result,
    BASE_URL, HEADERS
)

POLL_INTERVAL_SECONDS = 3600  # 60 minutes
BLOG_DATA_FILE = Path("/home/ubuntu/social_automation/blog_data.json")


def get_clean_title_from_cache(url: str) -> str:
    """Look up clean title from blog_data.json cache."""
    if BLOG_DATA_FILE.exists():
        with open(BLOG_DATA_FILE, "r") as f:
            data = json.load(f)
        for art in data:
            if art["url"] == url:
                return art["title"]
    return ""


def get_live_blog_urls() -> list:
    """Fetch current blog article URLs from the live website."""
    try:
        resp = requests.get(f"{BASE_URL}/blog", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen = set()
        articles = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/blog/" in href:
                full = urljoin(BASE_URL, href)
                if full not in seen:
                    seen.add(full)
                    # Use clean title from cache, fallback to scraped text
                    clean_title = get_clean_title_from_cache(full)
                    raw_title   = a.get_text(strip=True)
                    title = clean_title if clean_title else raw_title
                    if len(title) > 10:
                        articles.append({"url": full, "title": title})
        return articles
    except Exception as e:
        print(f"  Error fetching blog: {e}")
        return []


def run_monitor():
    print("=" * 60)
    print("  RightCompound — Blog Article Monitor")
    print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Poll interval: {POLL_INTERVAL_SECONDS // 60} minutes")
    print("=" * 60)

    while True:
        try:
            state = load_state()
            known_urls = set(state.get("known_blog_urls", []))

            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new blog articles...")
            live_articles = get_live_blog_urls()
            live_urls     = {a["url"] for a in live_articles}
            print(f"  Live: {len(live_articles)} articles | Known: {len(known_urls)}")

            new_articles = [a for a in live_articles if a["url"] not in known_urls]

            if new_articles:
                print(f"  NEW ARTICLES DETECTED: {len(new_articles)}")
                for article in new_articles:
                    print(f"  Posting: {article['title']}")
                    result = post_blog_article(article)
                    log_post_result(result)
                    print(f"  Posted article: {article['url']}")
                    time.sleep(2)

                # Update known URLs
                state["known_blog_urls"] = sorted(live_urls)
                save_state(state)
            else:
                print("  No new articles found.")

                # First run: populate known URLs
                if not known_urls:
                    print(f"  Initializing known blog URLs with {len(live_urls)} articles")
                    state["known_blog_urls"] = sorted(live_urls)
                    save_state(state)

        except Exception as e:
            print(f"  Blog monitor error: {e}")

        print(f"  Next check in {POLL_INTERVAL_SECONDS // 60} minutes...")
        time.sleep(POLL_INTERVAL_SECONDS)


def run_once():
    """Single-run check for new blog articles (used by Manus agent tasks)."""
    print("=" * 60)
    print("  RightCompound — New Blog Article Check (single run)")
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    try:
        state = load_state()
        known_urls = set(state.get("known_blog_urls", []))

        print(f"\nChecking for new blog articles...")
        live_articles = get_live_blog_urls()
        live_urls     = {a["url"] for a in live_articles}
        print(f"  Live: {len(live_articles)} articles | Known: {len(known_urls)}")

        new_articles = [a for a in live_articles if a["url"] not in known_urls]

        if new_articles:
            print(f"  NEW ARTICLES DETECTED: {len(new_articles)}")
            for article in new_articles:
                print(f"  Posting: {article['title']}")
                result = post_blog_article(article)
                log_post_result(result)
                print(f"  Posted: {article['url']}")
                time.sleep(2)

            state["known_blog_urls"] = sorted(live_urls)
            save_state(state)
        else:
            print("  No new articles found.")
            if not known_urls:
                print(f"  Initializing known blog URLs with {len(live_urls)} articles")
                state["known_blog_urls"] = sorted(live_urls)
                save_state(state)
    except Exception as e:
        print(f"  Blog monitor error: {e}")
        raise


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_monitor()
