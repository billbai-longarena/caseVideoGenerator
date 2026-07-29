import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {chipColors, chipTextColor, fontStack, palette} from "../theme";
import {SPRING_POP, idleFloat} from "../anim/springs";
import type {KeywordCue} from "../data/types";

const ENTRANCES = [
  {x: 0, y: 50},
  {x: -50, y: 0},
  {x: 50, y: 0},
];

export const KeywordPop: React.FC<{
  cue: KeywordCue;
  startFrame: number;
  index: number;
  large?: boolean;
}> = ({cue, startFrame, index, large = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const directed = cue.display !== undefined;
  const enterMode = cue.enter ?? "scale";
  const enterFrames = cue.enterFrames ?? 40;
  const springProgress = spring({
    frame: frame - startFrame,
    fps,
    config: SPRING_POP,
    durationInFrames: enterFrames,
  });
  const linearProgress = interpolate(frame, [startFrame, startFrame + enterFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const progress = enterMode === "cut" ? (frame >= startFrame ? 1 : 0) : enterMode === "fade" ? linearProgress : springProgress;
  const legacyEntrance = ENTRANCES[index % ENTRANCES.length];
  const entrance = directed
    ? enterMode === "rise"
      ? {x: 0, y: 50}
      : enterMode === "slide-left"
        ? {x: -50, y: 0}
        : enterMode === "slide-right"
          ? {x: 50, y: 0}
          : {x: 0, y: 0}
    : legacyEntrance;
  const restRotation = cue.rotation ?? (index % 2 === 0 ? -2 : 2);
  const rotation = directed ? restRotation : restRotation + (1 - progress) * (index % 2 === 0 ? -5 : 5);
  const background = cue.background ?? chipColors[index % chipColors.length];
  const textColor = cue.color ?? chipTextColor(background);
  const shouldFloat = cue.float ?? !directed;
  const float = shouldFloat ? idleFloat(frame, startFrame + 20) : 0;
  const surface = cue.surface ?? "chip";
  const scale = directed && enterMode !== "scale" ? 1 : progress;

  if (cue.display === false || frame < startFrame - 2) return null;

  return (
    <div
      style={{
        opacity: Math.min(1, progress * 1.4),
        transform: `translate(${(1 - progress) * entrance.x}px, ${(1 - progress) * entrance.y + float}px) scale(${scale}) rotate(${rotation}deg)`,
        background: surface === "chip" ? background : "transparent",
        color: textColor,
        border: surface === "chip" ? `4px solid ${palette.white}` : "none",
        boxShadow: surface === "chip" ? `7px 7px 0 ${palette.ink}` : "none",
        padding: large ? "15px 28px" : "13px 24px 15px",
        fontFamily: fontStack,
        fontSize: cue.fontSize ?? (large ? 42 : 34),
        fontWeight: 900,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {cue.text}
    </div>
  );
};
