import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {chipColors, chipTextColor, fontStack, palette} from "../theme";
import {SPRING_POP, idleFloat} from "../anim/springs";

const ENTRANCES = [
  {x: 0, y: 50},
  {x: -50, y: 0},
  {x: 50, y: 0},
];

export const KeywordPop: React.FC<{
  text: string;
  startFrame: number;
  index: number;
  large?: boolean;
}> = ({text, startFrame, index, large = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - startFrame, fps, config: SPRING_POP, durationInFrames: 40});
  const entrance = ENTRANCES[index % ENTRANCES.length];
  const restRotation = index % 2 === 0 ? -2 : 2;
  const rotation = restRotation + (1 - s) * (index % 2 === 0 ? -5 : 5);
  const background = chipColors[index % chipColors.length];
  const float = idleFloat(frame, startFrame + 20);

  if (frame < startFrame - 2) return null;

  return (
    <div
      style={{
        opacity: Math.min(1, s * 1.4),
        transform: `translate(${(1 - s) * entrance.x}px, ${(1 - s) * entrance.y + float}px) scale(${s}) rotate(${rotation}deg)`,
        background,
        color: chipTextColor(background),
        border: `4px solid ${palette.white}`,
        boxShadow: `7px 7px 0 ${palette.ink}`,
        padding: large ? "15px 28px" : "13px 24px 15px",
        fontFamily: fontStack,
        fontSize: large ? 42 : 34,
        fontWeight: 900,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};
