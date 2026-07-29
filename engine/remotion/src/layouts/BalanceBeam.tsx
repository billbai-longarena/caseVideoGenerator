import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {fontStack, palette} from "../theme";
import {EASE_OUT, easedPop} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {KeywordPop} from "../components/KeywordPop";
import {unitStartFrame} from "../timing/timeline";
import {propNumber, propString, type LayoutProps} from "./shared";

// Tension line between two forces; keywords stamped along it.
export const BalanceBeam: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const line = easedPop(frame, 28, 54, EASE_OUT);
  const formulaAt =
    unitStartFrame(propNumber(scene, "formulaAtUnit", scene.units[1])) - sceneStartFrame;
  const formulaIn = interpolate(frame, [formulaAt, formulaAt + 12], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const chipSpots = [
    {x: 635, y: 188},
    {x: 1210, y: 352},
    {x: 910, y: 520},
  ];

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={88} y={170} size={78} />
      <div
        style={{
          position: "absolute",
          left: 646,
          top: 270,
          width: 900,
          height: 20,
          background: palette.white,
          transform: `scaleX(${line}) rotate(-4deg)`,
          transformOrigin: "left center",
          boxShadow: `0 7px 0 ${palette.blue}`,
        }}
      />
      {scene.keywords.map((keyword, idx) => (
        <div
          key={keyword.text}
          style={{
            position: "absolute",
            left: chipSpots[idx % chipSpots.length].x,
            top: chipSpots[idx % chipSpots.length].y,
          }}
        >
          <KeywordPop
            cue={keyword}
            startFrame={unitStartFrame(keyword.atUnit, keyword.offset ?? 0) - sceneStartFrame}
            index={idx}
            large
          />
        </div>
      ))}
      <div
        style={{
          position: "absolute",
          left: 744,
          top: 394,
          color: palette.white,
          fontFamily: fontStack,
          fontSize: 44,
          fontWeight: 950,
          opacity: formulaIn,
          transform: `translateY(${(1 - formulaIn) * 20}px)`,
          WebkitTextStroke: `2px ${palette.ink}`,
          textShadow: `5px 5px 0 ${palette.blue}`,
        }}
      >
        {propString(scene, "formula", "表层需求 ≠ 真实目标")}
      </div>
    </>
  );
};
