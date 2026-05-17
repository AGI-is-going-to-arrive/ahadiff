import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const targets = [
  path.join(repo, "docs", "video"),
  path.join(repo, "docs", "USER_GUIDE.zh.html"),
  path.join(repo, "docs", "VALIDATION_AUDIT.zh.md"),
];
const skipDirs = new Set(["node_modules", ".git", ".next", ".remotion"]);
const skipExts = new Set([".mp4", ".wav", ".mp3", ".png", ".jpg", ".jpeg", ".webp"]);
const patterns = [
  { name: "real token-plan key", regex: /tp-[A-Za-z0-9]{20,}/ },
  { name: "OpenAI-style key", regex: /sk-[A-Za-z0-9_-]{20,}/ },
  { name: "local absolute path", regex: /(?:\/Users\/|\/private\/var\/|\/var\/folders\/|\/tmp\/|[A-Za-z]:\\Users\\)/ },
  { name: "localhost port", regex: /(?:localhost|127\.0\.0\.1|\[::1\]):\d{2,5}/i },
];

const files = [];
const collect = (target) => {
  const stat = fs.statSync(target);
  if (stat.isFile()) {
    files.push(target);
    return;
  }
  for (const entry of fs.readdirSync(target, { withFileTypes: true })) {
    if (skipDirs.has(entry.name)) {
      continue;
    }
    const full = path.join(target, entry.name);
    if (entry.isDirectory()) {
      collect(full);
    } else if (!skipExts.has(path.extname(entry.name).toLowerCase())) {
      files.push(full);
    }
  }
};

for (const target of targets) {
  collect(target);
}

const findings = [];
for (const file of files) {
  const text = fs.readFileSync(file, "utf8");
  for (const pattern of patterns) {
    const match = pattern.regex.exec(text);
    if (match) {
      findings.push({ file: path.relative(repo, file), pattern: pattern.name, match: match[0] });
    }
  }
}

if (findings.length > 0) {
  console.error(JSON.stringify(findings, null, 2));
  process.exit(1);
}

console.log(`Sensitive scan passed for ${files.length} text files.`);
