import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_SETTLE} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {KeywordCueRow, propString, sceneUnitFrame, type LayoutProps} from "./shared";

// Full-bleed closing: overline + big centered quote + closing badge. No info card.
export const ClosingQuote: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const overlineIn = spring({frame: frame - 4, fps, config: SPRING_SETTLE, durationInFrames: 36});
  const badgeAt = sceneUnitFrame(scene, sceneStartFrame, "badgeAtUnit", scene.units[1]);
  const badgeIn = spring({frame: frame - badgeAt, fps, config: SPRING_SETTLE, durationInFrames: 40});

  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 110,
          top: 150,
          opacity: overlineIn,
          transform: `translateY(${(1 - overlineIn) * 22}px)`,
          fontFamily: fontStack,
          fontSize: 52,
          fontWeight: 950,
          color: palette.yellow,
          WebkitTextStroke: `2px ${palette.ink}`,
        }}
      >
        {propString(scene, "overline", "真正的问题，常常藏在表面需求之后")}
      </div>
      <HeadlineReveal headline={scene.headline} x={110} y={240} size={98} delay={14} />
      <KeywordCueRow scene={scene} sceneStartFrame={sceneStartFrame} x={170} y={566} large />
      <div
        style={{
          position: "absolute",
          right: 110,
          top: 220,
          width: 460,
          height: 300,
          border: `8px solid ${palette.white}`,
          background: "rgba(11,98,214,0.8)",
          boxShadow: `16px 16px 0 ${palette.ink}`,
          transform: `rotate(${2 + (1 - badgeIn) * 6}deg) scale(${0.8 + badgeIn * 0.2})`,
          opacity: badgeIn,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: palette.white,
          fontFamily: fontStack,
          fontSize: 70,
          fontWeight: 950,
          lineHeight: 1.05,
          textAlign: "center",
          whiteSpace: "pre-line",
        }}
      >
        {propString(scene, "badge", "CASE\nNOTE")}
      </div>
    </>
  );
};
