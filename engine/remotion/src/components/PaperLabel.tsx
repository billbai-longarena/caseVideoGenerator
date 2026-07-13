import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_SETTLE, idleFloat} from "../anim/springs";

export const PaperLabel: React.FC<{
  text: string;
  x: number;
  y: number;
  color: string;
  delay: number;
  rotate?: number;
  large?: boolean;
}> = ({text, x, y, color, delay, rotate = 0, large = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: SPRING_SETTLE, durationInFrames: 40});
  const float = idleFloat(frame, delay + 22);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `translateY(${(1 - s) * 28 + float}px) scale(${0.82 + s * 0.18}) rotate(${rotate}deg)`,
        opacity: s,
        background: color,
        color: color === palette.red ? palette.white : palette.ink,
        border: `4px solid ${palette.white}`,
        boxShadow: `8px 8px 0 ${palette.ink}`,
        padding: large ? "15px 28px" : "10px 20px",
        fontFamily: fontStack,
        fontSize: large ? 42 : 30,
        fontWeight: 950,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};
