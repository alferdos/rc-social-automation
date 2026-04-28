"""
RightCompound — Social Media Post Engine
=========================================
Core engine for posting compounds and blog articles to X, Facebook, and Instagram.
Handles:
  - Hook generation (varied, genuine-sounding, no AI tells)
  - Deduplication tracking (JSON state file)
  - X (Twitter) API v2 posting with image
  - Facebook Graph API posting to all pages
  - Instagram posting (via Facebook Graph API)
  - Blog article posting with hooks
"""

import json
import os
import random
import re
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from requests_oauthlib import OAuth1Session

# ============================================================
# PATHS
# ============================================================
BASE_URL = "https://rightcompound.com"
HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CITY_MAP = {
    "riyadh": "Riyadh", "khobar": "Al Khobar", "jeddah": "Jeddah",
    "dammam": "Dammam", "taif": "Taif", "jubail": "Jubail",
    "al-qaseem": "Al Qaseem", "qaseem": "Al Qaseem",
    "madinah": "Madinah", "makkah": "Makkah", "dhahran": "Dhahran",
}

AMENITY_KEYWORDS = [
    ("Swimming Pool",    ["swimming pool", "pool"]),
    ("Gym",              ["gym", "fitness center", "fitness centre"]),
    ("Padel Court",      ["padel"]),
    ("Tennis Court",     ["tennis"]),
    ("Basketball Court", ["basketball"]),
    ("Kids Play Area",   ["kids play", "playground", "children play"]),
    ("Kids Day Care",    ["day care", "daycare", "nursery"]),
    ("Supermarket",      ["supermarket", "grocery"]),
    ("Restaurant",       ["restaurant", "dining"]),
    ("Mosque",           ["mosque"]),
    ("24/7 Security",    ["24/7 security", "security guard", "gated community"]),
    ("Parking",          ["parking"]),
    ("Maintenance",      ["maintenance"]),
    ("Housekeeping",     ["housekeeping", "maid service"]),
    ("Sauna",            ["sauna"]),
    ("Jacuzzi",          ["jacuzzi"]),
    ("Squash Court",     ["squash"]),
    ("Volleyball Court", ["volleyball"]),
    ("Clinic",           ["clinic", "medical"]),
    ("Laundry",          ["laundry"]),
    ("Concierge",        ["concierge"]),
    ("Rooftop",          ["rooftop"]),
    ("Garden",           ["garden", "landscaped"]),
    ("Barbecue Area",    ["barbecue", "bbq"]),
]

# ============================================================
# SCRAPER (used by monitors and daily post)
# ============================================================
def scrape_compound_detail_from_engine(url: str) -> dict | None:
    """Scrape a single compound page and return structured data."""
    import re as _re
    from bs4 import BeautifulSoup as _BS
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
        soup = _BS(resp.text, "html.parser")

        name = ""
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)
        if not name:
            og = soup.find("meta", {"property": "og:title"})
            if og:
                name = og.get("content", "").strip()

        parts     = [p for p in url.replace(BASE_URL, "").split("/") if p]
        city_slug = parts[1] if len(parts) >= 3 else ""
        slug      = parts[2] if len(parts) >= 3 else ""
        city      = CITY_MAP.get(city_slug.lower(), city_slug.replace("-", " ").title())

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

        page_text = soup.get_text(" ", strip=True).lower()
        amenities = [label for label, kws in AMENITY_KEYWORDS if any(kw in page_text for kw in kws)]

        br_matches = _re.findall(r"(\d)\s*(?:br|bedroom)", page_text, _re.IGNORECASE)
        bedrooms   = sorted(set(int(b) for b in br_matches if 0 < int(b) <= 6))

        return {
            "name":        name or slug.replace("-", " ").title(),
            "slug":        slug,
            "city":        city,
            "city_slug":   city_slug,
            "url":         url,
            "description": desc[:350] if desc else "",
            "image_url":   image_url,
            "amenities":   amenities[:8],
            "bedrooms":    bedrooms,
        }
    except Exception as e:
        print(f"  Scrape error for {url}: {e}")
        return None

# ============================================================
# ORIGINAL PATHS SECTION
# ============================================================
BASE_DIR    = Path("/home/ubuntu/social_automation")
STATE_FILE  = BASE_DIR / "post_state.json"
COMPOUNDS_FILE = BASE_DIR / "compounds_data.json"
BLOG_FILE   = BASE_DIR / "blog_data.json"

