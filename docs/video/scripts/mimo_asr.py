from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

import httpx


def _transcribe(api_key: str, base_url: str, model: str, audio_path: Path, language: str) -> str:
    prompt = {
        "zh": "请只输出这段音频的中文逐字转写，不要解释。",
        "en": "Output only the English transcript of this audio. Do not explain.",
    }[language]
    data = "data:audio/wav;base64," + base64.b64encode(audio_path.read_bytes()).decode("ascii")
    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_audio", "input_audio": {"data": data}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_completion_tokens": 2048,
        },
        timeout=180,
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload["choices"][0]["message"]["content"]).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe local audio via MiMo chat audio input.")
    parser.add_argument("audio", nargs="+", help="Audio files to transcribe.")
    parser.add_argument("--out", required=True, help="Combined transcript output.")
    parser.add_argument("--raw-json", required=True, help="Per-file transcript metadata output.")
    parser.add_argument("--model", default="mimo-v2.5")
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    parser.add_argument("--api-key-env", default="MIMO_API_KEY")
    parser.add_argument("--base-url-env", default="MIMO_BASE_URL")
    args = parser.parse_args()

    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise SystemExit(f"{args.api_key_env} is not set.")
    base_url = os.getenv(args.base_url_env)
    if not base_url:
        raise SystemExit(f"{args.base_url_env} is not set.")

    records = []
    for item in args.audio:
        path = Path(item)
        print(f"Transcribing {path}", flush=True)
        text = _transcribe(api_key, base_url, args.model, path, args.language)
        records.append({"file": str(path), "language": args.language, "model": args.model, "text": text})

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n\n".join(record["text"] for record in records) + "\n", encoding="utf-8")
    raw_path = Path(args.raw_json)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Wrote {raw_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
