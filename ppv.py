from functools import partial

import httpx
from playwright.async_api import async_playwright
import logging
import json

# --- Standalone utility classes (from roxie.py/watchfooty.py) ---
import json
import os
class Cache:
    def __init__(self, filename, exp=None):
        self.filename = filename
        self.exp = exp
    def load(self, *a, **k):
        if not os.path.exists(self.filename):
            return {}
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    def write(self, data):
        with open(self.filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
class Time:
    @staticmethod
    def now():
        import datetime
        return datetime.datetime.now()
    @staticmethod
    def clean(dt):
        return dt
    @staticmethod
    def from_ts(ts):
        import datetime
        return datetime.datetime.fromtimestamp(ts)
    def delta(self, **kwargs):
        import datetime
        return self + datetime.timedelta(**kwargs)
    def timestamp(self):
        return self.timestamp()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
def get_logger(name):
    return logging.getLogger(name)
class Leagues:
    @staticmethod
    def get_tvg_info(sport, event): return (None, None)
leagues = Leagues()

# --- Real network/process_event implementation ---
class Network:
    @staticmethod
    async def get_base(mirrors):
        # Try each mirror, return the first that works
        import httpx
        for url in mirrors:
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(url, timeout=5)
                    if r.status_code == 200:
                        return url
            except Exception:
                continue
        return mirrors[0]
    @staticmethod
    async def safe_process(handler, url_num, log):
        try:
            return await handler()
        except Exception as e:
            log.warning(f"Exception in handler: {e}")
            return None
    @staticmethod
    async def browser(p, browser=None):
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        return browser, context
    @staticmethod
    async def process_event(url, url_num, context, timeout=6, log=None):
        page = await context.new_page()
        captured = []
        import asyncio
        got_one = asyncio.Event()
        def handler(request):
            u = request.url
            if ".m3u8" in u:
                captured.append(u)
                got_one.set()
        page.on("request", handler)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(1_500)
            wait_task = asyncio.create_task(got_one.wait())
            try:
                await asyncio.wait_for(wait_task, timeout=timeout)
            except asyncio.TimeoutError:
                if log: log.warning(f"URL {url_num}) Timed out waiting for M3U8.")
                return None
            finally:
                if not wait_task.done():
                    wait_task.cancel()
                    try:
                        await wait_task
                    except asyncio.CancelledError:
                        pass
            if captured:
                if log: log.info(f"URL {url_num}) Captured M3U8")
                return captured[-1]
            if log: log.warning(f"URL {url_num}) No M3U8 captured after waiting.")
            return None
        except Exception as e:
            if log: log.warning(f"URL {url_num}) Exception while processing: {e}")
            return None
        finally:
            page.remove_listener("request", handler)
            await page.close()
network = Network()

log = get_logger(__name__)

urls: dict[str, dict[str, str | float]] = {}

TAG = "PPV"

CACHE_FILE = Cache(f"{TAG.lower()}.json", exp=10_800)
API_FILE = Cache(f"{TAG.lower()}-api.json", exp=19_800)

API_MIRRORS = [
    "https://old.ppv.to/api/streams",
    "https://api.ppvs.su/api/streams",
    "https://api.ppv.to/api/streams",
]

BASE_MIRRORS = [
    "https://old.ppv.to",
    "https://ppvs.su",
    "https://ppv.to",
]


async def refresh_api_cache(
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, dict[str, str]]:
    log.info(f"Refreshing API cache from {url}")

    try:
        r = await client.get(url, timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error(f'Failed to fetch "{url}": {e}')
        return {}

    data = r.json()
    log.info(f"Fetched API data: {len(data) if hasattr(data, '__len__') else 'ok'} items")
    try:
        API_FILE.write(data)
        log.info(f"Wrote API cache to {API_FILE.filename}")
    except Exception as e:
        log.warning(f"Failed to write API cache: {e}")
    return data


async def get_events(
    client: httpx.AsyncClient,
    api_url: str,
    cached_keys: set[str],
) -> list[dict[str, str]]:
    api_data = API_FILE.load(per_entry=False)
    if not api_data:
        log.info("No API cache found or empty; refreshing now")
        api_data = await refresh_api_cache(client, api_url)
    else:
        log.info(f"Loaded API cache from {API_FILE.filename}")

    events = []

    now = Time.clean(Time.now())
    start_dt = now.delta(hours=-12)
    end_dt = now.delta(hours=12)
    log.info(f"Event time window: {start_dt} to {end_dt}")

    for stream_group in api_data.get("streams", []):
        sport = stream_group["category"]
        if sport == "24/7 Streams":
            continue
        for event in stream_group.get("streams", []):
            name = event.get("name")
            start_ts = event.get("starts_at")
            logo = event.get("poster")
            iframe = event.get("iframe")
            if not (name and start_ts and iframe):
                log.info(f"Skipping event (missing data): {name}")
                continue
            key = f"[{sport}] {name} ({TAG})"
            if cached_keys & {key}:
                log.info(f"Skipping cached event: {key}")
                continue
            event_dt = Time.from_ts(start_ts)
            if not start_dt <= event_dt <= end_dt:
                log.info(f"Skipping event (out of window): {key} at {event_dt}")
                continue
            log.info(f"Adding event: {key} at {event_dt}")
            events.append(
                {
                    "sport": sport,
                    "event": name,
                    "link": iframe,
                    "logo": logo,
                    "timestamp": event_dt.timestamp(),
                }
            )
    return events


async def scrape(client: httpx.AsyncClient) -> None:
    cached_urls = CACHE_FILE.load()
    cached_count = len(cached_urls)
    urls.update(cached_urls)
    log.info(f"Loaded {cached_count} event(s) from cache")
    base_url = await network.get_base(BASE_MIRRORS)
    api_url = await network.get_base(API_MIRRORS)
    log.info(f"Using base mirror: {base_url}")
    log.info(f"Using API mirror: {api_url}")
    if not (base_url and api_url):
        log.warning("No working PPV mirrors")
        CACHE_FILE.write(cached_urls)
        return
    log.info(f'Scraping from "{base_url}"')
    log.info(f"Using base mirror: {base_url}")
    log.info(f"Using API mirror (selected): {api_url}")

    # Force-fetch the first API mirror raw response and save for debugging
    try:
        async with httpx.AsyncClient() as client2:
            resp = await client2.get(API_MIRRORS[0], timeout=10)
            resp.raise_for_status()
            try:
                raw = resp.json()
            except Exception:
                raw = resp.text
            with open("ppv-api.json", "w", encoding="utf-8") as jf:
                json.dump(raw, jf, ensure_ascii=False, indent=2)
            log.info(f"Wrote raw API response to ppv-api.json (mirror {API_MIRRORS[0]})")
            # Use the first mirror as api_url for subsequent processing
            api_url = API_MIRRORS[0]
    except Exception as e:
        log.warning(f"Direct API fetch failed: {e}")
    events = await get_events(
        client,
        api_url,
        set(cached_urls.keys()),
    )
    log.info(f"Processing {len(events)} new URL(s)")
    if events:
        async with async_playwright() as p:
            browser, context = await network.browser(p, browser="brave")
            for i, ev in enumerate(events, start=1):
                handler = partial(
                    network.process_event,
                    url=ev["link"],
                    url_num=i,
                    context=context,
                    timeout=6,
                    log=log,
                )
                url = await network.safe_process(
                    handler,
                    url_num=i,
                    log=log,
                )
                if url:
                    sport, event, logo, ts, link = (
                        ev["sport"],
                        ev["event"],
                        ev["logo"],
                        ev["timestamp"],
                        ev["link"],
                    )
                    key = f"[{sport}] {event} ({TAG})"
                    tvg_id, pic = leagues.get_tvg_info(sport, event)
                    entry = {
                        "url": url,
                        "logo": logo or pic,
                        "base": base_url,
                        "timestamp": ts,
                        "id": tvg_id or "Live.Event.us",
                        "link": link,
                    }
                    urls[key] = cached_urls[key] = entry
            await browser.close()
    if new_count := len(cached_urls) - cached_count:
        log.info(f"Collected and cached {new_count} new event(s)")
    else:
        log.info("No new events found")
    CACHE_FILE.write(cached_urls)

    # Export only working links to M3U playlist
    m3u_lines = ['#EXTM3U']
    for key, entry in cached_urls.items():
        url = entry.get("url")
        if not url:
            continue
        m3u_lines.append(f'#EXTINF:-1 tvg-id="{entry.get("id", "")}" tvg-logo="{entry.get("logo", "")}",{key}')
        m3u_lines.append(url)
    with open(f"{TAG.lower()}.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines))
    log.info(f"Exported working events to {TAG.lower()}.m3u")