# ============================================================
# X (TWITTER) CREDENTIALS
# ============================================================
X_API_KEY             = "5TnCv43zNgUq4OxzRlCbyUILE"
X_API_SECRET          = "5bDEfRJMFEDULacadWm9CPwlfYa7NUEvVYQ06S7thm4nhyvbxe"
X_ACCESS_TOKEN        = "231394170-LU3hOtSqHKZ1MJl26bmJFwdb5EWCXbf2BvznVMWU"
X_ACCESS_TOKEN_SECRET = "VNfeBsJ9KiJWClYeDCldyKi0oyYwONAgldPesFx2J6LLs"
X_TWEETS_URL          = "https://api.twitter.com/2/tweets"
X_MEDIA_URL           = "https://upload.twitter.com/1.1/media/upload.json"

# ============================================================
# FACEBOOK CREDENTIALS
# ============================================================
GRAPH_API_VERSION = "v21.0"
GRAPH_BASE        = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

FB_PAGES = [
    {
        "name":  "Saudi Compounds",
        "id":    "100228283377591",
        "token": "EAAVQCiakMfUBRYdNedGtaYgT2vXGbitbebIRyG2rDZBkJ3ibCcFkUcZARKb8PpfZAuLX2yLWyHLqYmOG0EZAIGMb9YIYje0XHRVNukL2jZCPSeLsVtijDHeGxZAZCapnb3nByPgKhHs13x3K9HCwauUlusudp8zEYZAvt0G1nNCFw5ootBR8ETx4Hf6IlF8TSHORrucd",
    },
    {
        "name":  "Riyadh Compounds",
        "id":    "186853371348233",
        "token": "EAAVQCiakMfUBRer20SZBNj0iakqWSSX6ZC8wStKu8SZCGuzvAN3mdFgWfX1xk8XIBqXSI5FKiL91Wfmc3qo8P8989kfQNw7ARnXka3DMgOGG45Gf1Amot8ongYjwV9MG0n3vsJMcCMCoSEJyeDuBTZCKkfy8eGoY1hb1D5zzixaj9zNZCn1Xo1Tgmq2eeKHcU8jem",
    },
    {
        "name":  "Jeddah Compounds",
        "id":    "146106828783128",
        "token": "EAAVQCiakMfUBReRpS2dWmKBLsKVP5F7WyVDZBGq5V3QmAvQStBIZCznRe3txVcv9Pw99caUAzUiNVrj6pT50etnTOGbfxujfjFqmtnCePpQttclQ91Wd1Hqyoqjh6ofbRitJ77hLdOrNSKpDj7ZCRN91MpOVd72CekxV9YKELinMuwwYZAcWhpQvnyDaQgHNrVaj",
    },
    {
        "name":  "Expatsinksa",
        "id":    "135377393308032",
        "token": "EAAVQCiakMfUBRQjQGbEH77Tm0Lzj7bMdy7pcDZAZC3dHVv80ovjZAqNldYOB3PtocCSHd7ZCKfzn3vFaCtzvhxclcngKDn8agePInZCdPrhC1UXdKe5xaTiKBbRislDfBftjFlDJHTenRnBNfitZABo1DwpLl1eZCpeFESZCSf60q7MmookDEnVwqXuSZAuZCVq4KpHc1ZB",
    },
]

# ============================================================
# HOOK TEMPLATES — Compound Posts
# Varied, genuine-sounding, no dashes, no AI tells
# ============================================================
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

# ============================================================
# HOOK TEMPLATES — Blog Posts
# ============================================================
BLOG_HOOKS = [
    "We just published something useful for anyone looking to move to Saudi Arabia.",
    "If you are searching for a compound in Saudi Arabia, read this first.",
    "This guide will save you a lot of time and frustration.",
    "Everything you need to know, in one place.",
    "We put together a proper guide for expats looking for housing in Saudi Arabia.",
    "New on the blog. This one is worth reading before you start your search.",
    "A lot of people ask us about this. We finally wrote it all down.",
    "Before you sign any lease in Saudi Arabia, read this.",
    "Our latest article covers something most expats wish they knew earlier.",
    "This might be the most useful thing we have published this year.",
    "Thinking about moving to Saudi Arabia? Start here.",
    "We break it all down so you do not have to figure it out on your own.",
    "The compound search in Saudi Arabia can be overwhelming. This helps.",
    "Fresh from the blog. Practical advice for expats in Saudi Arabia.",
    "We covered this topic properly so you have everything in one place.",
]

