import React from "react";
import {AbsoluteFill} from "remotion";
import type {LayoutScene, Scene, Tone} from "../data/types";
import {KeywordPop} from "../components/KeywordPop";
import {unitStartFrame} from "../timing/timeline";

export type LayoutProps = {
  scene: LayoutScene;
  sceneStartFrame: number;
  duration: number;
};

// Keyword chips triggered by narration unit timing (frames are scene-local).
export const KeywordCueRow: React.FC<{
  scene: Scene;
  sceneStartFrame: number;
  x?: number;
  y?: number;
  large?: boolean;
}> = ({scene, sceneStartFrame, x = 96, y = 520, large = false}) => {
  if (scene.keywords.length === 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        display: "flex",
        gap: 18,
      }}
    >
      {scene.keywords.map((keyword, idx) => (
        <KeywordPop
          key={keyword.text}
          cue={keyword}
          startFrame={unitStartFrame(keyword.atUnit, keyword.offset ?? 0) - sceneStartFrame}
          index={idx}
          large={large}
        />
      ))}
    </div>
  );
};

export const Overlay: React.FC<{tone: Tone}> = ({tone}) => {
  const background =
    tone === "bright"
      ? "linear-gradient(90deg, rgba(5,17,31,0.38) 0%, rgba(5,17,31,0.16) 50%, rgba(255,244,209,0.04) 100%)"
      : tone === "archive"
        ? "linear-gradient(90deg, rgba(3,8,16,0.50) 0%, rgba(3,8,16,0.24) 54%, rgba(3,8,16,0.08) 100%)"
        : "linear-gradient(90deg, rgba(3,8,16,0.58) 0%, rgba(3,8,16,0.32) 54%, rgba(3,8,16,0.10) 100%)";

  return <AbsoluteFill style={{background}} />;
};

export const ArchiveTexture: React.FC<{tone: Tone}> = ({tone}) => {
  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        opacity: tone === "archive" ? 0.34 : 0.2,
        backgroundImage:
          "repeating-linear-gradient(0deg, rgba(255,255,255,0.12) 0, rgba(255,255,255,0.12) 1px, transparent 1px, transparent 6px)",
        mixBlendMode: "soft-light",
      }}
    />
  );
};

export const propNumber = (scene: Scene, key: string, fallback: number) => {
  const value = scene.props[key];
  return typeof value === "number" ? value : fallback;
};

export const propString = (scene: Scene, key: string, fallback = "") => {
  const value = scene.props[key];
  return typeof value === "string" ? value : fallback;
};

export const propNumberList = (scene: Scene, key: string, fallback: number[]) => {
  const value = scene.props[key];
  if (Array.isArray(value)) {
    const numbers = value.filter((item): item is number => typeof item === "number");
    return numbers.length > 0 ? numbers : fallback;
  }
  return fallback;
};

export const sceneUnitFrame = (
  scene: Scene,
  sceneStartFrame: number,
  key: string,
  fallbackUnit: number,
) => unitStartFrame(propNumber(scene, key, fallbackUnit)) - sceneStartFrame;
