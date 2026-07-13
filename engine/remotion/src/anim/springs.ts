import {Easing, interpolate, spring} from "remotion";

// Keyword chips: visible ~10% overshoot, settles in ~14 frames.
export const SPRING_POP = {damping: 11, stiffness: 190, mass: 0.7};
// Cards / paper labels: slight overshoot.
export const SPRING_SETTLE = {damping: 16, stiffness: 150, mass: 0.9};
// Headline characters: critically damped, no bounce.
export const SPRING_SMOOTH = {damping: 200};

export const EASE_OUT = Easing.out(Easing.cubic);
export const EASE_INOUT = Easing.inOut(Easing.quad);
export const EASE_EXIT = Easing.in(Easing.cubic);

export const springAt = (
  frame: number,
  startFrame: number,
  fps: number,
  config: {damping: number; stiffness?: number; mass?: number} = SPRING_SETTLE,
) => spring({frame: frame - startFrame, fps, config, durationInFrames: 40});

export const easedPop = (
  frame: number,
  start: number,
  end = start + 14,
  easing = EASE_OUT,
) =>
  interpolate(frame, [start, end], [0, 1], {
    easing,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

// Gentle 2px float so settled elements don't look frozen on long holds.
export const idleFloat = (frame: number, settleFrame: number, amplitude = 2) =>
  frame <= settleFrame ? 0 : Math.sin((frame - settleFrame) / 28) * amplitude;
