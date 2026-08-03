import React from "react";
import {interpolate} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {EASE_OUT} from "../../../anim/springs";
import {clamp, fontStack, palette, visualTheme} from "../../../theme";
import {estimatedTextUnits, fitSingleLineFontSize} from "../../../textFit";

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
  width: number;
  height: number;
}> = ({layer, visibility, localFrame, width, height}) => {
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
  // `from` controls the count-up animation baseline. A zero baseline is the
  // common way to animate a single metric and must not duplicate the metric
  // as an "▲ value" delta. Non-zero legacy comparisons remain compatible;
  // new plans can state the intent explicitly with `showDelta`.
  const hasDelta = layer.showDelta ?? (value.from !== undefined && value.from !== 0);
  const delta = value.to - from;
  const deltaColor = toneColor(layer.deltaTone);
  const settled = progress >= 1;
  const punch = interpolate(localFrame, [28, 34, 40], [1, 1.06, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const finalValueText = `${value.prefix ?? ""}${value.to.toFixed(decimals)}${value.suffix ?? ""}`;
  const deltaValueText = `${Math.abs(delta).toFixed(decimals)}${value.suffix ?? ""}`;
  const compact = width < 520 || height < 260;
  const horizontalPadding = clamp(width * 0.08, 20, 44);
  const verticalPadding = compact ? 22 : 30;
  const innerWidth = Math.max(96, width - horizontalPadding * 2 - 10);
  const preferredNumberSize = compact ? 104 : 128;
  const deltaScale = 0.38;
  const deltaArrowUnits = 1.15;
  const combinedUnits =
    estimatedTextUnits(finalValueText) +
    (hasDelta ? (estimatedTextUnits(deltaValueText) + deltaArrowUnits) * deltaScale : 0);
  const numberSize = hasDelta
    ? clamp((innerWidth * 0.84 - 18) / Math.max(1, combinedUnits), 42, preferredNumberSize)
    : fitSingleLineFontSize({
        text: finalValueText,
        maxWidth: innerWidth,
        preferred: preferredNumberSize,
        min: 42,
        safety: 0.84,
      });
  const labelSize = layer.label
    ? fitSingleLineFontSize({
        text: layer.label,
        maxWidth: innerWidth,
        preferred: compact ? 27 : 30,
        min: 20,
        safety: 0.9,
      })
    : 0;
  const align = layer.align ?? "left";
  const crossAlign = align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start";
  const mainAlign = align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start";

  return (
    <div
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: crossAlign,
        width: "100%",
        height: "fit-content",
        maxWidth: "100%",
        maxHeight: "100%",
        minWidth: 0,
        padding: `${verticalPadding}px ${horizontalPadding}px`,
        boxSizing: "border-box",
        overflow: "hidden",
        background: "rgba(5,17,31,0.82)",
        border: `5px solid ${visualTheme.accentSurface}`,
        boxShadow: "12px 12px 0 rgba(5,17,31,0.7)",
        color: palette.white,
        fontFamily: fontStack,
        opacity: visibility,
        transform: `translateY(${(1 - visibility) * 22}px)`,
        transformOrigin: `${align} center`,
      }}
    >
      {layer.label ? (
        <div
          style={{
            width: "100%",
            minWidth: 0,
            fontSize: labelSize,
            fontWeight: 800,
            letterSpacing: 3,
            color: "rgba(255,255,255,0.78)",
            marginBottom: 8,
            textAlign: align,
            whiteSpace: "nowrap",
            overflow: "hidden",
          }}
        >
          {layer.label}
        </div>
      ) : null}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: mainAlign,
          gap: 18,
          width: "100%",
          maxWidth: "100%",
          minWidth: 0,
          whiteSpace: "nowrap",
          transform: `scale(${punch})`,
          transformOrigin: `${align} center`,
        }}
      >
        <div
          style={{
            fontSize: numberSize,
            lineHeight: 1,
            fontWeight: 950,
            color: visualTheme.accentSurface,
            fontVariantNumeric: "tabular-nums",
            textShadow: "0 5px 0 rgba(0,0,0,0.55)",
            whiteSpace: "nowrap",
            flexShrink: 0,
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
              fontSize: Math.min(44, numberSize * deltaScale),
              fontWeight: 900,
              color: deltaColor,
              whiteSpace: "nowrap",
              flexShrink: 0,
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
            overflowWrap: "anywhere",
            textAlign: align,
          }}
        >
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};
