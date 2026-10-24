
import os
import sys
import io
import time
import base64
from PIL import Image
from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "qwen/qwen3.8-27b"

def analyze(path):
    start = time.perf_counter()

    with Image.open(path) as im:
        im.thumbnail((512, 512))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=70)

    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
        "Analyze ONLY the electronic components physically visible in this image. "
        "Do NOT list components merely because they are related to electronics. "
        "Do NOT infer components that cannot be visually confirmed. "
        "Return each component TYPE only once. "
        "Maximum 20 component types. "
        "If uncertain, omit the component. "
        "Return ONLY valid JSON in exactly this format: "
        '{"components": ["resistor", "capacitor", "diode"]}'
    )
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encoded}"
                    }
                }
            ]
        }],
        temperature=0,
        max_completion_tokens=500,
        response_format={"type": "json_object"},
    )

    print(response.choices[0].message.content)
    print(f"Time: {time.perf_counter() - start:.2f}s",
          file=sys.stderr)

if __name__ == "__main__":
    analyze(sys.argv[1])

