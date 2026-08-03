import type React from "react";
import {storyboard} from "./data/storyboard";

// Approved default from the WL-005 background-scene comparison: C = 80%.
// Keep the material centralized so cover cards, text glass cards, and semantic
// comparison cards cannot drift to different opacity defaults.
export const GLASS_CARD_OPACITY = 0.8;
export const GLASS_CARD_SECONDARY_OPACITY = 0.72;
export const glassCardBackground = `linear-gradient(145deg, rgba(5,17,31,${GLASS_CARD_OPACITY}), rgba(24,31,36,${GLASS_CARD_SECONDARY_OPACITY}))`;

const visualStyle = (storyboard.visualStyle ?? "").toLowerCase();
const isSalesWatercolor =
  storyboard.projectType === "sales-case" ||
  visualStyle.includes("bright-editorial-watercolor") ||
  visualStyle.includes("sales-watercolor") ||
  visualStyle.includes("fde-bright-watercolor");
const isManagerVisual =
  storyboard.projectType === "sales-management-case" ||
  visualStyle.includes("manager") ||
  visualStyle.includes("silhouette");
// Partner co-brand projects may provide an authorized logo pair in the
// project-local `brand/` directory. The public engine only keeps a generic
// palette; client-specific colors belong in private project configuration.
const isPartnerCoBrandVisual = visualStyle.includes("partner-co-brand");
// 女性领导力 100 series: WL-002 five-color watercolor. Every current
// women's-leadership visual style routes to this palette; the earlier
// single-red family is retired for new and revised production.
const isWomenLeadershipVisual = visualStyle.includes("women-leadership");

export const visualTheme = {
  family: isWomenLeadershipVisual
    ? "women-leadership-five-color-watercolor"
    : isPartnerCoBrandVisual
    ? "partner-co-brand-watercolor"
    : isSalesWatercolor
    ? "sales-watercolor"
    : isManagerVisual
      ? "manager-warm"
      : "editorial-default",
  preserveBlueYellow: isSalesWatercolor,
  // Brand chip surface. Client-specific colors belong in private project
  // configuration; the public engine uses a neutral partner palette.
  brandSurface: isWomenLeadershipVisual
    ? "#CA4D2A"
    : isPartnerCoBrandVisual
    ? "#245f75"
    : "#0b62d6",
  // Emphasized network-node surface. Client-specific colors are not stored
  // in the public repository.
  networkEmphasis: isWomenLeadershipVisual
    ? "rgba(89,165,93,0.92)"
    : isPartnerCoBrandVisual
    ? "rgba(0,133,160,0.92)"
    : "rgba(11,98,214,0.92)",
  // Opaque accent text-card surface. Partner colors are intentionally
  // generic; authorized brand colors stay in private project inputs.
  accentSurface: isWomenLeadershipVisual
    ? "#EFDB56"
    : isPartnerCoBrandVisual
      ? "#8fd3d0"
      : "#ffd45a",
  emphasis: isWomenLeadershipVisual
    ? "#CA4D2A"
    : isPartnerCoBrandVisual
    ? "#167f8f"
    : isSalesWatercolor
    ? "#174a9b"
    : isManagerVisual
      ? "#b85d32"
      : "#d42a2a",
  positive: isWomenLeadershipVisual ? "#59A55D" : "#4cd48a",
  negative: isWomenLeadershipVisual ? "#CA4D2A" : "#e2b13c",
  neutral: isWomenLeadershipVisual ? "#7D9DC6" : "#22b7e8",
  supportive: isWomenLeadershipVisual ? "#ECA23F" : "#ffd45a",
  cardAccent: isWomenLeadershipVisual
    ? "linear-gradient(90deg, #59A55D 0 20%, #EFDB56 20% 40%, #7D9DC6 40% 60%, #ECA23F 60% 80%, #CA4D2A 80% 100%)"
    : "linear-gradient(90deg, #ffd45a, #22b7e8, #d42a2a)",
} as const;

export const fontStack =
  '"PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif';

export const palette = {
  ink: "#06111f",
  blue: "#0b62d6",
  cyan: "#22b7e8",
  // Backward-compatible semantic emphasis color. Its value follows the
  // storyboard visual family instead of forcing literal red into every case.
  red: visualTheme.emphasis,
  yellow: "#ffd45a",
  white: "#f9fbff",
};

export const chipColors = [palette.yellow, palette.cyan, palette.red];

export const chipTextColor = (background: string) =>
  background === palette.red ? palette.white : palette.ink;

// The signature 花字 treatment: heavy stroke + hard offset shadow.
export const strokeShadow = (
  strokeWidth = 4,
  shadowColor = palette.blue,
  shadowOffset = 10,
): React.CSSProperties => ({
  WebkitTextStroke: `${strokeWidth}px ${palette.ink}`,
  textShadow: `${shadowOffset}px ${shadowOffset}px 0 ${shadowColor}, ${Math.round(
    shadowOffset * 1.5,
  )}px ${Math.round(shadowOffset * 1.5)}px 0 rgba(0,0,0,0.46)`,
});

export const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));
