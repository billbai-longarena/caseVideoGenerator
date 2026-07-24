import React from "react";
import {interpolate} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, palette} from "../../../theme";
import {fitTextBlockFontSize} from "../../../textFit";

// Speech bubble bound to a portrait: bubble pops, then the quote types on
// clause by clause. `tail` points the bubble at the speaker's side.
export const DialogueLayer: React.FC<{
  layer: VisualLayer;
  visibility: number;
  localFrame: number;
}> = ({layer, visibility, localFrame}) => {
  const text = layer.text ?? "";
  if (!text) return null;
  const tail = layer.tail ?? "left";
  const pop = interpolate(localFrame, [0, 12], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const charsShown = Math.floor(
    interpolate(localFrame, [8, 8 + text.length * 1.6], [0, text.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }),
  );
  const shown = text.slice(0, charsShown);
  const textSize = fitTextBlockFontSize({
    text,
    maxWidth: 660,
    maxLines: 4,
    preferred: 42,
    min: 30,
  });

  return (
    <div
      style={{
        position: "relative",
        display: "inline-flex",
        flexDirection: "column",
        width: "fit-content",
        boxSizing: "border-box",
        maxWidth: 760,
        opacity: visibility * pop,
        transform: `translateY(${(1 - pop) * 26}px) scale(${0.94 + pop * 0.06})`,
        transformOrigin: tail === "left" ? "bottom left" : "bottom right",
        fontFamily: fontStack,
      }}
    >
      {layer.speaker ? (
        <div
          style={{
            alignSelf: tail === "left" ? "flex-start" : "flex-end",
            background: palette.blue,
            color: palette.white,
            fontSize: 28,
            fontWeight: 900,
            letterSpacing: 2,
            padding: "8px 22px",
            marginBottom: -4,
            zIndex: 2,
            boxShadow: "6px 6px 0 rgba(5,17,31,0.6)",
          }}
        >
          {layer.speaker}
        </div>
      ) : null}
      <div
        style={{
          position: "relative",
          background: "rgba(249,251,255,0.97)",
          color: palette.ink,
          maxWidth: "100%",
          boxSizing: "border-box",
          fontSize: textSize,
          fontWeight: 800,
          lineHeight: 1.4,
          padding: "30px 38px",
          border: `4px solid ${palette.ink}`,
          boxShadow: "12px 12px 0 rgba(5,17,31,0.55)",
          whiteSpace: "pre-line",
          overflowWrap: "anywhere",
          minHeight: 60,
        }}
      >
        {shown}
        {charsShown < text.length ? (
          <span style={{opacity: localFrame % 16 < 8 ? 1 : 0}}>▌</span>
        ) : null}
        <div
          style={{
            position: "absolute",
            bottom: -26,
            [tail === "left" ? "left" : "right"]: 64,
            width: 0,
            height: 0,
            borderLeft: "22px solid transparent",
            borderRight: "22px solid transparent",
            borderTop: `26px solid ${palette.ink}`,
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: -17,
            [tail === "left" ? "left" : "right"]: 70,
            width: 0,
            height: 0,
            borderLeft: "16px solid transparent",
            borderRight: "16px solid transparent",
            borderTop: "20px solid rgba(249,251,255,0.97)",
          }}
        />
      </div>
    </div>
  );
};
