import json
import os
from html import escape


def safe(text: str) -> str:
    if not text:
        return ""
    return escape(str(text)).replace('\n', ' ').strip()


def generate(input_path: str = "ppv-api.json", output_path: str = "ppv.m3u"):
    if not os.path.exists(input_path):
        print(f"Input file '{input_path}' not found.")
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = ["#EXTM3U"]

    streams_root = data.get("streams") or []
    for group in streams_root:
        category = group.get("category") or group.get("category_name") or ""
        for s in group.get("streams", []):
            name = safe(s.get("name") or s.get("title") or "Untitled")
            sid = s.get("id")
            poster = s.get("poster") or ""
            iframe = s.get("iframe") or s.get("url") or ""

            # build attributes: tvg-id, tvg-logo, group-title
            attrs = []
            if sid is not None:
                attrs.append(f'tvg-id="{sid}"')
            if poster:
                attrs.append(f'tvg-logo="{poster}"')
            if category:
                attrs.append(f'group-title="{safe(category)}"')

            attr_str = " ".join(attrs)
            lines.append(f'#EXTINF:-1 {attr_str},{name}')
            # fallback to iframe URL as stream URI
            lines.append(iframe or "")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote {len(lines)//2} entries to '{output_path}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(generate())
