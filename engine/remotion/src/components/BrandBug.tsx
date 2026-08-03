import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette, visualTheme} from "../theme";
import {SPRING_SETTLE} from "../anim/springs";
import {storyboard} from "../data/storyboard";
import {IS_VERTICAL, VERTICAL_CHROME_TOP} from "../canvas";

export const BrandBug: React.FC<{kicker?: string; immediate?: boolean}> = ({
  kicker,
  immediate = false,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = immediate
    ? 1
    : spring({frame: frame - 2, fps, config: SPRING_SETTLE, durationInFrames: 36});

  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        // Vertical: drop below the platform's top overlay (tabs/back button).
        top: IS_VERTICAL ? VERTICAL_CHROME_TOP : 48,
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
      {kicker ? (
        <div
          style={{
            padding: "10px 18px",
            background: "rgba(0,0,0,0.58)",
            border: "2px solid rgba(255,255,255,0.68)",
            boxShadow: "5px 6px 0 rgba(5,17,31,0.48)",
            fontSize: 26,
          }}
        >
          {kicker}
        </div>
      ) : null}
    </div>
  );
};

export const ChapterBadge: React.FC<{chapter: string}> = ({chapter}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - 4, fps, config: SPRING_SETTLE, durationInFrames: 36});

  // Vertical: the top-right corner sits under platform overlay UI, and
  // chapter words are director-facing labels — keep them off the phone screen.
  if (IS_VERTICAL) return null;

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
