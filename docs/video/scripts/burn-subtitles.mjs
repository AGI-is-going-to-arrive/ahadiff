import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const locales = ["zh", "en"];

const style = [
  "FontName=Arial Unicode MS",
  "FontSize=13",
  "PrimaryColour=&H00FFFFFF",
  "OutlineColour=&HCC1E1B18",
  "BackColour=&H00000000",
  "BorderStyle=1",
  "Outline=1.2",
  "Shadow=0.5",
  "MarginV=36",
  "MarginL=110",
  "MarginR=110",
  "Alignment=2",
].join(",");

for (const locale of locales) {
  const input = path.join(root, "output", `ahadiff-tutorial.${locale}.clean.mp4`);
  const srt = path.join(root, "output", "subtitles", `ahadiff-tutorial.${locale}.srt`);
  const output = path.join(root, "output", `ahadiff-tutorial.${locale}.burned-subtitles.mp4`);

  for (const file of [input, srt]) {
    if (!fs.existsSync(file)) {
      throw new Error(`Missing required file: ${file}`);
    }
  }

  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-i",
      input,
      "-vf",
      `subtitles=${srt}:force_style='${style}'`,
      "-c:v",
      "libx264",
      "-crf",
      "23",
      "-preset",
      "medium",
      "-c:a",
      "copy",
      output,
    ],
    { stdio: "inherit" },
  );

  console.log(`Wrote ${output}`);
}
