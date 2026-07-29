import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette, visualTheme} from "../theme";
import {SPRING_SETTLE} from "../anim/springs";
import {storyboard} from "../data/storyboard";

export const BrandBug: React.FC<{kicker: string}> = ({kicker}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - 2, fps, config: SPRING_SETTLE, durationInFrames: 36});

  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        top: 48,
        display: "flex",
        alignItems: "center",
        gap: 16,
        fontFamily: fontStack,
        color: palette.white,
        fontWeight: 800,
        opacity: s,
        transform: `translateX(${(1 - s) * -30}px)`,
      }}
    >
      <div
        style={{
          background: visualTheme.brandSurface,
          padding: "12px 18px",
          border: `3px solid ${palette.white}`,
          boxShadow: `8px 8px 0 ${palette.ink}`,
          fontSize: 30,
          lineHeight: 1,
        }}
      >
        {storyboard.brand}
      </div>
      <div
        style={{
          padding: "10px 18px",
          background: "rgba(0,0,0,0.42)",
          border: "2px solid rgba(255,255,255,0.68)",
          fontSize: 26,
        }}
      >
        {kicker}
      </div>
    </div>
  );
};

export const ChapterBadge: React.FC<{chapter: string}> = ({chapter}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - 4, fps, config: SPRING_SETTLE, durationInFrames: 36});

  return (
    <div
      style={{
        position: "absolute",
        right: 70,
        top: 46,
        fontFamily: fontStack,
        color: palette.white,
        fontSize: 66,
        fontWeight: 950,
        lineHeight: 1,
        WebkitTextStroke: `3px ${visualTheme.brandSurface}`,
        textShadow: `6px 6px 0 ${palette.ink}`,
        opacity: s,
        transform: `scale(${0.7 + s * 0.3})`,
        transformOrigin: "right top",
      }}
    >
      {chapter}
    </div>
  );
};
