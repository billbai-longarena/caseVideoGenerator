import React from "react";
import {AbsoluteFill} from "remotion";
import type {SceneTransition} from "../data/types";
import {fontStack, palette, visualTheme} from "../theme";

export const TransitionWipe: React.FC<{
  progress: number;
  chapter: string;
  variant: SceneTransition;
}> = ({
  progress,
  chapter,
  variant,
}) => {
  if (progress <= 0 || variant === "none") {
    return null;
  }

  if (variant === "chapter-circle") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: progress * 0.68,
          background: "linear-gradient(90deg, rgba(255,212,90,0.92), rgba(11,98,214,0.92))",
          clipPath: `circle(${progress * 92}% at 76% 48%)`,
          mixBlendMode: "normal",
        }}
      >
        <div
          style={{
            position: "absolute",
            right: 140,
            top: 360,
            fontFamily: fontStack,
            fontSize: 128,
            fontWeight: 950,
            color: palette.white,
            WebkitTextStroke: `4px ${palette.ink}`,
            textShadow: `10px 10px 0 ${visualTheme.brandSurface}`,
          }}
        >
          {chapter}
        </div>
      </AbsoluteFill>
    );
  }

  if (variant === "paper-stripes") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: progress * 0.5,
          background:
            "repeating-linear-gradient(-8deg, rgba(11,98,214,0.82) 0, rgba(11,98,214,0.82) 34px, rgba(255,212,90,0.72) 34px, rgba(255,212,90,0.72) 54px)",
          clipPath: `polygon(${100 - progress * 118}% 0, 100% 0, 100% 100%, ${92 - progress * 118}% 100%)`,
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 108,
            bottom: 238,
            fontFamily: fontStack,
            fontSize: 112,
            fontWeight: 950,
            color: palette.white,
            WebkitTextStroke: `4px ${palette.ink}`,
            textShadow: `10px 10px 0 ${palette.red}`,
          }}
        >
          {chapter}
        </div>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        opacity: progress * 0.72,
        background: visualTheme.brandSurface,
        clipPath: `polygon(0 0, ${24 + progress * 82}% 0, ${8 + progress * 82}% 100%, 0 100%)`,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 90,
          top: 390,
          fontFamily: fontStack,
          fontSize: 120,
          fontWeight: 950,
          color: palette.white,
          WebkitTextStroke: `4px ${palette.ink}`,
          textShadow: `10px 10px 0 ${palette.ink}`,
        }}
      >
        {chapter}
      </div>
    </AbsoluteFill>
  );
};
