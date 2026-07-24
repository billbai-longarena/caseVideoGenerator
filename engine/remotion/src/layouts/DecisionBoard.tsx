import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {chipColors, chipTextColor, fontStack, palette} from "../theme";
import {SPRING_SETTLE, idleFloat} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {unitStartFrame} from "../timing/timeline";
import type {LayoutProps} from "./shared";
import {fitTextBlockFontSize} from "../textFit";

export const DecisionBoard: React.FC<LayoutProps> = ({scene, sceneStartFrame, duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pulse = interpolate(frame, [0, duration / 2, duration], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const cardGap = 24;
  const boardWidth = 1240;
  const cardWidth = Math.min(
    310,
    (boardWidth - cardGap * Math.max(0, scene.keywords.length - 1)) /
      Math.max(1, scene.keywords.length),
  );

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={94} y={154} size={72} width={470} />
      <div
        style={{
          position: "absolute",
          left: 620,
          top: 170,
          display: "flex",
          gap: cardGap,
          width: boardWidth,
          fontFamily: fontStack,
        }}
      >
        {scene.keywords.map((keyword, idx) => {
          const startFrame =
            unitStartFrame(keyword.atUnit, keyword.offset ?? 0) - sceneStartFrame;
          const s = spring({
            frame: frame - startFrame,
            fps,
            config: SPRING_SETTLE,
            durationInFrames: 40,
          });
          const background = chipColors[idx % chipColors.length];
          const float = idleFloat(frame, startFrame + 26, 3);
          const keywordSize = fitTextBlockFontSize({
            text: keyword.text,
            maxWidth: cardWidth - 48,
            maxLines: 3,
            preferred: 48,
            min: 32,
          });
          return (
            <div
              key={keyword.text}
              style={{
                width: cardWidth,
                height: 390,
                opacity: s,
                transform: `translateY(${(1 - s) * 44 + float}px) rotate(${[-3, 1, 3][idx % 3]}deg) scale(${0.94 + s * 0.06})`,
                background,
                color: chipTextColor(background),
                border: `7px solid ${palette.white}`,
                boxShadow: `13px 13px 0 ${palette.ink}`,
                padding: 24,
                boxSizing: "border-box",
                overflow: "hidden",
                flexShrink: 0,
              }}
            >
              <div style={{fontSize: 72, fontWeight: 950, lineHeight: 1}}>
                {String.fromCharCode(65 + idx)}
              </div>
              <div style={{fontSize: keywordSize, fontWeight: 950, lineHeight: 1.08, marginTop: 34, overflowWrap: "anywhere"}}>
                {keyword.text}
              </div>
              <div
                style={{
                  marginTop: 32,
                  height: 12,
                  width: `${60 + idx * 14 + pulse * 12}%`,
                  background: idx === 2 ? palette.white : palette.blue,
                  border: `3px solid ${palette.ink}`,
                }}
              />
            </div>
          );
        })}
      </div>
    </>
  );
};
