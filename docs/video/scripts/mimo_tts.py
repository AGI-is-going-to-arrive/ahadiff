from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def _audio_data(message: Any) -> str:
    audio = getattr(message, "audio", None)
    if audio is None and isinstance(message, dict):
        audio = message.get("audio")
    if audio is None:
        raise RuntimeError("TTS response did not include audio data.")
    data = getattr(audio, "data", None)
    if data is None and isinstance(audio, dict):
        data = audio.get("data")
    if not isinstance(data, str) or not data:
        raise RuntimeError("TTS response audio data is empty.")
    return data


def _client(api_key_env: str, base_url_env: str) -> tuple[str, str]:
    api_key = os.getenv(api_key_env) or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(f"{api_key_env} or OPENAI_API_KEY is not set.")
    base_url = os.getenv(base_url_env) or os.getenv("OPENAI_BASE_URL")
    if not base_url:
        raise SystemExit(f"{base_url_env} or OPENAI_BASE_URL is not set.")
    return api_key, base_url.rstrip("/")


def _synthesize(
    client: tuple[str, str],
    *,
    model: str,
    voice: str,
    audio_format: str,
    instructions: str,
    text: str,
    out_path: Path,
    timeout: float,
    retries: int,
) -> None:
    api_key, base_url = client
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": instructions},
                        {"role": "assistant", "content": text},
                    ],
                    "audio": {"format": audio_format, "voice": voice},
                },
                timeout=timeout,
            )
            break
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError("TTS request failed.") from last_error
    response.raise_for_status()
    completion = response.json()
    message = completion["choices"][0]["message"]
    audio_bytes = base64.b64decode(_audio_data(message))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)


def _concat_wav(files: list[Path], out_path: Path) -> None:
    list_path = out_path.parent / "concat-list.txt"
    list_path.write_text(
        "\n".join(f"file '{file.relative_to(out_path.parent).as_posix()}'" for file in files) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path.name, "-c", "copy", out_path.name],
        cwd=out_path.parent,
        check=True,
    )


def _normalize_wav(in_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
            str(out_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate MiMo TTS audio via chat.completions.")
    parser.add_argument("--input", help="Narration text file.")
    parser.add_argument("--story", help="Story JSON file; each scene narration is synthesized separately.")
    parser.add_argument("--instructions", required=True, help="Voice style instructions file.")
    parser.add_argument("--out", required=True, help="Output audio file.")
    parser.add_argument("--scene-dir", default="public/audio/scenes", help="Scene audio output directory.")
    parser.add_argument("--locale", choices=("zh", "en"), default="zh", help="Story narration locale to synthesize.")
    parser.add_argument("--model", default="mimo-v2.5-tts")
    parser.add_argument("--voice", default="冰糖")
    parser.add_argument("--format", default="wav")
    parser.add_argument("--api-key-env", default="MIMO_API_KEY")
    parser.add_argument("--base-url-env", default="MIMO_BASE_URL")
    parser.add_argument("--timeout", type=float, default=360)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--skip-existing", action="store_true", help="Reuse existing scene clips and only rebuild the concat output.")
    args = parser.parse_args()

    if bool(args.input) == bool(args.story):
        raise SystemExit("Use exactly one of --input or --story.")

    client = _client(args.api_key_env, args.base_url_env)
    instructions = _read_text(args.instructions)
    out_path = Path(args.out)
    if args.input:
        raw_path = out_path.with_suffix(f".raw{out_path.suffix}")
        _synthesize(
            client,
            model=args.model,
            voice=args.voice,
            audio_format=args.format,
            instructions=instructions,
            text=_read_text(args.input),
            out_path=raw_path,
            timeout=args.timeout,
            retries=args.retries,
        )
        _normalize_wav(raw_path, out_path)
    else:
        story = json.loads(Path(args.story).read_text(encoding="utf-8"))
        narration_key = {"zh": "narrationZh", "en": "narrationEn"}[args.locale]
        scene_dir = Path(args.scene_dir)
        scene_files: list[Path] = []
        normalized_files: list[Path] = []
        for index, scene in enumerate(story["scenes"], start=1):
            scene_path = scene_dir / f"{index:02d}-{scene['id']}.{args.format}"
            if args.skip_existing and scene_path.exists() and scene_path.stat().st_size > 0:
                print(f"Reusing {scene_path}", flush=True)
            else:
                print(f"Synthesizing {scene_path}", flush=True)
                _synthesize(
                    client,
                    model=args.model,
                    voice=args.voice,
                    audio_format=args.format,
                    instructions=instructions,
                    text=scene[narration_key],
                    out_path=scene_path,
                    timeout=args.timeout,
                    retries=args.retries,
                )
            scene_files.append(scene_path)
            normalized_path = scene_dir / "normalized" / scene_path.name
            print(f"Normalizing {normalized_path}", flush=True)
            _normalize_wav(scene_path, normalized_path)
            normalized_files.append(normalized_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _concat_wav(normalized_files, out_path)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
