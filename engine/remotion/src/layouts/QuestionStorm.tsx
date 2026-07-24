import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {chipColors, chipTextColor, fontStack, palette} from "../theme";
import {SPRING_SETTLE, idleFloat} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {unitStartFrame} from "../timing/timeline";
import type {LayoutProps} from "./shared";
import {fitTextBlockFontSize} from "../textFit";

type QuestionProp = {text: string; atUnit: number; offset?: number};

// Headline pinned right; question cards land timed to each spoken question.
export const QuestionStorm: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const questions = (scene.props.questions ?? []) as QuestionProp[];

  const spots = [
    {x: 120, y: 174, rotate: -3, width: 470},
    {x: 430, y: 356, rotate: 3, width: 430},
    {x: 150, y: 530, rotate: -2, width: 560},
  ];

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={1120} y={190} size={82} width={700} />
      {questions.map((question, idx) => {
        const startFrame = unitStartFrame(question.atUnit, question.offset ?? 0) - sceneStartFrame;
        const s = spring({
          frame: frame - startFrame,
          fps,
          config: SPRING_SETTLE,
          durationInFrames: 40,
        });
        const spot = spots[idx % spots.length];
        const color = chipColors[idx % chipColors.length];
        const float = idleFloat(frame, startFrame + 24, 3);
        const questionSize = fitTextBlockFontSize({
          text: question.text,
          maxWidth: spot.width - 60,
          maxLines: 2,
          preferred: 48,
          min: 34,
        });
        return (
          <div
            key={question.text}
            style={{
              position: "absolute",
              left: spot.x,
              top: spot.y,
              width: spot.width,
              transform: `translateY(${(1 - s) * 36 + float}px) rotate(${spot.rotate}deg) scale(${0.9 + s * 0.1})`,
              opacity: s,
              background: color,
              color: chipTextColor(color),
              border: `6px solid ${palette.white}`,
              boxShadow: `12px 12px 0 ${palette.ink}`,
              padding: "24px 30px",
              boxSizing: "border-box",
              fontFamily: fontStack,
              fontSize: questionSize,
              fontWeight: 950,
              lineHeight: 1.1,
              overflowWrap: "anywhere",
            }}
          >
            {question.text}
          </div>
        );
      })}
    </>
  );
};
