export type Locale = "zh" | "en";
export type SceneTiming = {
  id: string;
  from: number;
  durationInFrames: number;
  startMs: number;
  endMs: number;
};
export type LocaleMedia = {
  audioSrc: string;
  hasAudio: boolean;
  durationInFrames: number;
  totalSeconds: number;
  sceneTimings: SceneTiming[];
  narrationChars: number;
};
export const FPS = 30;
export const MEDIA = {
  "zh": {
    "audioSrc": "audio/ahadiff-narration.zh.wav",
    "hasAudio": true,
    "durationInFrames": 12090,
    "totalSeconds": 403,
    "sceneTimings": [
      {
        "id": "problem",
        "from": 0,
        "durationInFrames": 978,
        "startMs": 0,
        "endMs": 32586
      },
      {
        "id": "cli-guide",
        "from": 978,
        "durationInFrames": 2112,
        "startMs": 32586,
        "endMs": 102970
      },
      {
        "id": "diff-claims",
        "from": 3089,
        "durationInFrames": 1077,
        "startMs": 102970,
        "endMs": 138859
      },
      {
        "id": "lesson-read",
        "from": 4166,
        "durationInFrames": 906,
        "startMs": 138859,
        "endMs": 169060
      },
      {
        "id": "quiz-review",
        "from": 5072,
        "durationInFrames": 1121,
        "startMs": 169060,
        "endMs": 206417
      },
      {
        "id": "eval-detail",
        "from": 6193,
        "durationInFrames": 1280,
        "startMs": 206417,
        "endMs": 249095
      },
      {
        "id": "concepts-graph",
        "from": 7473,
        "durationInFrames": 1412,
        "startMs": 249095,
        "endMs": 296176
      },
      {
        "id": "dashboard-settings",
        "from": 8885,
        "durationInFrames": 1820,
        "startMs": 296176,
        "endMs": 356835
      },
      {
        "id": "wrap",
        "from": 10705,
        "durationInFrames": 1385,
        "startMs": 356835,
        "endMs": 403000
      }
    ],
    "narrationChars": 2126
  },
  "en": {
    "audioSrc": "audio/ahadiff-narration.en.wav",
    "hasAudio": true,
    "durationInFrames": 11850,
    "totalSeconds": 395,
    "sceneTimings": [
      {
        "id": "problem",
        "from": 0,
        "durationInFrames": 985,
        "startMs": 0,
        "endMs": 32835
      },
      {
        "id": "cli-guide",
        "from": 985,
        "durationInFrames": 1639,
        "startMs": 32835,
        "endMs": 87458
      },
      {
        "id": "diff-claims",
        "from": 2624,
        "durationInFrames": 1133,
        "startMs": 87458,
        "endMs": 125226
      },
      {
        "id": "lesson-read",
        "from": 3757,
        "durationInFrames": 960,
        "startMs": 125226,
        "endMs": 157239
      },
      {
        "id": "quiz-review",
        "from": 4717,
        "durationInFrames": 1392,
        "startMs": 157239,
        "endMs": 203640
      },
      {
        "id": "eval-detail",
        "from": 6109,
        "durationInFrames": 1454,
        "startMs": 203640,
        "endMs": 252096
      },
      {
        "id": "concepts-graph",
        "from": 7563,
        "durationInFrames": 1380,
        "startMs": 252096,
        "endMs": 298086
      },
      {
        "id": "dashboard-settings",
        "from": 8943,
        "durationInFrames": 1565,
        "startMs": 298086,
        "endMs": 350242
      },
      {
        "id": "wrap",
        "from": 10507,
        "durationInFrames": 1343,
        "startMs": 350242,
        "endMs": 395000
      }
    ],
    "narrationChars": 5515
  }
} satisfies Record<Locale, LocaleMedia>;
