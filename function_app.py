"""
RightCompound Social Media Automation — Azure Function App
===========================================================
Self-contained Azure Function with all posting logic inline.
State is stored in Azure Blob Storage (social-state container).
Credentials are read from environment variables.

Timer Triggers (Riyadh UTC+3):
  daily_compound_post   → 09:00 Riyadh = 06:00 UTC  (cron: 0 0 6 * * *)
  new_compound_check    → 12:00 Riyadh = 09:00 UTC  (cron: 0 0 9 * * *)
  daily_blog_post       → 15:00 Riyadh = 12:00 UTC  (cron: 0 0 12 * * *)
  new_blog_check        → 18:00 Riyadh = 15:00 UTC  (cron: 0 0 15 * * *)
"""

import azure.functions as func
import logging
import json
import os
import random
import re
import time
import requests
from datetime import datetime, timezone, timedelta

app = func.FunctionApp()

RIYADH_TZ = timezone(timedelta(hours=3))

# ============================================================
# CREDENTIALS (from environment variables)
# ============================================================
X_API_KEY             = os.environ.get("X_API_KEY", "")
X_API_SECRET          = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN        = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

FB_PAGES = [
    {"name": "Saudi Compounds",  "id": os.environ.get("FB_PAGE_ID_SAUDI", ""),  "token": os.environ.get("FB_PAGE_TOKEN_SAUDI", "")},
    {"name": "Riyadh Compounds", "id": os.environ.get("FB_PAGE_ID_RIYADH", ""), "token": os.environ.get("FB_PAGE_TOKEN_RIYADH", "")},
    {"name": "Jeddah Compounds", "id": os.environ.get("FB_PAGE_ID_JEDDAH", ""), "token": os.environ.get("FB_PAGE_TOKEN_JEDDAH", "")},
    {"name": "Expatsinksa",      "id": os.environ.get("FB_PAGE_ID_EXPATS", ""), "token": os.environ.get("FB_PAGE_TOKEN_EXPATS", "")},
]

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

GRAPH_BASE = "https://graph.facebook.com/v21.0"
BASE_URL   = "https://rightcompound.com"
HEADERS    = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

CITY_MAP = {
    "riyadh": "Riyadh", "khobar": "Al Khobar", "jeddah": "Jeddah",
    "dammam": "Dammam", "taif": "Taif", "jubail": "Jubail",
    "al-qaseem": "Al Qaseem", "qaseem": "Al Qaseem",
    "madinah": "Madinah", "makkah": "Makkah", "dhahran": "Dhahran",
}

COMPOUND_HOOKS = [
    "Looking for your next home in {city}? This one is worth a look.",
    "Not all compounds in {city} are the same. Here is one that stands out.",
    "If you are relocating to {city}, this compound just made your shortlist.",
    "Expat life in {city} just got a whole lot easier.",
    "This compound in {city} has everything your family needs under one roof.",
    "Finding the right compound in {city} takes time. We did the work for you.",
    "Life in {city} is better when you have the right community around you.",
    "A compound in {city} that checks all the boxes.",
    "Your search for a home in {city} might just end here.",
    "Settling in {city}? This compound is one of the best options available right now.",
    "Gated, secure, and fully equipped. This is what living in {city} should feel like.",
    "We keep finding great compounds in {city} so you do not have to.",
    "This is the kind of compound in {city} that makes relocation feel easy.",
    "Families moving to {city} ask us all the time. Here is one of our top picks.",
    "A well-equipped compound in {city} just went live on RightCompound.",
    "If {city} is where you are headed, this compound deserves your attention.",
    "Another great option for expats and families in {city}.",
    "Community, comfort, and convenience. This compound in {city} has it all.",
    "For those planning a move to {city}, this one is hard to overlook.",
    "Compound living in {city} at its finest.",
]

BLOG_HOOKS = [
    "This guide is exactly what you need before making your next move.",
    "Everything you need to know, all in one place.",
    "If you are serious about finding the right compound, read this first.",
    "We put this together so you do not have to search for hours.",
    "One of the most useful reads for anyone relocating to Saudi Arabia.",
    "This article answers the questions we get asked most.",
    "Before you sign anything, read this.",
    "Your relocation just got a lot less stressful.",
    "The kind of information that actually makes a difference.",
    "We wrote this because finding good compound advice is harder than it should be.",
    "Short, useful, and worth your time.",
    "If you are planning a move, bookmark this.",
    "Real information for people making real decisions.",
    "This is what we wish we had when we started.",
    "Worth a read whether you are new to Saudi Arabia or not.",
]

