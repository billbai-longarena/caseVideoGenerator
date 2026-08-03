import React from "react";
import {Img, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_SETTLE} from "../anim/springs";
import {storyboard} from "../data/storyboard";
import {IS_VERTICAL, VERTICAL_CHROME_TOP, VERTICAL_MARGIN_X} from "../canvas";

// Persistent co-brand bug for joint-partner videos (declared via
// storyboard_plan.json top-level "coBrand"). Pins both partner logos to the
// top-right corner for the whole video, above every layer including the
// cover. Omit coBrand for single-brand videos and nothing renders.
export const CoBrandBug: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const coBrand = storyboard.coBrand;
  if (!coBrand || coBrand.logos.length !== 2) {
    return null;
  }
  const s = spring({frame: frame - 2, fps, config: SPRING_SETTLE, durationInFrames: 36});

  // Vertical: the top-right corner sits below the platform's top overlay UI,
  // aligned with the persistent brand chip row on the opposite side.
  const logoHeight = IS_VERTICAL ? 56 : 44;

  return (
    <div
      style={{
        position: "absolute",
        right: IS_VERTICAL ? VERTICAL_MARGIN_X : 70,
        top: IS_VERTICAL ? VERTICAL_CHROME_TOP : 48,
        display: "flex",
        alignItems: "center",
        gap: IS_VERTICAL ? 14 : 12,
        padding: IS_VERTICAL ? "14px 22px" : "10px 18px",
        background: "rgba(255,255,255,0.92)",
        border: `2px solid ${palette.ink}`,
        borderRadius: 14,
        boxShadow: `4px 4px 0 rgba(0,0,0,0.35)`,
        opacity: s,
        transform: `translateX(${(1 - s) * 30}px)`,
      }}
    >
      <Img
        src={staticFile(coBrand.logos[0].src)}
        alt={coBrand.logos[0].alt}
        style={{height: logoHeight, objectFit: "contain"}}
      />
      <div
        style={{
          fontFamily: fontStack,
          color: palette.ink,
          fontSize: IS_VERTICAL ? 34 : 26,
          fontWeight: 800,
          lineHeight: 1,
        }}
      >
        {coBrand.separator ?? "×"}
      </div>
      <Img
        src={staticFile(coBrand.logos[1].src)}
        alt={coBrand.logos[1].alt}
        style={{height: logoHeight, objectFit: "contain"}}
      />
    </div>
  );
};
