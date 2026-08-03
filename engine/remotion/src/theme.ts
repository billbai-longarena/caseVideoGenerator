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
// E.Q.STAR 蒙淇星 custom column: bright watercolor with a yellow/black + grass
// green brand palette. Grass green replaces the default red emphasis so
// semantic accents stay on-brand.
const isMontessoriVisual = visualStyle.includes("montessori");
// 杯中故事 baijiu column: bright watercolor with a warm amber/sorghum-gold
// brand palette. Amber replaces the default emphasis so chrome matches the
// baijiu warm-gold imagery.
const isBaijiuVisual = visualStyle.includes("baijiu");
// PPG PMC brand stories: bright industrial watercolor with a clean
// steel-blue/zinc palette. Steel blue replaces the default emphasis so
// chrome matches the PPG protective-coatings imagery.
const isPpgVisual = visualStyle.includes("ppg");
// 中电福富 (ZDFF) brand stories: bright tech watercolor with a clean
// sky-blue/silver palette. Sky blue replaces the default emphasis so
// chrome matches the cybersecurity/compliance product imagery.
const isZdffVisual = visualStyle.includes("zdff");
// SalesNail × WorkBuddy co-brand series: bright watercolor keyed to the two
// partner logos. SalesNail blue becomes the brand surface and WorkBuddy jade
// becomes the emphasis/accent, replacing the default blue/yellow sales
// palette for joint-promotion videos only.
const isSalesnailWorkbuddyVisual = visualStyle.includes("salesnail-workbuddy");
// 女性领导力 100 series: WL-002 five-color watercolor. Every current
// women's-leadership visual style routes to this palette; the earlier
// single-red family is retired for new and revised production.
const isWomenLeadershipVisual = visualStyle.includes("women-leadership");

export const visualTheme = {
  family: isWomenLeadershipVisual
    ? "women-leadership-five-color-watercolor"
    : isSalesnailWorkbuddyVisual
    ? "salesnail-workbuddy-watercolor"
    : isSalesWatercolor
    ? "sales-watercolor"
    : isManagerVisual
      ? "manager-warm"
      : isMontessoriVisual
        ? "montessori-bright"
        : isBaijiuVisual
          ? "baijiu-bright"
          : isPpgVisual
            ? "ppg-bright"
            : isZdffVisual
              ? "zdff-bright"
              : "editorial-default",
  preserveBlueYellow: isSalesWatercolor,
  // Brand chip surface. Legacy columns keep the cobalt chip; the E.Q.STAR
  // montessori column uses a near-black chip from its yellow/black brand;
  // the baijiu column uses a deep sorghum-amber chip; PPG uses a deep
  // steel-blue chip from its protective-coatings palette; the SalesNail ×
  // WorkBuddy co-brand series uses the SalesNail logo blue; the
  // 女性领导力 (women's leadership) uses the five-color family's terracotta.
  brandSurface: isWomenLeadershipVisual
    ? "#CA4D2A"
    : isSalesnailWorkbuddyVisual
    ? "#3671db"
    : isMontessoriVisual
    ? "#1a1a14"
    : isBaijiuVisual
      ? "#6b3f10"
      : isPpgVisual
        ? "#1c4e6e"
        : isZdffVisual
          ? "#0d4a8a"
          : "#0b62d6",
  // Emphasized network-node surface. Legacy columns keep the cobalt node;
  // the montessori column uses its grass-green brand accent instead; the
  // baijiu column uses its amber brand accent; PPG uses steel blue; the
  // co-brand series uses WorkBuddy jade; 女性领导力 uses leaf green.
  networkEmphasis: isWomenLeadershipVisual
    ? "rgba(89,165,93,0.92)"
    : isSalesnailWorkbuddyVisual
    ? "rgba(0,168,132,0.92)"
    : isMontessoriVisual
    ? "rgba(47,125,59,0.92)"
    : isBaijiuVisual
      ? "rgba(166,106,28,0.92)"
      : isPpgVisual
        ? "rgba(28,78,110,0.92)"
        : isZdffVisual
          ? "rgba(13,74,138,0.92)"
          : "rgba(11,98,214,0.92)",
  // Opaque accent text-card surface. Legacy columns keep cadmium yellow;
  // the co-brand series uses WorkBuddy jade so hero cards match the
  // partner logos.
  accentSurface: isWomenLeadershipVisual
    ? "#EFDB56"
    : isSalesnailWorkbuddyVisual
      ? "#00c090"
      : "#ffd45a",
  emphasis: isWomenLeadershipVisual
    ? "#CA4D2A"
    : isSalesnailWorkbuddyVisual
    ? "#0e8a6d"
    : isSalesWatercolor
    ? "#174a9b"
    : isManagerVisual
      ? "#b85d32"
      : isMontessoriVisual
        ? "#2f7d3b"
        : isBaijiuVisual
          ? "#a66a1c"
          : isPpgVisual
            ? "#2e7ca6"
            : isZdffVisual
              ? "#1a6db5"
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
