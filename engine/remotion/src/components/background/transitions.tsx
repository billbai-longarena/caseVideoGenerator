import React from "react";
import {AbsoluteFill, interpolate} from "remotion";
import type {BackgroundMotion, BackgroundTransition} from "../../data/types";
import {EASE_INOUT} from "../../anim/springs";

export const backgroundTransform = (
  motion: BackgroundMotion,
  localFrame: number,
  duration: number,
  extraX = 0,
  extraY = 0,
) => {
  const progress = interpolate(localFrame, [0, duration], [0, 1], {
    easing: EASE_INOUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const zoom = interpolate(progress, [0, 1], [1.025, 1.075]);
  const pan =
    motion === "left"
      ? interpolate(progress, [0, 1], [-26, 22])
      : motion === "right"
        ? interpolate(progress, [0, 1], [24, -24])
        : 0;
  const lift = motion === "lift" ? interpolate(progress, [0, 1], [18, -20]) : 0;

  return `translate3d(${pan + extraX}px, ${lift + extraY}px, 0) scale(${zoom})`;
};

export const nextBackgroundStyle = (
  transition: BackgroundTransition,
  progress: number,
): React.CSSProperties => {
  if (transition === "paper") {
    return {
      opacity: 1,
      clipPath: `inset(0 ${100 - progress * 100}% 0 0)`,
      filter: "saturate(1.1) contrast(1.05)",
    };
  }

  if (transition === "ink") {
    const leading = 12 + progress * 96;
    return {
      opacity: 1,
      clipPath: `polygon(0 0, ${leading}% 0, ${leading - 10}% 18%, ${leading - 3}% 38%, ${leading - 13}% 64%, ${leading - 5}% 100%, 0 100%)`,
      filter: "saturate(1.1) contrast(1.05)",
    };
  }

  if (transition === "push") {
    return {
      opacity: progress,
      transform: `translate3d(${(1 - progress) * 110}px, 0, 0) scale(${1.02 + progress * 0.025})`,
      filter: "saturate(1.1) contrast(1.05)",
    };
  }

  if (transition === "flash") {
    return {
      opacity: interpolate(progress, [0, 0.2, 1], [0, 0.95, 1]),
      filter: "saturate(1.14) contrast(1.08)",
    };
  }

  return {
    opacity: progress,
    filter: "saturate(1.1) contrast(1.05)",
  };
};

export const BackgroundTransitionOverlay: React.FC<{
  transition: BackgroundTransition;
  progress: number;
}> = ({transition, progress}) => {
  if (progress <= 0) {
    return null;
  }

  if (transition === "flash") {
    const opacity = interpolate(progress, [0, 0.45, 1], [0, 0.42, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity,
          background:
            "radial-gradient(circle at 58% 44%, rgba(255,232,87,0.98), rgba(255,255,255,0.58) 36%, transparent 72%)",
        }}
      />
    );
  }

  if (transition === "paper") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: 0.38,
          background: `linear-gradient(90deg, transparent 0%, transparent ${progress * 100 - 5}%, rgba(255,255,255,0.92) ${progress * 100}%, transparent ${progress * 100 + 8}%)`,
          mixBlendMode: "screen",
        }}
      />
    );
  }

  if (transition === "ink") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: 0.2 + progress * 0.18,
          background:
            "linear-gradient(115deg, rgba(11,98,214,0.8), transparent 42%), radial-gradient(circle at 34% 70%, rgba(255,212,90,0.52), transparent 36%)",
          clipPath: `polygon(0 0, ${12 + progress * 92}% 0, ${progress * 78}% 100%, 0 100%)`,
          mixBlendMode: "soft-light",
        }}
      />
    );
  }

  if (transition === "push") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: 0.16,
          background:
            "repeating-linear-gradient(90deg, rgba(255,255,255,0.32) 0, rgba(255,255,255,0.32) 2px, transparent 2px, transparent 18px)",
          transform: `translateX(${progress * 120}px)`,
          mixBlendMode: "screen",
        }}
      />
    );
  }

  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        opacity: 0.16,
        background:
          "radial-gradient(circle at 28% 35%, rgba(255,212,90,0.65), transparent 34%), radial-gradient(circle at 70% 56%, rgba(34,183,232,0.5), transparent 42%)",
        mixBlendMode: "screen",
      }}
    />
  );
};
