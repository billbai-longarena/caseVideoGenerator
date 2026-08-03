import React from "react";
import {interpolate} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {unitStartFrame} from "../../../timing/timeline";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, glassCardBackground, palette, visualTheme} from "../../../theme";

const barColor = (tone?: "good" | "bad" | "neutral") => {
  if (tone === "good") return visualTheme.positive;
  if (tone === "bad") return visualTheme.negative;
  return visualTheme.neutral;
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
  const compact = bars.length >= 4;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: compact ? 15 : 22,
        width: "100%",
        maxWidth: "100%",
        maxHeight: "100%",
        minWidth: 0,
        position: "relative",
        padding: compact ? "22px 28px" : "28px 34px",
        boxSizing: "border-box",
        overflow: "hidden",
        background: glassCardBackground,
        border: "2px solid rgba(255,255,255,0.66)",
        borderRadius: 8,
        boxShadow: "12px 12px 0 rgba(5,17,31,0.48), 0 22px 40px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,255,255,0.2)",
        color: palette.white,
        fontFamily: fontStack,
        opacity: visibility,
        transform: `translateY(${(1 - visibility) * 22}px)`,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: 8,
          background: visualTheme.cardAccent,
        }}
      />
      {layer.label ? (
        <div style={{fontSize: compact ? 25 : 30, fontWeight: 800, letterSpacing: 2, color: "rgba(255,255,255,0.78)"}}>
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
                marginBottom: compact ? 5 : 8,
                gap: 16,
              }}
            >
              <span style={{fontSize: compact ? 27 : 32, fontWeight: 800, minWidth: 0, overflowWrap: "anywhere"}}>{bar.label}</span>
              <span
                style={{
                  fontSize: compact ? 38 : 46,
                  fontWeight: 950,
                  color: barColor(bar.tone),
                  fontVariantNumeric: "tabular-nums",
                  whiteSpace: "nowrap",
                }}
              >
                {Math.round(shown)}
                {bar.suffix ?? ""}
              </span>
            </div>
            <div
              style={{
                height: compact ? 20 : 26,
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
        <div style={{fontSize: compact ? 23 : 28, fontWeight: 700, color: "rgba(255,255,255,0.8)", whiteSpace: "pre-line", overflowWrap: "anywhere"}}>
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};
