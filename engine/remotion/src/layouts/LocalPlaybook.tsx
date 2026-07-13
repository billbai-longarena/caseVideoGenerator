import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_SETTLE} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {KeywordPop} from "../components/KeywordPop";
import {unitStartFrame} from "../timing/timeline";
import {propString, type LayoutProps} from "./shared";

export const LocalPlaybook: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const badgeIn = spring({frame: frame - 4, fps, config: SPRING_SETTLE, durationInFrames: 36});
  const cardIn = spring({frame: frame - 50, fps, config: SPRING_SETTLE, durationInFrames: 40});

  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 90,
          top: 176,
          display: "inline-block",
          opacity: badgeIn,
          transform: `translateX(${(1 - badgeIn) * -40}px)`,
          background: palette.blue,
          border: `5px solid ${palette.white}`,
          boxShadow: `10px 10px 0 ${palette.ink}`,
          padding: "12px 22px",
          fontSize: 34,
          fontWeight: 950,
          fontFamily: fontStack,
          color: palette.white,
        }}
      >
        {propString(scene, "badge", "关键资源")}
      </div>
      <HeadlineReveal headline={scene.headline} x={90} y={266} size={96} />
      {scene.keywords.map((keyword, idx) => (
        <div
          key={keyword.text}
          style={{position: "absolute", left: 900 + idx * 230, top: 210 + idx * 118}}
        >
          <KeywordPop
            text={keyword.text}
            startFrame={unitStartFrame(keyword.atUnit, keyword.offset ?? 0) - sceneStartFrame}
            index={idx}
            large
          />
        </div>
      ))}
      <div
        style={{
          position: "absolute",
          right: 118,
          bottom: 205,
          width: 500,
          opacity: cardIn,
          fontFamily: fontStack,
          transform: `translateY(${(1 - cardIn) * 44}px) rotate(-2deg)`,
        }}
      >
        <div style={{height: 34, background: palette.yellow, border: `5px solid ${palette.ink}`}} />
        <div
          style={{
            background: "rgba(255,255,255,0.94)",
            border: `5px solid ${palette.ink}`,
            borderTop: 0,
            padding: 24,
            color: palette.ink,
            boxShadow: `12px 12px 0 ${palette.blue}`,
          }}
        >
          <div style={{fontSize: 28, fontWeight: 950, color: palette.red}}>
            {propString(scene, "cardTitle", "RESOURCE MAP")}
          </div>
          <div style={{fontSize: 40, fontWeight: 950, lineHeight: 1.1}}>
            {propString(scene, "cardText", "角色识别 + 资源整合")}
          </div>
        </div>
      </div>
    </>
  );
};
