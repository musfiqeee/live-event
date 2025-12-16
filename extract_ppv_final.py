import re
import time
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


INPUT = Path("ppv.m3u")
OUTPUT = Path("ppv-final.m3u")


def parse_m3u(path: Path):
    lines = [l.rstrip('\n') for l in path.read_text(encoding="utf-8").splitlines()]
    entries = []
    if not lines or not lines[0].startswith("#EXTM3U"):
        return []
    i = 1
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            info = lines[i]
            uri = lines[i+1] if i+1 < len(lines) else ""
            entries.append((info, uri))
            i += 2
        else:
            i += 1
    return entries


def find_m3u8_in_html(html: str):
    # naive regex to find .m3u8 urls
    m = re.findall(r'https?://[^\"\'\s>]+\.m3u8[^\"\'\s>]*', html)
    return list(dict.fromkeys(m))


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
            if ".m3u8" in u:
                if u not in found:
                    found.append(u)

        page.on("request", on_request)

        try:
            page.goto(url, timeout=timeout, wait_until="networkidle")
        except Exception:
            try:
                page.goto(url, timeout=timeout)
            except Exception as e:
                print(f"goto failed for {url}: {e}")

        # allow extra network activity
        time.sleep(2)

        # try to inspect HTML for m3u8
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
    if not INPUT.exists():
        print("Input ppv.m3u not found. Run generate_ppv_m3u.py first.")
        return 1

    entries = parse_m3u(INPUT)
    print(f"Parsed {len(entries)} entries from {INPUT}")

    out_lines = ["#EXTM3U"]

    try:
        with sync_playwright() as p:
            for idx, (info, uri) in enumerate(entries, 1):
                try:
                    print(f"[{idx}/{len(entries)}] Processing: {uri}")
                    if "pooembed.top/embed" in uri or "pooembed.top" in uri or "pooembed" in uri:
                        found = []
                        try:
                            found = extract_from_embed(p, uri)
                        except Exception as e:
                            print(f"Error extracting from {uri}: {e}")

                        if found:
                            chosen = found[0]
                            print(f"  -> found m3u8: {chosen}")
                            out_lines.append(info)
                            out_lines.append(chosen)
                        else:
                            print(f"  -> no m3u8 found, keeping embed URL as fallback")
                            out_lines.append(info)
                            out_lines.append(uri)
                    else:
                        # copy as-is
                        out_lines.append(info)
                        out_lines.append(uri)
                except KeyboardInterrupt:
                    print("Interrupted by user, stopping.")
                    break
                except Exception as e:
                    print(f"Unhandled error for {uri}: {e}")
                    out_lines.append(info)
                    out_lines.append(uri)
    except KeyboardInterrupt:
        print("Interrupted during Playwright session. Writing partial output.")
    except Exception as e:
        print(f"Playwright session error: {e}")

    OUTPUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
