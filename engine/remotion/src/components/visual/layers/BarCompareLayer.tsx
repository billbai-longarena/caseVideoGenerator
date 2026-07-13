import React from "react";
import {interpolate} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {unitStartFrame} from "../../../timing/timeline";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, palette} from "../../../theme";

const barColor = (tone?: "good" | "bad" | "neutral") => {
  if (tone === "good") return "#4cd48a";
  if (tone === "bad") return "#e2b13c";
  return palette.cyan;
};

// Horizontal comparison bars. Each bar grows in when its revealAtUnit arrives
// (falling back to the layer reveal), so before/after values can land on
// exactly the narration units that speak them.
export const BarCompareLayer: React.FC<{
  layer: VisualLayer;
  visibility: number;
  frame: number;
  layerRevealFrame: number;
}> = ({layer, visibility, frame, layerRevealFrame}) => {
  const bars = layer.bars ?? [];
  if (bars.length === 0) return null;
  const maxValue = Math.max(...bars.map((bar) => bar.max ?? bar.value), 1);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 26,
        padding: "32px 40px",
        background: "rgba(5,17,31,0.82)",
        border: "2px solid rgba(255,255,255,0.5)",
        boxShadow: "12px 12px 0 rgba(5,17,31,0.66)",
        color: palette.white,
        fontFamily: fontStack,
        opacity: visibility,
        transform: `translateY(${(1 - visibility) * 22}px)`,
        minWidth: 560,
      }}
    >
      {layer.label ? (
        <div style={{fontSize: 30, fontWeight: 800, letterSpacing: 3, color: "rgba(255,255,255,0.78)"}}>
          {layer.label}
        </div>
      ) : null}
      {bars.map((bar, index) => {
        const start = bar.revealAtUnit
          ? unitStartFrame(bar.revealAtUnit)
          : layerRevealFrame + index * 8;
        const grow = interpolate(frame, [start + 2, start + 26], [0, 1], {
          easing: EASE_OUT,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const widthPct = (bar.value / maxValue) * 100 * grow;
        const shown = bar.value * grow;
        return (
          <div key={`${bar.label}-${index}`} style={{opacity: grow > 0 ? 1 : 0}}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                marginBottom: 8,
              }}
            >
              <span style={{fontSize: 32, fontWeight: 800}}>{bar.label}</span>
              <span
                style={{
                  fontSize: 46,
                  fontWeight: 950,
                  color: barColor(bar.tone),
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {Math.round(shown)}
                {bar.suffix ?? ""}
              </span>
            </div>
            <div
              style={{
                height: 26,
                background: "rgba(255,255,255,0.14)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${widthPct}%`,
                  height: "100%",
                  background: barColor(bar.tone),
                  boxShadow: `0 0 18px ${barColor(bar.tone)}55`,
                }}
              />
            </div>
          </div>
        );
      })}
      {layer.text ? (
        <div style={{fontSize: 28, fontWeight: 700, color: "rgba(255,255,255,0.8)", whiteSpace: "pre-line"}}>
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};
