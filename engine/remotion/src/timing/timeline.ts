import {storyboard, timeline, getUnit} from "../data/storyboard";
import type {Scene, VisualBeat} from "../data/types";

export const FPS = storyboard.fps;

export const secondsToFrame = (seconds: number) => Math.round(seconds * FPS);

export const unitStartFrame = (unitIndex: number, offset = 0) =>
  secondsToFrame(getUnit(unitIndex).start + offset);

export const unitEndFrame = (unitIndex: number, includePause = false) => {
  const unit = getUnit(unitIndex);
  return secondsToFrame(includePause ? unit.end + unit.pauseAfter : unit.end);
};

export const totalDurationInFrames = Math.ceil((timeline.duration + 0.5) * FPS);

export type SceneBound = {from: number; duration: number};

// Scene owns its last unit's trailing pause so cuts land on breath boundaries.
export const sceneBounds = (): SceneBound[] =>
  storyboard.scenes.map((scene, index) => {
    const from = index === 0 ? 0 : unitStartFrame(scene.units[0]);
    const isLast = index === storyboard.scenes.length - 1;
    const to = isLast ? totalDurationInFrames : unitStartFrame(storyboard.scenes[index + 1].units[0]);
    return {from, duration: Math.max(1, to - from)};
  });

export type ResolvedBackgroundCue = {
  image?: string;
  video?: string;
  startFrame: number;
  transition: "wash" | "paper" | "ink" | "flash" | "push";
  motion: "center" | "left" | "right" | "lift";
};

export const resolvedBackgroundCues = (): ResolvedBackgroundCue[] => {
  const cues = storyboard.scenes.flatMap((scene) =>
    scene.backgrounds.map((cue) => ({
      image: cue.image,
      video: cue.video,
      startFrame: unitStartFrame(cue.atUnit, cue.offset ?? 0),
      transition: cue.transition,
      motion: cue.motion,
    })),
  );
  cues.sort((a, b) => a.startFrame - b.startFrame);
  if (cues.length > 0) {
    cues[0] = {...cues[0], startFrame: 0};
  }
  return cues;
};

export type ResolvedVisualBeat = {
  scene: Scene;
  beat: VisualBeat;
  startFrame: number;
  endFrame: number;
};

export const resolvedVisualBeats = (): ResolvedVisualBeat[] => {
  const bounds = sceneBounds();
  return storyboard.scenes.flatMap((scene, sceneIndex) => {
    const beats = scene.visualBeats ?? [];
    return beats.map((beat, beatIndex) => ({
      scene,
      beat,
      startFrame: unitStartFrame(beat.atUnit),
      endFrame:
        beatIndex < beats.length - 1
          ? unitStartFrame(beats[beatIndex + 1].atUnit)
          : bounds[sceneIndex].from + bounds[sceneIndex].duration,
    }));
  });
};

export type GapWindow = {start: number; end: number};

// Narration gaps >= minSeconds, in frames — used for deterministic BGM ducking.
export const gapWindows = (minSeconds = 0.68): GapWindow[] =>
  timeline.units
    .filter((unit) => unit.pauseAfter >= minSeconds)
    .map((unit) => ({
      start: secondsToFrame(unit.end),
      end: secondsToFrame(unit.end + unit.pauseAfter),
    }));