# ============================================================
# AZURE BLOB STATE
# ============================================================
def get_blob_client(blob_name: str):
    from azure.storage.blob import BlobServiceClient
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    client = BlobServiceClient.from_connection_string(conn_str)
    return client.get_blob_client(container="social-state", blob=blob_name)


def load_state() -> dict:
    try:
        blob = get_blob_client("post_state.json")
        return json.loads(blob.download_blob().readall())
    except Exception as e:
        logging.warning(f"Could not load state: {e}")
        return {
            "posted_compound_slugs": [],
            "compound_rotation_index": 0,
            "posted_blog_urls": [],
            "known_compound_urls": [],
            "known_blog_urls": [],
            "blog_queue": [],
        }


def save_state(state: dict):
    try:
        blob = get_blob_client("post_state.json")
        blob.upload_blob(json.dumps(state, indent=2), overwrite=True)
    except Exception as e:
        logging.error(f"Could not save state: {e}")


def load_blob_json(blob_name: str) -> list:
    try:
        blob = get_blob_client(blob_name)
        return json.loads(blob.download_blob().readall())
    except Exception as e:
        logging.warning(f"Could not load {blob_name}: {e}")
        return []


def save_blob_json(blob_name: str, data):
    try:
        blob = get_blob_client(blob_name)
        blob.upload_blob(json.dumps(data, indent=2, ensure_ascii=False), overwrite=True)
    except Exception as e:
        logging.error(f"Could not save {blob_name}: {e}")


# ============================================================
# SCRAPER
# ============================================================
def scrape_compound(url: str) -> dict | None:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        name = ""
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)
        if not name:
            og = soup.find("meta", {"property": "og:title"})
            if og:
                name = og.get("content", "").strip()

        parts = [p for p in url.replace(BASE_URL, "").split("/") if p]
        city_slug = parts[1] if len(parts) >= 3 else ""
        slug = parts[2] if len(parts) >= 3 else ""
        city = CITY_MAP.get(city_slug.lower(), city_slug.replace("-", " ").title())

        desc = ""
        for prop in ["description", "og:description"]:
            tag = soup.find("meta", {"name": prop}) or soup.find("meta", {"property": prop})
            if tag and tag.get("content"):
                desc = tag["content"].strip()
                break

        image_url = ""
        og_img = soup.find("meta", {"property": "og:image"})
        if og_img:
            image_url = og_img.get("content", "").strip()

        return {
            "name": name or slug.replace("-", " ").title(),
            "slug": slug,
            "city": city,
            "city_slug": city_slug,
            "url": url,
            "description": desc[:350] if desc else "",
            "image_url": image_url,
        }
    except Exception as e:
        logging.error(f"Scrape error for {url}: {e}")
        return None


