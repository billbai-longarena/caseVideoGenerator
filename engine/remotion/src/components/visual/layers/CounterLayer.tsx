import React from "react";
import {interpolate} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, palette} from "../../../theme";

const toneColor = (tone?: "good" | "bad" | "neutral") => {
  if (tone === "good") return "#4cd48a";
  if (tone === "bad") return palette.yellow;
  return palette.white;
};

// Animated number: rolls from `value.from` (or 0) to `value.to` over ~26 frames
// after the layer reveals, with an optional delta arrow when `from` is present.
export const CounterLayer: React.FC<{
  layer: VisualLayer;
  visibility: number;
  localFrame: number;
}> = ({layer, visibility, localFrame}) => {
  const value = layer.value;
  if (!value) return null;
  const from = value.from ?? 0;
  const decimals = value.decimals ?? 0;
  const progress = interpolate(localFrame, [4, 30], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const current = from + (value.to - from) * progress;
  const hasDelta = value.from !== undefined;
  const delta = value.to - from;
  const deltaColor = toneColor(layer.deltaTone);
  const settled = progress >= 1;
  const punch = interpolate(localFrame, [28, 34, 40], [1, 1.06, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: "flex-start",
        padding: "30px 44px",
        background: "rgba(5,17,31,0.82)",
        border: `5px solid ${palette.yellow}`,
        boxShadow: "12px 12px 0 rgba(5,17,31,0.7)",
        color: palette.white,
        fontFamily: fontStack,
        opacity: visibility,
        transform: `translateY(${(1 - visibility) * 22}px) scale(${punch})`,
        transformOrigin: "left center",
      }}
    >
      {layer.label ? (
        <div
          style={{
            fontSize: 30,
            fontWeight: 800,
            letterSpacing: 3,
            color: "rgba(255,255,255,0.78)",
            marginBottom: 8,
          }}
        >
          {layer.label}
        </div>
      ) : null}
      <div style={{display: "flex", alignItems: "baseline", gap: 22}}>
        <div
          style={{
            fontSize: 128,
            lineHeight: 1,
            fontWeight: 950,
            color: palette.yellow,
            fontVariantNumeric: "tabular-nums",
            textShadow: "0 5px 0 rgba(0,0,0,0.55)",
          }}
        >
          {value.prefix ?? ""}
          {current.toFixed(decimals)}
          {value.suffix ?? ""}
        </div>
        {hasDelta && settled ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 44,
              fontWeight: 900,
              color: deltaColor,
            }}
          >
            <span style={{fontSize: 52, lineHeight: 1}}>{delta >= 0 ? "▲" : "▼"}</span>
            {Math.abs(delta).toFixed(decimals)}
            {value.suffix ?? ""}
          </div>
        ) : null}
      </div>
      {layer.text ? (
        <div
          style={{
            marginTop: 12,
            fontSize: 30,
            fontWeight: 700,
            color: "rgba(255,255,255,0.86)",
            whiteSpace: "pre-line",
          }}
        >
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};
