import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const locales = ["zh", "en"];

const normalize = (value) =>
  Array.from(value)
    .filter((char) => /[\p{Script=Han}A-Za-z0-9]/u.test(char))
    .join("")
    .toLowerCase();

const compare = (locale) => {
  const expectedPath = path.join(root, "output", "script", `ahadiff-narration.${locale}.txt`);
  const actualPath = path.join(root, "output", "asr", `ahadiff-asr.${locale}.txt`);
  if (!fs.existsSync(expectedPath) || !fs.existsSync(actualPath)) {
    throw new Error(`Missing ASR comparison input for ${locale}.`);
  }

  const expected = normalize(fs.readFileSync(expectedPath, "utf8"));
  const actual = normalize(fs.readFileSync(actualPath, "utf8"));
  const expectedSet = new Set(Array.from(expected));
  const actualSet = new Set(Array.from(actual));
  let overlap = 0;
  for (const char of expectedSet) {
    if (actualSet.has(char)) {
      overlap += 1;
    }
  }
  const dice = (2 * overlap) / Math.max(1, expectedSet.size + actualSet.size);
  const lengthRatio = actual.length / Math.max(1, expected.length);

  if (dice < 0.78 || lengthRatio < 0.75 || lengthRatio > 1.35) {
    throw new Error(
      `ASR transcript drift is too high for ${locale}: dice=${dice.toFixed(3)}, lengthRatio=${lengthRatio.toFixed(3)}`,
    );
  }

  return { locale, dice, lengthRatio, expectedChars: expected.length, actualChars: actual.length };
};

console.log(JSON.stringify(locales.map(compare), null, 2));
