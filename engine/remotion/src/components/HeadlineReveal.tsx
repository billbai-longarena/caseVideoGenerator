import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette, strokeShadow} from "../theme";
import {SPRING_SETTLE, SPRING_SMOOTH, idleFloat} from "../anim/springs";
import type {HeadlineSpec} from "../data/types";

const accentRanges = (line: string, accents: string[]) => {
  const flags = new Array<boolean>(line.length).fill(false);
  for (const accent of accents) {
    let from = 0;
    while (true) {
      const hit = line.indexOf(accent, from);
      if (hit === -1) break;
      for (let i = hit; i < hit + accent.length; i += 1) flags[i] = true;
      from = hit + accent.length;
    }
  }
  return flags;
};

export const HeadlineReveal: React.FC<{
  headline: HeadlineSpec;
  x?: number;
  y?: number;
  size?: number;
  delay?: number;
  align?: "left" | "center" | "right";
  width?: number;
}> = ({headline, x = 92, y = 218, size = 116, delay = 4, align = "left", width = 1060}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const lines = headline.text.split("\n");
  const charStagger = 2;

  let charCursor = 0;
  const totalChars = lines.reduce((sum, line) => sum + Array.from(line).length, 0);
  const settleFrame = delay + totalChars * charStagger + 18;
  const float = idleFloat(frame, settleFrame);

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width,
        transform: `translateY(${float}px)`,
        fontFamily: fontStack,
        fontSize: size,
        lineHeight: 1.02,
        fontWeight: 950,
        color: palette.white,
        textAlign: align,
      }}
    >
      {lines.map((line, lineIndex) => {
        const chars = Array.from(line);
        const flags = accentRanges(line, headline.accent);
        return (
          <div key={lineIndex} style={{whiteSpace: "nowrap"}}>
            {headline.reveal === "perClause"
              ? (() => {
                  const lineDelay = delay + lineIndex * 10;
                  const s = spring({
                    frame: frame - lineDelay,
                    fps,
                    config: SPRING_SETTLE,
                    durationInFrames: 40,
                  });
                  charCursor += chars.length;
                  return (
                    <span
                      style={{
                        display: "inline-block",
                        opacity: s,
                        transform: `translateY(${(1 - s) * 44}px)`,
                        ...strokeShadow(Math.max(2, Math.round(size / 30))),
                      }}
                    >
                      {chars.map((ch, i) => (
                        <span key={i} style={flags[i] ? {color: palette.yellow} : undefined}>
                          {ch}
                        </span>
                      ))}
                    </span>
                  );
                })()
              : chars.map((ch, i) => {
                  const charDelay = delay + charCursor * charStagger;
                  charCursor += 1;
                  const s = spring({
                    frame: frame - charDelay,
                    fps,
                    config: SPRING_SMOOTH,
                    durationInFrames: 30,
                  });
                  const accent = flags[i];
                  const pulse = accent
                    ? 1 +
                      0.08 *
                        spring({
                          frame: frame - charDelay - 3,
                          fps,
                          config: SPRING_SMOOTH,
                          durationInFrames: 24,
                        }) *
                        (1 - Math.min(1, Math.max(0, (frame - charDelay - 16) / 10)))
                    : 1;
                  return (
                    <span
                      key={i}
                      style={{
                        display: "inline-block",
                        opacity: s,
                        transform: `translateY(${(1 - s) * 40}px) scale(${(1.15 - 0.15 * s) * pulse})`,
                        color: accent ? palette.yellow : palette.white,
                        ...strokeShadow(Math.max(2, Math.round(size / 30))),
                      }}
                    >
                      {ch === " " ? " " : ch}
                    </span>
                  );
                })}
          </div>
        );
      })}
    </div>
  );
};
