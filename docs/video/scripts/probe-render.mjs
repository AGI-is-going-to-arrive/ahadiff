import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const locales = ["zh", "en"];

const probe = (file) => {
  const raw = execFileSync(
    "ffprobe",
    ["-v", "error", "-show_entries", "stream=index,codec_type,codec_name", "-of", "json", file],
    { encoding: "utf8" },
  );
  return JSON.parse(raw);
};

const checkStreams = (file, burned) => {
  if (!fs.existsSync(file)) {
    throw new Error(`Missing render output: ${file}`);
  }
  const streams = probe(file).streams ?? [];
  const video = streams.filter((stream) => stream.codec_type === "video");
  const audio = streams.filter((stream) => stream.codec_type === "audio");
  const subtitles = streams.filter((stream) => stream.codec_type === "subtitle");
  if (video.length !== 1) {
    throw new Error(`${path.basename(file)} expected one video stream, found ${video.length}`);
  }
  if (audio.length !== 1) {
    throw new Error(`${path.basename(file)} expected one audio stream, found ${audio.length}`);
  }
  if (burned && subtitles.length !== 0) {
    throw new Error(`${path.basename(file)} should not contain a separate subtitle stream.`);
  }
  return streams;
};

const pixelDiff = (clean, burned) => {
  const diffLog = execFileSync(
    "ffmpeg",
    [
      "-hide_banner",
      "-ss",
      "00:00:12",
      "-i",
      clean,
      "-ss",
      "00:00:12",
      "-i",
      burned,
      "-filter_complex",
      "[0:v]crop=iw:ih*0.32:0:ih*0.68,format=gray[a];[1:v]crop=iw:ih*0.32:0:ih*0.68,format=gray[b];[a][b]blend=all_mode=difference,signalstats,metadata=print:file=-",
      "-frames:v",
      "1",
      "-f",
      "null",
      "-",
    ],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const match = diffLog.match(/lavfi\.signalstats\.YAVG=([0-9.]+)/);
  const yavg = match ? Number(match[1]) : 0;
  if (!Number.isFinite(yavg) || yavg <= 0.1) {
    throw new Error(`Subtitle burn pixel-diff check was too low: ${yavg}`);
  }
  return yavg;
};

const result = {};
for (const locale of locales) {
  const clean = path.join(root, "output", `ahadiff-tutorial.${locale}.clean.mp4`);
  const burned = path.join(root, "output", `ahadiff-tutorial.${locale}.burned-subtitles.mp4`);
  result[locale] = {
    clean: checkStreams(clean, false),
    burned: checkStreams(burned, true),
    subtitlePixelDiffYavg: pixelDiff(clean, burned),
  };
}

console.log(JSON.stringify(result, null, 2));
