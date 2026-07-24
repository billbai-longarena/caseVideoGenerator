import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_POP, idleFloat} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {InfoCard} from "../components/InfoCard";
import {unitStartFrame} from "../timing/timeline";
import {propNumber, propString, sceneUnitFrame, type LayoutProps} from "./shared";
import {fitSingleLineFontSize} from "../textFit";

// No keyword chip row, no standard card position: the big yellow slab is the scene.
export const SubjectReveal: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const revealAtUnit = propNumber(scene, "revealAtUnit", scene.units[1]);
  const revealDelay =
    unitStartFrame(revealAtUnit, propNumber(scene, "revealOffset", 0)) - sceneStartFrame;
  const s = spring({frame: frame - revealDelay, fps, config: SPRING_POP, durationInFrames: 44});
  const float = idleFloat(frame, revealDelay + 24, 3);
  const noteAt = sceneUnitFrame(scene, sceneStartFrame, "noteAtUnit", revealAtUnit);
  const reveal = propString(scene, "reveal", "关键主角");
  const revealWidth = 1240;
  const revealSize = fitSingleLineFontSize({
    text: reveal,
    maxWidth: revealWidth - 108,
    preferred: propNumber(scene, "revealSize", 140),
    min: 64,
  });

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={90} y={190} size={72} width={960} />
      <div
        style={{
          position: "absolute",
          left: 92,
          top: 430,
          width: revealWidth,
          boxSizing: "border-box",
          opacity: Math.min(1, s * 1.3),
          transform: `translateY(${float}px) scale(${s}) rotate(${-4 - (1 - s) * 6}deg)`,
          transformOrigin: "left center",
          background: palette.yellow,
          color: palette.ink,
          border: `8px solid ${palette.white}`,
          boxShadow: `16px 16px 0 ${palette.blue}`,
          padding: "26px 54px 30px",
          fontFamily: fontStack,
          fontSize: revealSize,
          fontWeight: 950,
          lineHeight: 1,
          WebkitTextStroke: `2px ${palette.ink}`,
        }}
      >
        {reveal}
      </div>
      <InfoCard
        label={propString(scene, "noteLabel", "CASE NOTE")}
        text={propString(scene, "note", "表面的题目，往往不是客户真正的问题")}
        delay={noteAt}
        right={110}
        y={188}
        width={430}
        rotate={2}
        shadowColor={palette.red}
      />
    </>
  );
};