# ============================================================
# STATE MANAGEMENT
# ============================================================
def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "posted_compound_slugs": [],
        "posted_blog_urls": [],
        "known_compound_urls": [],
        "known_blog_urls": [],
        "last_compound_post_date": None,
        "post_queue": [],
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ============================================================
# COMPOUND DATA
# ============================================================
def load_compounds() -> list:
    if COMPOUNDS_FILE.exists():
        with open(COMPOUNDS_FILE, "r") as f:
            return json.load(f)
    return []


def get_next_compound(state: dict) -> dict | None:
    """Pick the next unposted compound. Resets cycle when all have been posted."""
    compounds = load_compounds()
    if not compounds:
        return None

    posted = set(state.get("posted_compound_slugs", []))
    unposted = [c for c in compounds if c["slug"] not in posted]

    if not unposted:
        # Full cycle complete — reset and start over
        print("All compounds posted. Resetting cycle.")
        state["posted_compound_slugs"] = []
        save_state(state)
        unposted = compounds

    # Pick first in list (deterministic rotation)
    return unposted[0]


def mark_compound_posted(state: dict, compound: dict):
    state.setdefault("posted_compound_slugs", []).append(compound["slug"])
    state["last_compound_post_date"] = datetime.now(timezone.utc).isoformat()
    save_state(state)


# ============================================================
# TEXT BUILDERS
# ============================================================
def pick_hook(templates: list, **kwargs) -> str:
    hook = random.choice(templates)
    return hook.format(**kwargs)


def build_compound_x_text(compound: dict) -> str:
    """Build X (Twitter) post text for a compound. Max 280 chars."""
    city      = compound["city"]
    name      = compound["name"]
    amenities = compound.get("amenities", [])
    url       = compound["url"]

    hook = pick_hook(COMPOUND_HOOKS, city=city)
    amenity_line = " | ".join(amenities[:3]) if amenities else "Premium Amenities"

    text = (
        f"{hook}\n\n"
        f"{name}\n"
        f"{city}, Saudi Arabia\n\n"
        f"{amenity_line}\n\n"
        f"{url}\n\n"
        f"#SaudiArabia #{city.replace(' ', '')} #Compounds #ExpatLiving #RightCompound #سكن_السعودية"
    )

    if len(text) > 280:
        text = (
            f"{hook}\n\n"
            f"{name} | {city}\n\n"
            f"{url}\n\n"
            f"#SaudiArabia #Compounds #ExpatLiving #RightCompound #سكن_السعودية"
        )

    return text


def build_compound_fb_text(compound: dict) -> str:
    """Build Facebook/Instagram post text for a compound."""
    city      = compound["city"]
    name      = compound["name"]
    amenities = compound.get("amenities", [])
    url       = compound["url"]
    desc      = compound.get("description", "")

    hook = pick_hook(COMPOUND_HOOKS, city=city)
    amenity_lines = "\n".join(f"  {a}" for a in amenities[:6]) if amenities else "  Premium Amenities"

    short_desc = ""
    if desc:
        # Take first 2 sentences max
        sentences = re.split(r'(?<=[.!?])\s+', desc.strip())
        short_desc = " ".join(sentences[:2])
        if len(short_desc) > 200:
            short_desc = short_desc[:197] + "..."

    text = f"""{hook}

{name}
{city}, Saudi Arabia

What is included:
{amenity_lines}
"""
    if short_desc:
        text += f"\n{short_desc}\n"

    text += f"""
View full profile and contact details:
{url}

#SaudiArabia #{city.replace(' ', '')} #Compounds #ExpatLiving #RightCompound #سكن_السعودية #ExpatHousing #GatedCommunity"""

    return text


def build_blog_x_text(article: dict) -> str:
    """Build X post text for a blog article."""
    title = article["title"]
    url   = article["url"]
    hook  = pick_hook(BLOG_HOOKS)

    text = (
        f"{hook}\n\n"
        f"{title}\n\n"
        f"{url}\n\n"
        f"#SaudiArabia #ExpatLiving #Compounds #RightCompound #سكن_السعودية"
    )

    if len(text) > 280:
        text = (
            f"{hook}\n\n"
            f"{url}\n\n"
            f"#SaudiArabia #Compounds #RightCompound #سكن_السعودية"
        )

    return text


