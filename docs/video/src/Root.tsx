import { Composition } from "remotion";
import { AhaDiffVideo } from "./AhaDiffVideo";
import { FPS, MEDIA } from "./generated/timeline";

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="AhaDiffTutorialZh"
        component={AhaDiffVideo}
        durationInFrames={MEDIA.zh.durationInFrames}
        fps={FPS}
        width={3840}
        height={2160}
        defaultProps={{ locale: "zh" }}
      />
      <Composition
        id="AhaDiffTutorialEn"
        component={AhaDiffVideo}
        durationInFrames={MEDIA.en.durationInFrames}
        fps={FPS}
        width={3840}
        height={2160}
        defaultProps={{ locale: "en" }}
      />
    </>
  );
};
