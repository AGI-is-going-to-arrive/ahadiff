import { Audio } from "@remotion/media";
import { AbsoluteFill, Img, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import story from "../content/story.json";
import { MEDIA, type Locale } from "./generated/timeline";

type StoryScene = (typeof story.scenes)[number];

const palette = {
  paper: "#f7f1e8",
  ink: "#211d19",
  muted: "#6d6258",
  line: "#d8cdbc",
  rust: "#b84d34",
  green: "#2f6f50",
  blue: "#385a73",
  dark: "#24211d",
};

const mono: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace",
};

const screenshotMap: Record<string, Record<Locale, string>> = {
  welcome: { zh: "screenshots/zh/zh-welcome.png", en: "screenshots/en/en-welcome.png" },
  settings: { zh: "screenshots/zh/zh-settings.png", en: "screenshots/en/en-settings.png" },
  diff: { zh: "screenshots/zh/zh-diff.png", en: "screenshots/en/en-diff.png" },
  lesson: { zh: "screenshots/zh/zh-lesson.png", en: "screenshots/en/en-lesson.png" },
  quiz: { zh: "screenshots/zh/zh-quiz.png", en: "screenshots/en/en-quiz.png" },
  review: { zh: "screenshots/zh/zh-review.png", en: "screenshots/en/en-review.png" },
  dashboard: { zh: "screenshots/zh/zh-dashboard.png", en: "screenshots/en/en-dashboard.png" },
  concepts: { zh: "screenshots/zh/zh-concepts.png", en: "screenshots/en/en-concepts.png" },
  guide: { zh: "screenshots/zh/zh-guide.png", en: "screenshots/en/en-guide.png" },
  "guide-full": { zh: "screenshots/zh/zh-guide-full.png", en: "screenshots/en/en-guide-full.png" },
  "lesson-scorelinks": { zh: "screenshots/zh/zh-lesson-scorelinks.png", en: "screenshots/en/en-lesson.png" },
  "rundetail-score": { zh: "screenshots/zh/zh-rundetail-score.png", en: "screenshots/en/en-rundetail-score.png" },
  "rundetail-overview": { zh: "screenshots/zh/zh-rundetail-overview.png", en: "screenshots/en/en-rundetail-overview.png" },
  "concepts-graph": { zh: "screenshots/zh/zh-concepts-graph.png", en: "screenshots/en/en-concepts-graph.png" },
};

const SceneCard = ({ scene, index, locale }: { scene: StoryScene; index: number; locale: Locale }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const opacity = interpolate(frame, [0, 0.5 * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const screenshotScale = interpolate(frame, [0.2 * fps, 0.8 * fps], [1.02, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const accent = index % 3 === 0 ? palette.rust : index % 3 === 1 ? palette.green : palette.blue;
  const title = locale === "zh" ? scene.titleZh : scene.titleEn;
  const kicker = locale === "zh" ? scene.kickerZh : scene.kickerEn;
  const brandLabel = locale === "zh" ? "知返教程" : "AhaDiff Tutorial";
  const screenshotKey = (scene as StoryScene & { screenshot?: string }).screenshot;
  const screenshotSrc = screenshotKey ? screenshotMap[screenshotKey]?.[locale] : undefined;
  const hasCommands = scene.commands.length > 0;

  return (
    <AbsoluteFill style={{ background: palette.paper, opacity }}>
      {/* Top bar */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 120,
          background: palette.dark,
          display: "flex",
          alignItems: "center",
          padding: "0 144px",
          justifyContent: "space-between",
          zIndex: 10,
        }}
      >
        <div style={{ ...mono, fontSize: 39, color: "#fff8ee", letterSpacing: 1.5 }}>
          {brandLabel} · {String(index + 1).padStart(2, "0")}/{story.scenes.length}
        </div>
        <div style={{ ...mono, fontSize: 36, color: accent }}>{kicker}</div>
      </div>

      {/* Full-screen screenshot */}
      {screenshotSrc ? (
        <div
          style={{
            position: "absolute",
            top: 120,
            left: 0,
            right: 0,
            bottom: 0,
            overflow: "hidden",
          }}
        >
          <Img
            src={staticFile(screenshotSrc)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: "top left",
              transform: `scale(${screenshotScale})`,
              transformOrigin: "top left",
            }}
          />
        </div>
      ) : null}

      {/* Title overlay card */}
      <div
        style={{
          position: "absolute",
          left: 96,
          bottom: hasCommands ? 108 : 84,
          maxWidth: 1680,
          background: "rgba(247, 241, 232, 0.94)",
          borderRadius: 30,
          padding: "48px 66px",
          boxShadow: "0 24px 96px rgba(33, 29, 25, 0.18)",
          zIndex: 5,
        }}
      >
        <div style={{ fontSize: locale === "zh" ? 84 : 78, fontWeight: 760, lineHeight: 1.15, color: palette.ink }}>
          {title}
        </div>
        {hasCommands ? (
          <div
            style={{
              marginTop: 30,
              background: palette.dark,
              borderRadius: 18,
              padding: "24px 36px",
              color: "#fff8ee",
              ...mono,
              fontSize: 39,
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
            }}
          >
            {scene.commands.join("\n")}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

export const AhaDiffVideo = ({ locale }: { locale: Locale }) => {
  const media = MEDIA[locale];

  return (
    <AbsoluteFill style={{ background: palette.paper }}>
      {media.hasAudio ? <Audio src={staticFile(media.audioSrc)} /> : null}
      {media.sceneTimings.map((timing, index) => {
        const scene = story.scenes.find((item) => item.id === timing.id);
        if (!scene) {
          return null;
        }
        return (
          <Sequence
            key={timing.id}
            from={timing.from}
            durationInFrames={timing.durationInFrames}
            premountFor={30}
          >
            <SceneCard scene={scene} index={index} locale={locale} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