def build_blog_fb_text(article: dict) -> str:
    """Build Facebook/Instagram post text for a blog article."""
    title = article["title"]
    url   = article["url"]
    hook  = pick_hook(BLOG_HOOKS)

    return f"""{hook}

{title}

Read the full article here:
{url}

#SaudiArabia #ExpatLiving #Compounds #RightCompound #سكن_السعودية #ExpatHousing"""


# ============================================================
# X (TWITTER) POSTING
# ============================================================
def _x_oauth() -> OAuth1Session:
    return OAuth1Session(
        client_key=X_API_KEY,
        client_secret=X_API_SECRET,
        resource_owner_key=X_ACCESS_TOKEN,
        resource_owner_secret=X_ACCESS_TOKEN_SECRET,
    )


def upload_image_to_x(image_url: str) -> str | None:
    """Download image and upload to X Media API v1.1."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RightCompound/1.0)"}
        r = requests.get(image_url, headers=headers, timeout=30)
        r.raise_for_status()
        tmp = "/tmp/rc_post_image.jpg"
        with open(tmp, "wb") as f:
            f.write(r.content)
        oauth = _x_oauth()
        with open(tmp, "rb") as img:
            resp = oauth.post(X_MEDIA_URL, files={"media": img})
        if resp.status_code == 200:
            return resp.json()["media_id_string"]
        print(f"  X media upload failed: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  X image error: {e}")
        return None


def post_to_x(text: str, image_url: str = None) -> dict:
    """Post a tweet via X API v2."""
    oauth   = _x_oauth()
    payload = {"text": text}

    if image_url:
        media_id = upload_image_to_x(image_url)
        if media_id:
            payload["media"] = {"media_ids": [media_id]}

    try:
        resp = oauth.post(X_TWEETS_URL, json=payload)
        if resp.status_code == 201:
            tweet_id = resp.json()["data"]["id"]
            url      = f"https://x.com/rightcompound/status/{tweet_id}"
            print(f"  X posted: {url}")
            return {"platform": "X", "status": "success", "url": url, "id": tweet_id}
        else:
            print(f"  X failed: {resp.status_code} {resp.text[:300]}")
            return {"platform": "X", "status": "error", "error": resp.text[:300]}
    except Exception as e:
        print(f"  X exception: {e}")
        return {"platform": "X", "status": "error", "error": str(e)}


# ============================================================
# FACEBOOK POSTING
# ============================================================
def post_to_facebook(text: str, image_url: str = None, pages: list = None) -> list:
    """Post to one or more Facebook pages. Returns list of results."""
    if pages is None:
        pages = FB_PAGES

    results = []
    for page in pages:
        try:
            if image_url:
                endpoint = f"{GRAPH_BASE}/{page['id']}/photos"
                payload  = {"url": image_url, "caption": text, "access_token": page["token"]}
            else:
                endpoint = f"{GRAPH_BASE}/{page['id']}/feed"
                payload  = {"message": text, "access_token": page["token"]}

            resp   = requests.post(endpoint, data=payload, timeout=30)
            result = resp.json()

            if "id" in result:
                post_id = result["id"]
                print(f"  FB [{page['name']}] posted: {post_id}")
                results.append({"platform": "Facebook", "page": page["name"], "status": "success", "id": post_id})
            else:
                err = result.get("error", {}).get("message", "Unknown")
                code = result.get("error", {}).get("code", "")
                print(f"  FB [{page['name']}] failed [{code}]: {err}")
                results.append({"platform": "Facebook", "page": page["name"], "status": "error", "error": err, "code": code})
        except Exception as e:
            print(f"  FB [{page['name']}] exception: {e}")
            results.append({"platform": "Facebook", "page": page["name"], "status": "error", "error": str(e)})

    return results


# ============================================================
# INSTAGRAM POSTING (via Facebook Graph API)
# ============================================================
def post_to_instagram(text: str, image_url: str, ig_accounts: list = None) -> list:
    """
    Post to Instagram Business accounts linked to Facebook pages.
    ig_accounts: list of {"name": ..., "ig_user_id": ..., "token": ...}
    When Meta approves, pass in the IG account IDs here.
    """
    if not ig_accounts:
        print("  Instagram: no accounts configured yet (pending Meta approval)")
        return [{"platform": "Instagram", "status": "skipped", "reason": "pending Meta approval"}]

    results = []
    for acct in ig_accounts:
        try:
            # Step 1: Create media container
            container_url = f"{GRAPH_BASE}/{acct['ig_user_id']}/media"
            container_payload = {
                "image_url":    image_url,
                "caption":      text,
                "access_token": acct["token"],
            }
            r1 = requests.post(container_url, data=container_payload, timeout=30)
            r1_data = r1.json()
            if "id" not in r1_data:
                err = r1_data.get("error", {}).get("message", "Container creation failed")
                print(f"  IG [{acct['name']}] container failed: {err}")
                results.append({"platform": "Instagram", "account": acct["name"], "status": "error", "error": err})
                continue

            container_id = r1_data["id"]
            time.sleep(2)  # Brief pause before publishing

            # Step 2: Publish container
            publish_url = f"{GRAPH_BASE}/{acct['ig_user_id']}/media_publish"
            publish_payload = {"creation_id": container_id, "access_token": acct["token"]}
            r2 = requests.post(publish_url, data=publish_payload, timeout=30)
            r2_data = r2.json()

            if "id" in r2_data:
                print(f"  IG [{acct['name']}] posted: {r2_data['id']}")
                results.append({"platform": "Instagram", "account": acct["name"], "status": "success", "id": r2_data["id"]})
            else:
                err = r2_data.get("error", {}).get("message", "Publish failed")
                print(f"  IG [{acct['name']}] publish failed: {err}")
                results.append({"platform": "Instagram", "account": acct["name"], "status": "error", "error": err})

        except Exception as e:
            print(f"  IG [{acct['name']}] exception: {e}")
            results.append({"platform": "Instagram", "account": acct["name"], "status": "error", "error": str(e)})

    return results


# ============================================================
# HIGH-LEVEL: POST A COMPOUND
# ============================================================
def post_compound(compound: dict, ig_accounts: list = None) -> dict:
    """Post a compound to all platforms. Returns combined result."""
    print(f"\nPosting compound: {compound['name']} ({compound['city']})")
    print(f"  URL: {compound['url']}")

    image_url = compound.get("image_url") or None
    x_text    = build_compound_x_text(compound)
    fb_text   = build_compound_fb_text(compound)

    results = {
        "compound":   compound["name"],
        "city":       compound["city"],
        "url":        compound["url"],
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "platforms":  [],
    }

    # X
    x_result = post_to_x(x_text, image_url)
    results["platforms"].append(x_result)

    # Facebook (only if tokens are valid — will succeed once Meta approves)
    fb_results = post_to_facebook(fb_text, image_url)
    results["platforms"].extend(fb_results)

    # Instagram
    ig_results = post_to_instagram(fb_text, image_url, ig_accounts)
    results["platforms"].extend(ig_results)

    return results


# ============================================================
# HIGH-LEVEL: POST A BLOG ARTICLE
# ============================================================
def fetch_article_og_image(url: str) -> str | None:
    """Fetch the og:image URL from a blog article page."""
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", {"property": "og:image"})
        if og and og.get("content"):
            img_url = og["content"].strip()
            if img_url.startswith("http"):
                print(f"  Article image: {img_url}")
                return img_url
        return None
    except Exception as e:
        print(f"  Could not fetch article OG image: {e}")
        return None


def post_blog_article(article: dict, ig_accounts: list = None) -> dict:
    """Post a blog article to all platforms with OG image."""
    print(f"\nPosting blog article: {article['title']}")
    print(f"  URL: {article['url']}")

    # Fetch OG image from the article page
    image_url = article.get("image_url") or fetch_article_og_image(article["url"])

    x_text  = build_blog_x_text(article)
    fb_text = build_blog_fb_text(article)

    results = {
        "article":   article["title"],
        "url":       article["url"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platforms": [],
    }

    # X — post with image if available
    x_result = post_to_x(x_text, image_url)
    results["platforms"].append(x_result)

    # Facebook — post with image if available
    fb_results = post_to_facebook(fb_text, image_url)
    results["platforms"].extend(fb_results)

    # Instagram — post with image if available, skip if not
    if image_url and ig_accounts:
        ig_results = post_to_instagram(fb_text, image_url, ig_accounts)
        results["platforms"].extend(ig_results)
    elif image_url:
        results["platforms"].append({"platform": "Instagram", "status": "skipped", "reason": "pending Meta approval"})
    else:
        results["platforms"].append({"platform": "Instagram", "status": "skipped", "reason": "no image found"})

    return results


# ============================================================
# SAVE POST LOG
# ============================================================
def log_post_result(result: dict, log_file: str = None):
    if not log_file:
        log_file = str(BASE_DIR / "post_log.json")
    log = []
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            try:
                log = json.load(f)
            except Exception:
                log = []
    log.append(result)
    with open(log_file, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
