import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const fps = 30;
const storyPath = path.join(root, "content", "story.json");
const story = JSON.parse(fs.readFileSync(storyPath, "utf8"));

const locales = {
  zh: {
    audioRel: "audio/ahadiff-narration.zh.wav",
    narrationKey: "narrationZh",
    subtitleKey: "subtitleZh",
    title: story.titleZh,
  },
  en: {
    audioRel: "audio/ahadiff-narration.en.wav",
    narrationKey: "narrationEn",
    subtitleKey: "subtitleEn",
    title: story.titleEn,
  },
};

const ensureDir = (dir) => fs.mkdirSync(dir, { recursive: true });

const formatSrtTime = (ms) => {
  const total = Math.max(0, Math.round(ms));
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  const millis = total % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")},${String(millis).padStart(3, "0")}`;
};

const formatVttTime = (ms) => formatSrtTime(ms).replace(",", ".");

const audioDurationSeconds = (audioPath) => {
  if (!fs.existsSync(audioPath)) {
    return null;
  }
  const raw = execFileSync(
    "ffprobe",
    [
      "-v",
      "error",
      "-show_entries",
      "format=duration",
      "-of",
      "default=noprint_wrappers=1:nokey=1",
      audioPath,
    ],
    { encoding: "utf8" },
  ).trim();
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
};

const estimateSceneSeconds = (text, locale) => {
  if (locale === "zh") {
    return Math.max(10, Array.from(text).length / 4.8 + 2);
  }
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(10, words / 2.35 + 2.5);
};

const buildLocale = (locale, config) => {
  const audioPath = path.join(root, "public", config.audioRel);
  const narration = story.scenes.map((scene) => scene[config.narrationKey]).join("\n\n");

  ensureDir(path.join(root, "output", "script"));
  fs.writeFileSync(path.join(root, "output", "script", `ahadiff-narration.${locale}.txt`), `${narration}\n`, "utf8");

  const estimatedDurations = story.scenes.map((scene) => estimateSceneSeconds(scene[config.narrationKey], locale));
  const estimatedTotal = estimatedDurations.reduce((sum, value) => sum + value, 0);
  const probedDuration = audioDurationSeconds(audioPath);
  const totalSeconds = probedDuration ? Math.ceil(probedDuration + 0.8) : Math.ceil(estimatedTotal);
  const scale = totalSeconds / estimatedTotal;

  let cursorMs = 0;
  const captions = [];
  const scenes = story.scenes.map((scene, index) => {
    const isLast = index === story.scenes.length - 1;
    const durationMs = isLast
      ? totalSeconds * 1000 - cursorMs
      : Math.round(estimatedDurations[index] * scale * 1000);
    const startMs = cursorMs;
    const endMs = Math.max(startMs + 1000, startMs + durationMs);
    cursorMs = endMs;
    captions.push({
      text: scene[config.subtitleKey],
      startMs,
      endMs,
      timestampMs: null,
      confidence: null,
    });
    return {
      id: scene.id,
      from: Math.round((startMs / 1000) * fps),
      durationInFrames: Math.max(1, Math.round(((endMs - startMs) / 1000) * fps)),
      startMs,
      endMs,
    };
  });

  const durationInFrames = Math.max(
    Math.ceil(totalSeconds * fps),
    scenes.at(-1).from + scenes.at(-1).durationInFrames,
  );

  const srt = captions
    .map((caption, index) => {
      return [
        String(index + 1),
        `${formatSrtTime(caption.startMs)} --> ${formatSrtTime(caption.endMs)}`,
        caption.text,
      ].join("\n");
    })
    .join("\n\n");

  const vtt = `WEBVTT\n\n${captions
    .map((caption) => {
      return [
        `${formatVttTime(caption.startMs)} --> ${formatVttTime(caption.endMs)}`,
        caption.text,
      ].join("\n");
    })
    .join("\n\n")}\n`;

  ensureDir(path.join(root, "output", "subtitles"));
  ensureDir(path.join(root, "public", "captions"));
  fs.writeFileSync(path.join(root, "output", "subtitles", `ahadiff-tutorial.${locale}.srt`), `${srt}\n`, "utf8");
  fs.writeFileSync(path.join(root, "output", "subtitles", `ahadiff-tutorial.${locale}.vtt`), vtt, "utf8");
  fs.writeFileSync(
    path.join(root, "output", "subtitles", `ahadiff-tutorial.${locale}.json`),
    `${JSON.stringify(captions, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(root, "public", "captions", `ahadiff-tutorial.${locale}.json`),
    `${JSON.stringify(captions, null, 2)}\n`,
    "utf8",
  );

  return {
    audioSrc: config.audioRel,
    hasAudio: fs.existsSync(audioPath),
    durationInFrames,
    totalSeconds,
    sceneTimings: scenes,
    narrationChars: Array.from(narration).length,
  };
};

const media = Object.fromEntries(Object.entries(locales).map(([locale, config]) => [locale, buildLocale(locale, config)]));

ensureDir(path.join(root, "src", "generated"));
fs.writeFileSync(
  path.join(root, "src", "generated", "timeline.ts"),
  [
    "export type Locale = \"zh\" | \"en\";",
    "export type SceneTiming = {",
    "  id: string;",
    "  from: number;",
    "  durationInFrames: number;",
    "  startMs: number;",
    "  endMs: number;",
    "};",
    "export type LocaleMedia = {",
    "  audioSrc: string;",
    "  hasAudio: boolean;",
    "  durationInFrames: number;",
    "  totalSeconds: number;",
    "  sceneTimings: SceneTiming[];",
    "  narrationChars: number;",
    "};",
    `export const FPS = ${fps};`,
    `export const MEDIA = ${JSON.stringify(media, null, 2)} satisfies Record<Locale, LocaleMedia>;`,
    "",
  ].join("\n"),
  "utf8",
);

console.log(JSON.stringify(media, null, 2));
