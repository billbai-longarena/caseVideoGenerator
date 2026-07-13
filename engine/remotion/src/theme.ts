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

export const visualTheme = {
  family: isSalesWatercolor
    ? "sales-watercolor"
    : isManagerVisual
      ? "manager-warm"
      : "editorial-default",
  preserveBlueYellow: isSalesWatercolor,
  emphasis: isSalesWatercolor ? "#174a9b" : isManagerVisual ? "#b85d32" : "#d42a2a",
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
