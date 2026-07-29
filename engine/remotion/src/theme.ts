import type React from "react";
import {storyboard} from "./data/storyboard";

const visualStyle = (storyboard.visualStyle ?? "").toLowerCase();
const isSalesWatercolor =
  storyboard.projectType === "sales-case" ||
  visualStyle.includes("bright-editorial-watercolor") ||
  visualStyle.includes("sales-watercolor");
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

export const visualTheme = {
  family: isSalesWatercolor
    ? "sales-watercolor"
    : isManagerVisual
      ? "manager-warm"
      : isMontessoriVisual
        ? "montessori-bright"
        : isBaijiuVisual
          ? "baijiu-bright"
          : "editorial-default",
  preserveBlueYellow: isSalesWatercolor,
  // Brand chip surface. Legacy columns keep the cobalt chip; the E.Q.STAR
  // montessori column uses a near-black chip from its yellow/black brand;
  // the baijiu column uses a deep sorghum-amber chip.
  brandSurface: isMontessoriVisual ? "#1a1a14" : isBaijiuVisual ? "#6b3f10" : "#0b62d6",
  // Emphasized network-node surface. Legacy columns keep the cobalt node;
  // the montessori column uses its grass-green brand accent instead; the
  // baijiu column uses its amber brand accent.
  networkEmphasis: isMontessoriVisual
    ? "rgba(47,125,59,0.92)"
    : isBaijiuVisual
      ? "rgba(166,106,28,0.92)"
      : "rgba(11,98,214,0.92)",
  emphasis: isSalesWatercolor
    ? "#174a9b"
    : isManagerVisual
      ? "#b85d32"
      : isMontessoriVisual
        ? "#2f7d3b"
        : isBaijiuVisual
          ? "#a66a1c"
          : "#d42a2a",
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
