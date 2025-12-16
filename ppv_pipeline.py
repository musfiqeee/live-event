"""ppv_pipeline.py

Single-file pipeline to:
- fetch PPV API mirrors and save `ppv-api.json`
- filter streams for today + tomorrow (UTC)
- visit embed pages with Playwright to capture direct .m3u8 URLs
- write final `ppv.m3u`

Usage: python ppv_pipeline.py
"""
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import sys

import httpx
from playwright.sync_api import sync_playwright


MIRRORS = [
    "https://old.ppv.to/api/streams",
    "https://api.ppvs.su/api/streams",
    "https://api.ppv.to/api/streams",
]

API_FILE = Path("ppv-api.json")
OUT_M3U = Path("ppv.m3u")


def fetch_api(timeout: int = 10) -> dict | None:
    for url in MIRRORS:
        try:
            print("Trying:", url)
            r = httpx.get(url, timeout=timeout)
            print("Status:", r.status_code)
            if r.status_code != 200:
                continue
            try:
                payload = r.json()
            except Exception:
                print("Response not JSON")
                payload = None
            if payload is not None:
                API_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Saved API to {API_FILE}")
                return payload
        except Exception as e:
            print("Fetch error:", e)
    print("Failed to fetch API from mirrors")
    return None


def read_api() -> dict | None:
    if not API_FILE.exists():
        return None
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print("Failed to read api file:", e)
        return None


def find_m3u8_in_html(html: str):
    return list(dict.fromkeys(re.findall(r'https?://[^\"\'\s>]+\.m3u8[^\"\'\s>]*', html)))


def extract_from_embed(play, url: str, timeout: int = 20000):
    found = []
    browser = None
    context = None
    try:
        browser = play.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_request(req):
            u = req.url
            if ".m3u8" in u and u not in found:
                found.append(u)

        page.on("request", on_request)

        try:
            page.goto(url, timeout=timeout, wait_until="networkidle")
        except Exception:
            try:
                page.goto(url, timeout=timeout)
            except Exception as e:
                print(f"goto failed for {url}: {e}")

        time.sleep(1.5)

        try:
            html = page.content()
            for u in find_m3u8_in_html(html):
                if u not in found:
                    found.append(u)
        except Exception:
            pass

    except Exception as e:
        print(f"Playwright error for {url}: {e}")
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
    return found


def build_m3u_from_api(data: dict) -> int:
    streams_root = data.get("streams") or []

    now = datetime.now(timezone.utc)
    start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end_next = start_today + timedelta(days=2) - timedelta(seconds=1)

    selected = []
    for grp in streams_root:
        for s in grp.get("streams", []):
            starts = s.get("starts_at")
            if not isinstance(starts, int):
                continue
            dt = datetime.fromtimestamp(starts, tz=timezone.utc)
            if start_today <= dt <= end_next:
                selected.append((grp.get("category"), s))

    if not selected:
        print("No streams for today+tomorrow found in API")
        return 0

    lines = ["#EXTM3U"]
    with sync_playwright() as p:
        for idx, (category, s) in enumerate(selected, 1):
            name = s.get("name") or s.get("title") or "Untitled"
            sid = s.get("id")
            poster = s.get("poster") or ""
            iframe = s.get("iframe") or s.get("url") or ""
            starts = s.get("starts_at")
            dt = datetime.fromtimestamp(starts, tz=timezone.utc)

            attrs = []
            if sid is not None:
                attrs.append(f'tvg-id="{sid}"')
            if poster:
                attrs.append(f'tvg-logo="{poster}"')
            if category:
                attrs.append(f'group-title="{category}"')

            attr_str = " ".join(attrs)
            info = f'#EXTINF:-1 {attr_str},{name} [{dt.date()}]'

            final_uri = iframe
            if iframe and ("pooembed" in iframe or "embed" in iframe):
                print(f"[{idx}/{len(selected)}] Visiting embed: {iframe}")
                try:
                    found = extract_from_embed(p, iframe)
                    if found:
                        final_uri = found[0]
                        print(f"  -> extracted: {final_uri}")
                    else:
                        print("  -> no m3u8 extracted; keeping iframe")
                except Exception as e:
                    print(f"  -> error extracting {iframe}: {e}")

            lines.append(info)
            lines.append(final_uri)
            time.sleep(0.5)

    OUT_M3U.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_M3U} with {len(selected)} entries")
    return len(selected)


def main():
    # Step 1: fetch API (if needed)
    data = None
    if API_FILE.exists():
        data = read_api()
    if not data:
        data = fetch_api()
        if data is None:
            print("No API data available; aborting")
            return 1

    # Step 2: build final m3u
    count = build_m3u_from_api(data)
    if count == 0:
        print("No entries written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
