# AhaDiff Remotion Tutorial Video

This directory contains the standalone Remotion project for the AhaDiff
introduction and tutorial video. It is kept outside `viewer/`, so the
production WebUI bundle is not affected by video tooling.

## What Is Committed

- `content/story.json` — 9 tutorial scenes with Chinese and English narration
  and UI copy.
- `content/voice-instructions.{zh,en}.txt` — TTS voice style prompts.
- `public/screenshots/{zh,en}/` — WebUI screenshots used by the Remotion render.
- `public/captions/ahadiff-tutorial.{zh,en}.json` — captions used by the video.
- `output/script/ahadiff-narration.{zh,en}.txt` — full narration scripts.
- `output/asr/ahadiff-asr.{zh,en}.{txt,raw.json}` — ASR validation outputs.
- `output/subtitles/ahadiff-tutorial.{zh,en}.{srt,vtt,json}` — subtitle source.
- `output/ahadiff-tutorial.{zh,en}.burned-subtitles.mp4` — final viewer-facing
  MP4 files (the only video binaries shipped to users).

## What Is Generated Locally (Not Committed)

These artifacts are produced by the video build and are intentionally gitignored
to keep the repository slim. Developers who want to rebuild or modify the video
must regenerate them locally:

- `public/audio/ahadiff-narration.{zh,en}.wav` — final narration audio (run the
  `mimo_tts.py` step described under **Rebuild** below).
- `output/ahadiff-tutorial.{zh,en}.clean.mp4` — Remotion render without burned
  subtitles (produced by `pnpm run render`; the burn step turns it into the
  committed `*.burned-subtitles.mp4`).
- `node_modules/`, `.remotion/`, raw TTS WAVs, per-scene TTS WAVs, concat lists,
  logs, and macOS metadata.

If a build script complains about a missing `*.clean.mp4` or
`public/audio/*.wav`, run the **Rebuild** steps below to regenerate the
intermediates.

## Current Outputs

- Chinese final MP4:
  `output/ahadiff-tutorial.zh.burned-subtitles.mp4`
  - Size: `37,002,001` bytes
  - Duration: `403.000000s`
  - Streams: H.264 3840x2160 video + AAC 48 kHz stereo audio
- English final MP4:
  `output/ahadiff-tutorial.en.burned-subtitles.mp4`
  - Size: `38,710,711` bytes
  - Duration: `395.000000s`
  - Streams: H.264 3840x2160 video + AAC 48 kHz stereo audio

Both final MP4 files have burned-in subtitles and no separate subtitle stream.

## Rebuild

```bash
pnpm install --frozen-lockfile
pnpm run prepare
pnpm run render
pnpm run burn
pnpm run probe
pnpm run scan
```

TTS and ASR calls require local environment variables and are intentionally
separate from the normal build:

```bash
export MIMO_BASE_URL="..."
export MIMO_API_KEY="..."

uv run --with httpx python scripts/mimo_tts.py \
  --story content/story.json --locale zh \
  --instructions content/voice-instructions.zh.txt \
  --model mimo-v2.5-tts --voice "冰糖" \
  --out public/audio/ahadiff-narration.zh.wav

uv run --with httpx python scripts/mimo_tts.py \
  --story content/story.json --locale en \
  --instructions content/voice-instructions.en.txt \
  --model mimo-v2.5-tts --voice "冰糖" \
  --out public/audio/ahadiff-narration.en.wav

uv run --with httpx python scripts/mimo_asr.py \
  public/audio/ahadiff-narration.zh.wav \
  --language zh \
  --out output/asr/ahadiff-asr.zh.txt \
  --raw-json output/asr/ahadiff-asr.zh.raw.json

uv run --with httpx python scripts/mimo_asr.py \
  public/audio/ahadiff-narration.en.wav \
  --language en \
  --out output/asr/ahadiff-asr.en.txt \
  --raw-json output/asr/ahadiff-asr.en.raw.json
```

## Validation Notes

Commands run on 2026-05-18:

```bash
pnpm run typecheck
pnpm run probe
pnpm run scan
node scripts/check-asr-similarity.mjs
```

Results:

- `pnpm run typecheck` passed.
- `pnpm run probe` passed. Subtitle pixel-diff checks returned `5.74087` for
  Chinese and `8.34139` for English, confirming the burned MP4s differ from
  the clean renders in the subtitle area.
- `pnpm run scan` passed across 39 text files. It found no real API key, local
  absolute path, temporary path, or localhost port in the scanned text assets.
- `node scripts/check-asr-similarity.mjs` failed on the Chinese transcript:
  `dice=0.126`, `lengthRatio=0.027`. The Chinese ASR output is a refusal-like
  note instead of a transcript. The English transcript comparison, checked with
  the same script logic, was `dice=0.923`, `lengthRatio=0.836`.

The ASR failure is a validation limitation of the current generated transcript,
not proof that the MP4 is invalid. The MP4 stream/probe checks above remain the
current evidence for the rendered files.
