import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette} from "../theme";
import {EASE_OUT, SPRING_POP, SPRING_SETTLE} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {PaperLabel} from "../components/PaperLabel";
import {unitStartFrame} from "../timing/timeline";
import {propNumber, propString, type LayoutProps} from "./shared";
import {fitTextBlockFontSize} from "../textFit";

// City-hop roadshow timeline; the 叫停 stamp lands when the narration says it.
export const TimelineRoadshow: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cities = (scene.props.cities ?? []) as string[];
  const stampAt = unitStartFrame(propNumber(scene, "stampAtUnit", scene.units[1])) - sceneStartFrame;
  const quoteAt =
    unitStartFrame(propNumber(scene, "quoteAtUnit", scene.units[1]), propNumber(scene, "quoteOffset", 0)) -
    sceneStartFrame;

  // City nodes pop staggered across units 26-27 (~5.6s of narration).
  const railLeft = 300;
  const railWidth = 1320;
  const nodeGap = cities.length > 1 ? railWidth / (cities.length - 1) : 0;
  const cityWindowEnd = Math.max(stampAt - 8, 30);
  const cityStagger = cities.length > 1 ? cityWindowEnd / cities.length : 0;

  const railProgress = interpolate(frame, [6, cityWindowEnd], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const stampS = spring({frame: frame - stampAt, fps, config: SPRING_POP, durationInFrames: 40});
  const quoteIn = spring({frame: frame - quoteAt, fps, config: SPRING_SETTLE, durationInFrames: 40});
  const quote = propString(scene, "quote", "真正的考题才刚刚开始");
  const quoteSize = fitTextBlockFontSize({
    text: quote,
    maxWidth: 770,
    maxLines: 2,
    preferred: 48,
    min: 36,
  });

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={92} y={168} size={78} width={800} />
      <div
        style={{
          position: "absolute",
          left: railLeft,
          top: 620,
          width: railWidth,
          height: 12,
          background: "rgba(255,255,255,0.34)",
          border: `3px solid ${palette.ink}`,
        }}
      >
        <div
          style={{
            width: `${railProgress * 100}%`,
            height: "100%",
            background: palette.cyan,
          }}
        />
      </div>
      {cities.map((city, idx) => {
        const nodeStart = 10 + idx * cityStagger;
        const s = spring({frame: frame - nodeStart, fps, config: SPRING_POP, durationInFrames: 36});
        const stalled = stampS > 0.1 && idx >= cities.length - 1;
        return (
          <div
            key={city}
            style={{
              position: "absolute",
              left: railLeft + idx * nodeGap - 60,
              top: idx % 2 === 0 ? 510 : 670,
              width: 120,
              textAlign: "center",
              opacity: s,
              transform: `translateY(${(1 - s) * 30}px) scale(${s})`,
              fontFamily: fontStack,
            }}
          >
            <div
              style={{
                display: "inline-block",
                background: stalled ? palette.red : palette.white,
                color: stalled ? palette.white : palette.ink,
                border: `4px solid ${palette.ink}`,
                boxShadow: `6px 6px 0 ${palette.ink}`,
                padding: "10px 16px",
                fontSize: 32,
                fontWeight: 950,
                whiteSpace: "nowrap",
              }}
            >
              {city}
            </div>
            <div
              style={{
                width: 4,
                height: 34,
                background: palette.white,
                margin: "0 auto",
              }}
            />
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          left: 1080,
          top: 286,
          opacity: stampS,
          transform: `scale(${0.6 + stampS * 0.4}) rotate(${-8 + stampS * 2}deg)`,
          background: palette.red,
          color: palette.white,
          border: `8px solid ${palette.white}`,
          boxShadow: `14px 14px 0 ${palette.ink}`,
          padding: "22px 46px",
          fontFamily: fontStack,
          fontSize: 96,
          fontWeight: 950,
          lineHeight: 1,
          WebkitTextStroke: `2px ${palette.ink}`,
        }}
      >
        {propString(scene, "stamp", "叫停")}
      </div>
      <div
        style={{
          position: "absolute",
          left: 92,
          top: 378,
          width: 770,
          opacity: quoteIn,
          transform: `translateY(${(1 - quoteIn) * 26}px)`,
          fontFamily: fontStack,
          fontSize: quoteSize,
          fontWeight: 950,
          color: palette.yellow,
          WebkitTextStroke: `2px ${palette.ink}`,
          textShadow: `6px 6px 0 rgba(0,0,0,0.5)`,
        }}
      >
        {quote}
      </div>
      <PaperLabel
        text={propString(scene, "railLabel", "MILESTONES")}
        x={1500}
        y={168}
        color={palette.cyan}
        delay={14}
        rotate={3}
      />
    </>
  );
};
