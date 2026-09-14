#!/usr/bin/env python3
"""
Watch peakedinhighskool.com for a new Half-PPR trade value chart.
When the chart changes, slice it into readable chunks and post it to a Discord webhook.

Detection works off the date stamp baked into the image filename
(e.g. 1QBHalf4pt_20251111.png). If that stamp differs from the last one
we posted, it's a new chart.
"""

import io
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

# ---------------------------------------------------------------- config

CHART_PAGE = "https://peakedinhighskool.com/fantasy-trade-value-chart/"

# Which chart to grab. The page labels its images in the alt text.
FORMAT_LABEL = "Half-PPR"
ALT_KEYWORD = "half-ppr"
HEADING_KEYWORD = "half-ppr"

STATE_FILE = Path(__file__).parent / "state.json"

SLICE_COUNT = 3           # split the tall chart into this many chunks
SLICE_OVERLAP = 40        # px of overlap so no row gets cut in half
MAX_UPLOAD_BYTES = 7_500_000   # stay under Discord's 10MB ceiling

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------- state


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            log("state.json was malformed, starting fresh")
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def log(msg):
    print(f"[bot] {msg}", flush=True)


# ---------------------------------------------------------------- scraping


def fetch_page():
    resp = requests.get(CHART_PAGE, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def image_url_from_tag(tag):
    """The page lazy-loads images, so the real URL may live in a data- attribute."""
    for attr in ("data-lazy-src", "data-src", "data-original", "src"):
        val = (tag.get(attr) or "").strip()
        if val and not val.startswith("data:"):
            return val

    # Last resort: pull the first candidate out of a srcset
    for attr in ("data-lazy-srcset", "srcset"):
        val = (tag.get(attr) or "").strip()
        if val:
            first = val.split(",")[0].strip().split(" ")[0]
            if first and not first.startswith("data:"):
                return first
    return None


def find_chart_image(soup):
    """Locate the Half-PPR chart image, by alt text first, then by heading position."""
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").lower()
        if ALT_KEYWORD in alt and "trade value" in alt:
            url = image_url_from_tag(img)
            if url:
                log(f"matched on alt text: {alt!r}")
                return url

    # Fallback: find the Half-PPR heading and take the next image under it
    for heading in soup.find_all(re.compile(r"^h[1-4]$")):
        text = heading.get_text(" ", strip=True).lower()
        if HEADING_KEYWORD in text and "trade value" in text:
            img = heading.find_next("img")
            while img is not None:
                url = image_url_from_tag(img)
                if url and "wp-content/uploads" in url:
                    log(f"matched on heading: {text!r}")
                    return url
                img = img.find_next("img")

    return None


def normalize_image_url(url):
    """
    Turn a Jetpack CDN URL into the original full-resolution file.
    https://i0.wp.com/peakedinhighskool.com/wp-content/.../x.png?fit=... ->
    https://peakedinhighskool.com/wp-content/.../x.png
    """
    if url.startswith("//"):
        url = "https:" + url

    parsed = urlparse(url)

    if re.match(r"^i\d\.wp\.com$", parsed.netloc):
        # Path is /<real-host>/<real-path>
        parts = parsed.path.lstrip("/").split("/", 1)
        if len(parts) == 2:
            parsed = parsed._replace(netloc=parts[0], path="/" + parts[1])

    parsed = parsed._replace(scheme="https", query="", fragment="")
    return urlunparse(parsed)


def extract_stamp(url):
    """Pull the YYYYMMDD date stamp out of the image filename."""
    match = re.search(r"(\d{8})", os.path.basename(urlparse(url).path))
    return match.group(1) if match else None


def extract_week(soup):
    """Find the week number from the page headings or meta description."""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    candidates = []
    if meta and meta.get("content"):
        candidates.append(meta["content"])
    for heading in soup.find_all(re.compile(r"^h[1-4]$")):
        candidates.append(heading.get_text(" ", strip=True))

    for text in candidates:
        match = re.search(r"week\s+(\d{1,2})", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


# ---------------------------------------------------------------- images


def download_image(url):
    resp = requests.get(url, headers={**HEADERS, "Referer": CHART_PAGE}, timeout=60)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def encode(img):
    """PNG if it fits, WebP if not, downscaled WebP as a last resort."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    if buf.tell() <= MAX_UPLOAD_BYTES:
        return buf.getvalue(), "png"

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=92, method=6)
    if buf.tell() <= MAX_UPLOAD_BYTES:
        return buf.getvalue(), "webp"

    scaled = img.resize((int(img.width * 0.75), int(img.height * 0.75)), Image.LANCZOS)
    buf = io.BytesIO()
    scaled.save(buf, format="WEBP", quality=88, method=6)
    return buf.getvalue(), "webp"


def slice_image(img, count=SLICE_COUNT, overlap=SLICE_OVERLAP):
    """
    Cut a very tall chart into horizontal chunks.
    Discord squashes extreme aspect ratios into an unreadable sliver otherwise.
    """
    if img.height / img.width < 2.0:
        return [img]

    step = img.height // count
    chunks = []
    for i in range(count):
        top = max(0, i * step - (overlap if i else 0))
        bottom = img.height if i == count - 1 else min(img.height, (i + 1) * step + overlap)
        chunks.append(img.crop((0, top, img.width, bottom)))
    return chunks


# ---------------------------------------------------------------- discord


def post_to_discord(webhook, message, chunks):
    """First request carries the text, the rest are image-only follow-ups."""
    for i, chunk in enumerate(chunks):
        data, ext = encode(chunk)
        payload = {
            "allowed_mentions": {"parse": []},  # never ping anyone
        }
        if i == 0:
            payload["content"] = message

        files = {
            "payload_json": (None, json.dumps(payload), "application/json"),
            "files[0]": (f"trade_values_part{i + 1}.{ext}", data, f"image/{ext}"),
        }

        resp = requests.post(f"{webhook}?wait=true", files=files, timeout=120)
        if resp.status_code == 429:
            wait = resp.json().get("retry_after", 5)
            log(f"rate limited, waiting {wait}s")
            time.sleep(float(wait) + 1)
            resp = requests.post(f"{webhook}?wait=true", files=files, timeout=120)

        resp.raise_for_status()
        log(f"posted part {i + 1}/{len(chunks)} ({len(data) // 1024} KB, .{ext})")
        time.sleep(1)


# ---------------------------------------------------------------- main


def main():
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        log("DISCORD_WEBHOOK_URL is not set")
        return 1

    force = os.environ.get("FORCE_POST", "").lower() in ("1", "true", "yes")

    soup = fetch_page()

    raw_url = find_chart_image(soup)
    if not raw_url:
        log(f"could not find the {FORMAT_LABEL} chart image on the page")
        return 1

    url = normalize_image_url(raw_url)
    stamp = extract_stamp(url)
    week = extract_week(soup)
    log(f"found chart: week={week} stamp={stamp} url={url}")

    if not stamp:
        log("no date stamp in the filename, refusing to post (would break dedup)")
        return 1

    state = load_state()
    if state.get("last_stamp") == stamp and not force:
        log("already posted this chart, nothing to do")
        return 0

    img = download_image(url)
    log(f"downloaded {img.width}x{img.height}")

    chunks = slice_image(img)
    log(f"sliced into {len(chunks)} part(s)")

    week_label = f"Week {week}" if week else "Latest"
    message = (
        f"**{week_label} {FORMAT_LABEL} Trade Value Chart**\n"
        f"Full resolution: <{CHART_PAGE}>\n"
        f"Chart by PeakedInHighSkool"
    )

    post_to_discord(webhook, message, chunks)

    state["last_stamp"] = stamp
    state["last_week"] = week
    state["last_url"] = url
    state["last_posted_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
