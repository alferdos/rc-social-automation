"""
RightCompound — Daily Compound Post
=====================================
Triggered daily at 9:00 AM (Saudi time, UTC+3).
Picks the next unposted compound from the rotation and posts to all platforms.
Deduplication is tracked in post_state.json.

Run via cron: 0 6 * * * python3 /home/ubuntu/social_automation/daily_compound_post.py
(9am Riyadh = 6am UTC)
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
    load_state, save_state, load_compounds, get_next_compound,
    mark_compound_posted, post_compound, log_post_result,
    scrape_compound_detail_from_engine,
    BASE_URL, HEADERS
)


def refresh_compound_list(state: dict):
    """
    Re-scrape the live compound list and update compounds_data.json
    with any new entries (without removing existing ones).
    """
    try:
        resp = requests.get(f"{BASE_URL}/compounds", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        live_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/compounds/" in href and href != "/compounds":
                full = urljoin(BASE_URL, href)
                path = full.replace(BASE_URL, "")
                parts = [p for p in path.split("/") if p]
                if len(parts) == 3 and parts[0] == "compounds" and parts[1] and parts[2]:
                    live_urls.add(full)

        compounds_file = Path("/home/ubuntu/social_automation/compounds_data.json")
        existing = []
        if compounds_file.exists():
            with open(compounds_file, "r") as f:
                existing = json.load(f)

        existing_urls = {c["url"] for c in existing}
        new_urls      = live_urls - existing_urls

        if new_urls:
            print(f"  Found {len(new_urls)} new compounds to add to dataset")
            for url in sorted(new_urls):
                data = scrape_compound_detail_from_engine(url)
                if data and data.get("name"):
                    existing.append(data)
                    print(f"    Added: {data['name']}")
                time.sleep(0.5)

            with open(compounds_file, "w") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)

        # Update known URLs in state
        state["known_compound_urls"] = sorted(live_urls)
        save_state(state)

        return len(new_urls)

    except Exception as e:
        print(f"  Could not refresh compound list: {e}")
        return 0


def main():
    print("=" * 60)
    print("  RightCompound — Daily Compound Post")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    state = load_state()

    # Refresh compound list to catch any new additions
    print("\nRefreshing compound list...")
    new_count = refresh_compound_list(state)
    if new_count:
        print(f"  {new_count} new compounds added to dataset")

    # Pick next compound
    compound = get_next_compound(state)
    if not compound:
        print("No compounds available to post. Exiting.")
        sys.exit(1)

    print(f"\nSelected compound: {compound['name']} ({compound['city']})")

    # Post to all platforms
    result = post_compound(compound)

    # Mark as posted
    mark_compound_posted(state, compound)

    # Log result
    log_post_result(result)

    # Summary
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    success = [p for p in result["platforms"] if p.get("status") == "success"]
    failed  = [p for p in result["platforms"] if p.get("status") == "error"]
    skipped = [p for p in result["platforms"] if p.get("status") == "skipped"]

    for p in result["platforms"]:
        icon = "OK" if p["status"] == "success" else ("--" if p["status"] == "skipped" else "XX")
        name = p.get("page") or p.get("account") or p.get("platform", "")
        print(f"  [{icon}] {p['platform']} {name}")

    print(f"\n  Success: {len(success)} | Failed: {len(failed)} | Skipped: {len(skipped)}")
    print("=" * 60)

    sys.exit(0 if len(failed) == 0 else 1)


if __name__ == "__main__":
    main()