def scrape_all_compound_urls() -> list:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(f"{BASE_URL}/compounds", headers=HEADERS, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/compounds/") and href.count("/") >= 3:
                full = BASE_URL + href if not href.startswith("http") else href
                if full not in urls:
                    urls.append(full)
        return urls
    except Exception as e:
        logging.error(f"Could not scrape compound list: {e}")
        return []


def scrape_blog_articles() -> list:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(f"{BASE_URL}/blog", headers=HEADERS, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/blog/article/" in href:
                full = BASE_URL + href if not href.startswith("http") else href
                if full not in [x["url"] for x in articles]:
                    # Get title from OG or h1
                    title = a.get_text(strip=True)[:100]
                    articles.append({"url": full, "title": title})
        return articles
    except Exception as e:
        logging.error(f"Could not scrape blog: {e}")
        return []


def get_article_og_image(url: str) -> str:
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", {"property": "og:image"})
        if og:
            return og.get("content", "").strip()
    except:
        pass
    return ""


# ============================================================
# X (TWITTER) POSTING
# ============================================================
def post_to_x(text: str, image_url: str = "") -> str | None:
    try:
        from requests_oauthlib import OAuth1Session
        oauth = OAuth1Session(
            X_API_KEY, X_API_SECRET,
            X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
        )

        media_id = None
        if image_url:
            try:
                img_resp = requests.get(image_url, headers=HEADERS, timeout=20)
                if img_resp.status_code == 200:
                    upload_resp = oauth.post(
                        "https://upload.twitter.com/1.1/media/upload.json",
                        files={"media": img_resp.content}
                    )
                    if upload_resp.status_code == 200:
                        media_id = upload_resp.json().get("media_id_string")
            except Exception as e:
                logging.warning(f"X image upload failed: {e}")

        payload = {"text": text}
        if media_id:
            payload["media"] = {"media_ids": [media_id]}

        resp = oauth.post("https://api.twitter.com/2/tweets", json=payload)
        if resp.status_code == 201:
            tweet_id = resp.json()["data"]["id"]
            return f"https://x.com/rightcompound/status/{tweet_id}"
        else:
            logging.error(f"X post failed: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        logging.error(f"X post exception: {e}")
        return None


# ============================================================
# FACEBOOK POSTING
# ============================================================
def post_to_facebook(text: str, image_url: str = "") -> dict:
    results = {}
    for page in FB_PAGES:
        if not page["id"] or not page["token"]:
            logging.warning(f"FB page {page['name']} missing credentials")
            continue
        try:
            if image_url:
                resp = requests.post(
                    f"{GRAPH_BASE}/{page['id']}/photos",
                    data={"url": image_url, "caption": text, "access_token": page["token"]},
                    timeout=30
                )
            else:
                resp = requests.post(
                    f"{GRAPH_BASE}/{page['id']}/feed",
                    data={"message": text, "access_token": page["token"]},
                    timeout=30
                )
            if resp.status_code == 200:
                post_id = resp.json().get("id") or resp.json().get("post_id")
                results[page["name"]] = post_id
                logging.info(f"  FB [{page['name']}] posted: {post_id}")
            else:
                logging.error(f"  FB [{page['name']}] failed: {resp.status_code} {resp.text[:200]}")
                results[page["name"]] = None
        except Exception as e:
            logging.error(f"  FB [{page['name']}] exception: {e}")
            results[page["name"]] = None
        time.sleep(0.5)
    return results


# ============================================================
# POST BUILDERS
# ============================================================
def build_compound_post(compound: dict) -> str:
    city = compound.get("city", "Saudi Arabia")
    name = compound.get("name", "")
    url = compound.get("url", "")
    desc = compound.get("description", "")

    hook = random.choice(COMPOUND_HOOKS).format(city=city)

    lines = [hook, ""]
    lines.append(f"{name}")
    lines.append(f"Location: {city}")
    if desc:
        short_desc = desc[:200].rsplit(" ", 1)[0] + "..." if len(desc) > 200 else desc
        lines.append(f"{short_desc}")
    lines.append("")
    lines.append(f"View full details: {url}")
    lines.append("")
    lines.append("#SaudiArabia #Expats #CompoundLiving #Riyadh #Jeddah #AlKhobar #RightCompound")

    return "\n".join(lines)


def generate_blog_hook(title: str, article_text: str = "") -> str:
    """Generate a topic-specific hook for a blog article using OpenAI."""
    if not OPENAI_API_KEY:
        return random.choice(BLOG_HOOKS)
    try:
        context = f"Article title: {title}"
        if article_text:
            context += f"\nArticle summary: {article_text[:400]}"
        prompt = (
            f"{context}\n\n"
            "Write a single short punchy social media hook (1-2 sentences max) for this article. "
            "The hook must be directly relevant to the specific article topic. "
            "Do not use generic phrases like 'everything you need to know' or 'this guide'. "
            "Do not use dashes or em dashes anywhere in the text. "
            "Write in a genuine human tone. "
            "Do not include hashtags, quotes, or the article title itself. "
            "Just the hook sentence only."
        )
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4.1-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 80,
                "temperature": 0.8,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            hook = resp.json()["choices"][0]["message"]["content"].strip().strip('"\'')
            hook = hook.replace(" - ", " ").replace(" -- ", " ").replace("\u2014", " ").replace("\u2013", " ")
            logging.info(f"[HOOK] Generated for '{title[:50]}': {hook}")
            return hook
    except Exception as e:
        logging.warning(f"[HOOK] OpenAI failed: {e}")
    return random.choice(BLOG_HOOKS)


def build_blog_post(article: dict) -> str:
    title = article.get("title", "")
    url = article.get("url", "")
    article_text = article.get("description", "")

    hook = generate_blog_hook(title, article_text)

    lines = [hook, ""]
    lines.append(f"{title}")
    lines.append("")
    lines.append(f"Read the full article: {url}")
    lines.append("")
    lines.append("#SaudiArabia #Expats #CompoundLiving #Riyadh #RightCompound")

    return "\n".join(lines)


# ============================================================
# TIMER TRIGGER 1: Daily Compound Post — 9:00 AM Riyadh (06:00 UTC)
# ============================================================
@app.timer_trigger(
    schedule="0 0 6 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def daily_compound_post(timer: func.TimerRequest) -> None:
    now_riyadh = datetime.now(RIYADH_TZ).strftime("%Y-%m-%d %H:%M Riyadh")
    logging.info(f"[COMPOUND POST] Triggered at {now_riyadh}")

    if timer.past_due:
        logging.warning("Timer is past due — running anyway")

    state = load_state()
    compounds = load_blob_json("compounds_data.json")

    if not compounds:
        logging.error("[COMPOUND POST] No compounds data in blob storage")
        return

    posted_slugs = state.get("posted_compound_slugs", [])
    rotation_index = state.get("compound_rotation_index", 0)

    # Pick next compound in rotation (skip already posted in this cycle)
    if rotation_index >= len(compounds):
        # Full cycle complete, reset
        rotation_index = 0
        posted_slugs = []
        logging.info("[COMPOUND POST] Full rotation complete, resetting cycle")

    compound = compounds[rotation_index]
    rotation_index += 1

    logging.info(f"[COMPOUND POST] Selected: {compound.get('name')} ({compound.get('city')})")

    # Scrape fresh data if needed
    if not compound.get("description") or not compound.get("image_url"):
        fresh = scrape_compound(compound["url"])
        if fresh:
            compound.update(fresh)

    text = build_compound_post(compound)
    image_url = compound.get("image_url", "")

    # Post to X
    x_url = post_to_x(text, image_url)
    if x_url:
        logging.info(f"[COMPOUND POST] X posted: {x_url}")
    else:
        logging.error("[COMPOUND POST] X post failed")

    # Post to Facebook
    fb_results = post_to_facebook(text, image_url)

    # Update state
    posted_slugs.append(compound.get("slug", ""))
    state["posted_compound_slugs"] = posted_slugs
    state["compound_rotation_index"] = rotation_index
    state["last_compound_post"] = now_riyadh
    save_state(state)

    logging.info(f"[COMPOUND POST] Done. X={'OK' if x_url else 'FAIL'}, FB={sum(1 for v in fb_results.values() if v)}/{len(fb_results)} pages")


# ============================================================
# TIMER TRIGGER 2: New Compound Check — 12:00 PM Riyadh (09:00 UTC)
# ============================================================
@app.timer_trigger(
    schedule="0 0 9 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def new_compound_check(timer: func.TimerRequest) -> None:
    now_riyadh = datetime.now(RIYADH_TZ).strftime("%Y-%m-%d %H:%M Riyadh")
    logging.info(f"[COMPOUND CHECK] Triggered at {now_riyadh}")

    state = load_state()
    known_urls = set(state.get("known_compound_urls", []))

    current_urls = scrape_all_compound_urls()
    new_urls = [u for u in current_urls if u not in known_urls]

    if not new_urls:
        logging.info("[COMPOUND CHECK] No new compounds found")
        state["known_compound_urls"] = list(known_urls | set(current_urls))
        save_state(state)
        return

    logging.info(f"[COMPOUND CHECK] Found {len(new_urls)} new compounds")

    for url in new_urls:
        compound = scrape_compound(url)
        if not compound:
            continue

        text = build_compound_post(compound)
        image_url = compound.get("image_url", "")

        x_url = post_to_x(text, image_url)
        if x_url:
            logging.info(f"[COMPOUND CHECK] X posted new compound: {x_url}")

        fb_results = post_to_facebook(text, image_url)
        logging.info(f"[COMPOUND CHECK] FB posted to {sum(1 for v in fb_results.values() if v)}/{len(fb_results)} pages")

        # Add to compounds dataset
        compounds = load_blob_json("compounds_data.json")
        if not any(c.get("url") == url for c in compounds):
            compounds.append(compound)
            save_blob_json("compounds_data.json", compounds)

        time.sleep(2)

    state["known_compound_urls"] = list(known_urls | set(current_urls))
    save_state(state)


# ============================================================
# TIMER TRIGGER 3: Daily Blog Post — 3:00 PM Riyadh (12:00 UTC)
# ============================================================
@app.timer_trigger(
    schedule="0 0 12 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def daily_blog_post(timer: func.TimerRequest) -> None:
    now_riyadh = datetime.now(RIYADH_TZ).strftime("%Y-%m-%d %H:%M Riyadh")
    logging.info(f"[BLOG POST] Triggered at {now_riyadh}")

    if timer.past_due:
        logging.warning("Timer is past due — running anyway")

    state = load_state()
    blog_queue = state.get("blog_queue", [])

    if not blog_queue:
        logging.info("[BLOG POST] Queue is empty, nothing to post today")
        return

    article = blog_queue.pop(0)
    logging.info(f"[BLOG POST] Posting: {article.get('title')} | Queue remaining: {len(blog_queue)}")

    # Get OG image
    image_url = get_article_og_image(article["url"])
    if image_url:
        logging.info(f"[BLOG POST] Article image: {image_url}")

    text = build_blog_post(article)

    x_url = post_to_x(text, image_url)
    if x_url:
        logging.info(f"[BLOG POST] X posted: {x_url}")
    else:
        logging.error("[BLOG POST] X post failed")

    fb_results = post_to_facebook(text, image_url)

    # Update state
    posted_urls = state.get("posted_blog_urls", [])
    posted_urls.append(article["url"])
    state["posted_blog_urls"] = posted_urls
    state["blog_queue"] = blog_queue
    state["last_blog_post"] = now_riyadh
    save_state(state)

    logging.info(f"[BLOG POST] Done. X={'OK' if x_url else 'FAIL'}, FB={sum(1 for v in fb_results.values() if v)}/{len(fb_results)} pages")


# ============================================================
# TIMER TRIGGER 4: New Blog Article Check — 6:00 PM Riyadh (15:00 UTC)
# ============================================================
@app.timer_trigger(
    schedule="0 0 15 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def new_blog_check(timer: func.TimerRequest) -> None:
    now_riyadh = datetime.now(RIYADH_TZ).strftime("%Y-%m-%d %H:%M Riyadh")
    logging.info(f"[BLOG CHECK] Triggered at {now_riyadh}")

    state = load_state()
    known_blog_urls = set(state.get("known_blog_urls", []))
    posted_blog_urls = set(state.get("posted_blog_urls", []))

    articles = scrape_blog_articles()
    new_articles = [a for a in articles if a["url"] not in known_blog_urls and a["url"] not in posted_blog_urls]

    if not new_articles:
        logging.info("[BLOG CHECK] No new articles found")
        state["known_blog_urls"] = list(known_blog_urls | {a["url"] for a in articles})
        save_state(state)
        return

    logging.info(f"[BLOG CHECK] Found {len(new_articles)} new articles")

    for article in new_articles:
        # Get clean title from OG
        try:
            from bs4 import BeautifulSoup
            resp = requests.get(article["url"], headers=HEADERS, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
            og_title = soup.find("meta", {"property": "og:title"})
            if og_title and og_title.get("content"):
                article["title"] = og_title["content"].strip()
            og_img = soup.find("meta", {"property": "og:image"})
            image_url = og_img.get("content", "").strip() if og_img else ""
        except:
            image_url = ""

        text = build_blog_post(article)

        x_url = post_to_x(text, image_url)
        if x_url:
            logging.info(f"[BLOG CHECK] X posted new article: {x_url}")

        fb_results = post_to_facebook(text, image_url)
        logging.info(f"[BLOG CHECK] FB posted to {sum(1 for v in fb_results.values() if v)}/{len(fb_results)} pages")

        posted_blog_urls.add(article["url"])
        time.sleep(2)

    state["known_blog_urls"] = list(known_blog_urls | {a["url"] for a in articles})
    state["posted_blog_urls"] = list(posted_blog_urls)
    save_state(state)
