"""Drop-in alternative to gem.py that uses Google Gemini instead of Groq.

Same command line, same prompt, same output ({"components": [...]} on stdout, time on stderr),
so pi_scan.py can use either:   ./scan.sh --gem ~/kiosk-proto/gem_gemini.py
Needs GEMINI_API_KEY (from https://aistudio.google.com/apikey). Standard library + Pillow only.
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
PROMPT = (
    "Analyze ONLY the electronic components physically visible in this image. "
    "Do NOT list components merely because they are related to electronics. "
    "Do NOT infer components that cannot be visually confirmed. "
    "Return each component TYPE only once. "
    "Maximum 20 component types. "
    "If uncertain, omit the component. "
    "Return ONLY valid JSON in exactly this format: "
    '{"components": ["resistor", "capacitor", "diode"]}'
)


def analyze(path):
    start = time.perf_counter()

    with Image.open(path) as im:
        im.thumbnail((512, 512))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=70)

    body = json.dumps({
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
        ]}],
        # thinkingBudget 0: 2.5 Flash would otherwise spend the token budget thinking and cut the JSON short
        "generationConfig": {"temperature": 0, "maxOutputTokens": 1024, "responseMimeType": "application/json",
                             "thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        sys.exit(f"Gemini error {e.code}: {' '.join(detail.split())[:200]}")   # one line, for pi_scan

    parts = reply.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    print("".join(p.get("text", "") for p in parts).strip() or '{"components": []}')
    print(f"Time: {time.perf_counter() - start:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    analyze(sys.argv[1])
