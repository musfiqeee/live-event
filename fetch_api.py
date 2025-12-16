# fetch_api.py
import httpx, json

mirrors = [
    "https://old.ppv.to/api/streams",
    "https://api.ppvs.su/api/streams",
    "https://api.ppv.to/api/streams",
]

for url in mirrors:
    try:
        print("Trying:", url)
        r = httpx.get(url, timeout=10)
        print("Status:", r.status_code)
        text = r.text
        # show a preview
        print(text[:1000].replace("\n", " ") + ("\n..." if len(text) > 1000 else ""))
        # try to save JSON, fallback to raw text
        try:
            payload = r.json()
            with open("ppv-api.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            with open("ppv-api.json", "w", encoding="utf-8") as f:
                f.write(text)
        print("Saved to ppv-api.json")
        break
    except Exception as e:
        print("Error:", e)