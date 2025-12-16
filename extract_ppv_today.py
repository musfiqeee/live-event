import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re

from playwright.sync_api import sync_playwright


INPUT_JSON = Path("ppv-api.json")
OUTPUT_M3U = Path("ppv.m3u")


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


def main():
    if not INPUT_JSON.exists():
        print("ppv-api.json not found. Fetch the API first.")
        return 1

    data = json.loads(INPUT_JSON.read_text(encoding="utf-8"))
    streams_root = data.get("streams") or []

    # compute today's UTC date window and next day
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
        print("No streams for today+tomorrow found in ppv-api.json")
        return 0

    out_lines = ["#EXTM3U"]
    print(f"Found {len(selected)} streams for today+tomorrow; extracting with Playwright...")

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
            else:
                # if the iframe is already an m3u8, keep it
                if iframe and ".m3u8" in iframe and not iframe.startswith("http"):
                    pass

            out_lines.append(info)
            out_lines.append(final_uri)
            # brief pause
            time.sleep(0.5)

    OUTPUT_M3U.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {OUTPUT_M3U} with {len(selected)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
