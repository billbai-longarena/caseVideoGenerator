import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {fontStack, palette, visualTheme} from "../theme";
import {SPRING_SETTLE, EASE_OUT} from "../anim/springs";
import {getUnit, storyboard} from "../data/storyboard";
import {secondsToFrame} from "../timing/timeline";
import type {SubtitleCue} from "../data/types";

type DisplayCue = {
  text: string;
  startFrame: number;
  endFrame: number;
};

const textLength = (value: string) => Array.from(value).length;

const subtitleFontSize = (text: string) => {
  const length = textLength(text);
  if (length > 58) return 28;
  if (length > 46) return 30;
  return 34;
};

// Merge clauses separated by short pauses when the combined text remains within
// a two-line subtitle bar. This keeps short timeline units from looking like
// they only occupy the left half of the available caption area.
const buildDisplayCues = (subtitles: SubtitleCue[]): DisplayCue[] => {
  const cues: DisplayCue[] = [];
  for (const cue of subtitles) {
    const unit = getUnit(cue.unit);
    const startFrame = secondsToFrame(unit.start);
    const endFrame = secondsToFrame(unit.end + unit.pauseAfter);
    const prev = cues[cues.length - 1];
    const prevUnit = cue.unit > 1 ? getUnit(cue.unit - 1) : null;
    if (
      prev &&
      prevUnit &&
      prevUnit.pauseAfter < 0.4 &&
      textLength(prev.text) + textLength(cue.text) <= 46
    ) {
      prev.text += cue.text;
      prev.endFrame = endFrame;
    } else {
      cues.push({text: cue.text, startFrame, endFrame});
    }
  }
  return cues;
};

export const SubtitleBar: React.FC<{
  subtitles: SubtitleCue[];
  sceneStartFrame: number;
}> = ({subtitles, sceneStartFrame}) => {
  const localFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const absoluteFrame = localFrame + sceneStartFrame;
  const cues = buildDisplayCues(subtitles);

  const active = cues.find(
    (cue) => absoluteFrame >= cue.startFrame && absoluteFrame < cue.endFrame,
  );
  const fallback = cues[cues.length - 1];
  const cue = active ?? (absoluteFrame >= (fallback?.endFrame ?? 0) ? fallback : cues[0]);
  if (!cue) return null;

  const barIn = spring({frame: localFrame - 8, fps, config: SPRING_SETTLE, durationInFrames: 36});
  const clauseLocal = absoluteFrame - cue.startFrame;
  const clauseIn = interpolate(clauseLocal, [0, 4], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fontSize = subtitleFontSize(cue.text);
  const subtitleLabel = storyboard.subtitleLabel ?? "旁白";
  const labelLength = Array.from(subtitleLabel).length;
  const labelColumnWidth = Math.max(160, Math.min(300, labelLength * 42 + 44));
  const labelFontSize = labelLength > 4 ? 30 : 34;

  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        right: 70,
        bottom: 52,
        transform: `translateY(${(1 - barIn) * 92}px)`,
        display: "grid",
        gridTemplateColumns: `${labelColumnWidth}px 1fr`,
        alignItems: "stretch",
        fontFamily: fontStack,
        border: `4px solid ${palette.white}`,
        boxShadow: `8px 8px 0 rgba(0,0,0,0.76)`,
      }}
    >
      <div
        style={{
          background: visualTheme.brandSurface,
          color: palette.white,
          fontWeight: 950,
          fontSize: labelFontSize,
          lineHeight: 1,
          whiteSpace: "nowrap",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 16px",
          borderRight: `4px solid ${palette.white}`,
        }}
      >
        {subtitleLabel}
      </div>
      <div
        style={{
          minHeight: 84,
          background: "rgba(0,0,0,0.78)",
          color: palette.white,
          fontSize,
          lineHeight: 1.34,
          fontWeight: 700,
          padding: "18px 26px 16px",
          textShadow: "0 2px 0 rgba(0,0,0,0.8)",
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-start",
          overflow: "hidden",
        }}
      >
        <span
          style={{
            opacity: clauseIn,
            transform: `translateY(${(1 - clauseIn) * 8}px)`,
            display: "block",
            width: "100%",
            maxWidth: "100%",
            whiteSpace: "normal",
            overflowWrap: "anywhere",
            wordBreak: "normal",
          }}
        >
          {cue.text}
        </span>
      </div>
    </div>
  );
};
