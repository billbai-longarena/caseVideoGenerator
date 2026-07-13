import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {palette} from "../theme";

export const ProgressRail: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const progress = interpolate(frame, [0, durationInFrames - 1], [0, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: 12,
        background: "rgba(255,255,255,0.2)",
      }}
    >
      <div
        style={{
          width: `${progress}%`,
          height: "100%",
          background: palette.red,
        }}
      />
    </div>
  );
};
