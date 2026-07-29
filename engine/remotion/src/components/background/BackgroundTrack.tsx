import React from "react";
import {AbsoluteFill, interpolate, staticFile, useCurrentFrame, useVideoConfig, Video} from "remotion";
import {clamp, palette} from "../../theme";
import {resolvedBackgroundCues} from "../../timing/timeline";
import {BackgroundTransitionOverlay, backgroundTransform, nextBackgroundStyle} from "./transitions";

const cues = resolvedBackgroundCues();

const backgroundLayerStyle = (image: string): React.CSSProperties => ({
  position: "absolute",
  inset: 0,
  backgroundImage: `url("${staticFile(image)}")`,
  backgroundPosition: "center",
  backgroundRepeat: "no-repeat",
  backgroundSize: "cover",
  willChange: "transform, opacity",
});

const BackgroundMedia: React.FC<{
  image?: string;
  video?: string;
  style: React.CSSProperties;
}> = ({image, video, style}) => {
  if (video) {
    return (
      <Video
        src={staticFile(video)}
        muted
        loop
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          willChange: "transform, opacity",
          ...style,
        }}
      />
    );
  }
  if (!image) {
    throw new Error("Background cue must define image or video");
  }
  return <div style={{...backgroundLayerStyle(image), ...style}} />;
};

export const BackgroundTrack: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  if (cues.length === 0) {
    return <AbsoluteFill style={{backgroundColor: palette.ink}} />;
  }

  let currentIndex = 0;
  for (let index = 0; index < cues.length; index += 1) {
    if (frame >= cues[index].startFrame) {
      currentIndex = index;
    }
  }

  const currentCue = cues[currentIndex];
  const nextCue = cues[currentIndex + 1];
  const from = currentCue.startFrame;
  const to = nextCue ? nextCue.startFrame : durationInFrames;
  const cueDuration = Math.max(1, to - from);
  const localFrame = frame - from;
  const transitionFrames = clamp(Math.round(cueDuration * 0.22), 26, 42);
  const transitionStart = Math.max(from, to - transitionFrames);
  const nextProgress = nextCue
    ? interpolate(frame, [transitionStart, to], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;
  const currentFade = nextCue
    ? interpolate(frame, [transitionStart, to], [1, currentCue.transition === "push" ? 0.65 : 0.92], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;
  const nextLocalFrame = nextCue ? Math.max(0, frame - nextCue.startFrame) : 0;
  const nextDuration = nextCue
    ? Math.max(
        1,
        (cues[currentIndex + 2] ? cues[currentIndex + 2].startFrame : durationInFrames) -
          nextCue.startFrame,
      )
    : 1;
  const currentExtraX =
    currentCue.transition === "push" && nextProgress > 0
      ? interpolate(nextProgress, [0, 1], [0, -80])
      : 0;
  const nextExtraX =
    currentCue.transition === "push" && nextProgress > 0
      ? interpolate(nextProgress, [0, 1], [90, 0])
      : 0;
  const nextEnterScale = interpolate(nextProgress, [0, 1], [1.035, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{backgroundColor: palette.white, overflow: "hidden"}}>
      <BackgroundMedia
        image={currentCue.image}
        video={currentCue.video}
        style={{
          opacity: currentFade,
          transform: backgroundTransform(currentCue.motion, localFrame, cueDuration, currentExtraX),
          filter: "saturate(1.1) contrast(1.05)",
        }}
      />
      {nextCue ? (
        <BackgroundMedia
          image={nextCue.image}
          video={nextCue.video}
          style={{
            transform: `${backgroundTransform(nextCue.motion, nextLocalFrame, nextDuration, nextExtraX)} scale(${nextEnterScale})`,
            ...nextBackgroundStyle(currentCue.transition, nextProgress),
          }}
        />
      ) : null}
      <BackgroundTransitionOverlay transition={currentCue.transition} progress={nextProgress} />
      {(currentCue.video || nextCue?.video) ? (
        <div
          style={{
            position: "absolute",
            right: 48,
            bottom: 188,
            padding: "7px 12px",
            border: "1px solid rgba(255,255,255,0.72)",
            backgroundColor: "rgba(4,16,32,0.62)",
            color: "rgba(255,255,255,0.92)",
            fontFamily: '"Noto Sans SC", "Microsoft YaHei", sans-serif',
            fontSize: 19,
            fontWeight: 700,
            letterSpacing: 1,
            zIndex: 8,
          }}
        >
          工业场景示意
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
