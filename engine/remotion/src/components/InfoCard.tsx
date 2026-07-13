import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {SPRING_SETTLE, idleFloat} from "../anim/springs";

// Generic framed 花字 card: colored top rule + white body + hard shadow.
export const InfoCard: React.FC<{
  label: string;
  labelColor?: string;
  text: string;
  delay: number;
  x?: number;
  y?: number;
  right?: number;
  bottom?: number;
  width?: number;
  rotate?: number;
  dark?: boolean;
  shadowColor?: string;
}> = ({
  label,
  labelColor = palette.blue,
  text,
  delay,
  x,
  y,
  right,
  bottom,
  width = 460,
  rotate = 0,
  dark = false,
  shadowColor = palette.blue,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: SPRING_SETTLE, durationInFrames: 40});
  const float = idleFloat(frame, delay + 24);

  return (
    <div
      style={{
        position: "absolute",
        ...(x !== undefined ? {left: x} : {}),
        ...(y !== undefined ? {top: y} : {}),
        ...(right !== undefined ? {right} : {}),
        ...(bottom !== undefined ? {bottom} : {}),
        width,
        opacity: s,
        transform: `translate(${(1 - s) * 60}px, ${float}px) rotate(${rotate}deg)`,
        fontFamily: fontStack,
      }}
    >
      <div
        style={{
          background: dark ? "rgba(0,0,0,0.68)" : "rgba(255,255,255,0.94)",
          border: `5px solid ${dark ? palette.white : palette.ink}`,
          boxShadow: `12px 12px 0 ${shadowColor}`,
          padding: 26,
          color: dark ? palette.white : palette.ink,
        }}
      >
        <div style={{fontSize: 26, fontWeight: 950, color: labelColor}}>{label}</div>
        <div style={{fontSize: 44, fontWeight: 950, lineHeight: 1.1, marginTop: 12}}>{text}</div>
      </div>
    </div>
  );
};
