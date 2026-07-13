import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_SETTLE, idleFloat} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {KeywordPop} from "../components/KeywordPop";
import {unitStartFrame} from "../timing/timeline";
import {propNumber, propString, type LayoutProps} from "./shared";

// Headline top-center, focus ring left, chips scattered around the ring.
export const MapFocus: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ring = spring({frame: frame - 14, fps, config: SPRING_SETTLE, durationInFrames: 44});
  const float = idleFloat(frame, 40, 4);

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={430} y={150} size={98} align="center" />
      <div
        style={{
          position: "absolute",
          left: 150,
          top: 420,
          width: 420,
          height: 420,
          borderRadius: "50%",
          border: `10px solid ${palette.cyan}`,
          boxShadow: `0 0 0 16px rgba(255,212,90,0.75), 18px 18px 0 rgba(0,0,0,0.48)`,
          opacity: ring,
          transform: `translateY(${float}px) scale(${0.7 + ring * 0.3})`,
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: 78,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.88)",
            color: palette.blue,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: fontStack,
            fontSize: 72,
            fontWeight: 950,
            border: `6px solid ${palette.ink}`,
          }}
        >
          {propString(scene, "centerLabel", "FOCUS")}
        </div>
      </div>
      {scene.keywords.map((keyword, idx) => (
        <div
          key={keyword.text}
          style={{
            position: "absolute",
            left: [700, 1180, 900][idx % 3],
            top: [452, 550, 662][idx % 3],
          }}
        >
          <KeywordPop
            text={keyword.text}
            startFrame={unitStartFrame(keyword.atUnit, keyword.offset ?? 0) - sceneStartFrame}
            index={idx}
            large={propNumber(scene, "keywordLarge", 1) > 0}
          />
        </div>
      ))}
    </>
  );
};
