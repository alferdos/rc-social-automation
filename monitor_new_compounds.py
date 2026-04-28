"""
RightCompound — New Compound Monitor
======================================
Polls rightcompound.com/compounds every 30 minutes.
When a new compound URL is detected that was not previously known,
it scrapes the compound details and posts immediately to all platforms.

Run as a background daemon: python3 monitor_new_compounds.py
"""

import json
import sys
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from post_engine import (
    load_state, save_state, post_compound, log_post_result,
    scrape_compound_detail_from_engine,
    BASE_URL, HEADERS
)

POLL_INTERVAL_SECONDS = 1800  # 30 minutes


def get_live_compound_urls() -> set:
    """Fetch current compound URLs from the live website."""
    try:
        resp = requests.get(f"{BASE_URL}/compounds", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/compounds/" in href and href != "/compounds":
                full = urljoin(BASE_URL, href)
                path = full.replace(BASE_URL, "")
                parts = [p for p in path.split("/") if p]
                if len(parts) == 3 and parts[0] == "compounds" and parts[1] and parts[2]:
                    links.add(full)
        return links
    except Exception as e:
        print(f"  Error fetching compound list: {e}")
        return set()


def run_monitor():
    print("=" * 60)
    print("  RightCompound — New Compound Monitor")
    print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"  Poll interval: {POLL_INTERVAL_SECONDS // 60} minutes")
    print("=" * 60)

    while True:
        try:
            state = load_state()
            known_urls = set(state.get("known_compound_urls", []))

            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new compounds...")
            live_urls = get_live_compound_urls()
            print(f"  Live: {len(live_urls)} compounds | Known: {len(known_urls)}")

            new_urls = live_urls - known_urls

            if new_urls:
                print(f"  NEW COMPOUNDS DETECTED: {len(new_urls)}")
                for url in sorted(new_urls):
                    print(f"  Processing: {url}")
                    compound = scrape_compound_detail_from_engine(url)
                    if compound and compound.get("name"):
                        result = post_compound(compound)
                        log_post_result(result)
                        print(f"  Posted: {compound['name']}")
                    else:
                        print(f"  Could not scrape compound at {url}")
                    time.sleep(2)

                # Update known URLs
                state["known_compound_urls"] = sorted(live_urls)
                save_state(state)
            else:
                print("  No new compounds found.")

                # First run: populate known URLs
                if not known_urls:
                    print(f"  Initializing known URLs with {len(live_urls)} compounds")
                    state["known_compound_urls"] = sorted(live_urls)
                    save_state(state)

        except Exception as e:
            print(f"  Monitor error: {e}")

        print(f"  Next check in {POLL_INTERVAL_SECONDS // 60} minutes...")
        time.sleep(POLL_INTERVAL_SECONDS)


def run_once():
    """Single-run check for new compounds (used by Manus agent tasks)."""
    print("=" * 60)
    print("  RightCompound — New Compound Check (single run)")
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    try:
        state = load_state()
        known_urls = set(state.get("known_compound_urls", []))

        print(f"\nChecking for new compounds...")
        live_urls = get_live_compound_urls()
        print(f"  Live: {len(live_urls)} compounds | Known: {len(known_urls)}")

        new_urls = live_urls - known_urls

        if new_urls:
            print(f"  NEW COMPOUNDS DETECTED: {len(new_urls)}")
            for url in sorted(new_urls):
                print(f"  Processing: {url}")
                compound = scrape_compound_detail_from_engine(url)
                if compound and compound.get("name"):
                    result = post_compound(compound)
                    log_post_result(result)
                    print(f"  Posted: {compound['name']}")
                else:
                    print(f"  Could not scrape compound at {url}")
                time.sleep(2)

            state["known_compound_urls"] = sorted(live_urls)
            save_state(state)
        else:
            print("  No new compounds found.")
            if not known_urls:
                print(f"  Initializing known URLs with {len(live_urls)} compounds")
                state["known_compound_urls"] = sorted(live_urls)
                save_state(state)
    except Exception as e:
        print(f"  Monitor error: {e}")
        raise


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_monitor()
