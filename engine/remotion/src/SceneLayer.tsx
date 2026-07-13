import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import type {Scene} from "./data/types";
import {EASE_EXIT, EASE_OUT} from "./anim/springs";
import {BrandBug, ChapterBadge} from "./components/BrandBug";
import {SubtitleBar} from "./components/SubtitleBar";
import {TransitionWipe} from "./components/TransitionWipe";
import {LayoutRouter} from "./layouts/LayoutRouter";
import {ArchiveTexture, Overlay} from "./layouts/shared";

export const SceneLayer: React.FC<{
  scene: Scene;
  index: number;
  sceneStartFrame: number;
  duration: number;
}> = ({scene, index, sceneStartFrame, duration}) => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, 14], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const exit = interpolate(frame, [duration - 8, duration], [1, 0], {
    easing: EASE_EXIT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const visibility = Math.min(enter, exit);
  const exitLift = (1 - exit) * -12;
  const wipe = interpolate(frame, [0, 10, 24], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const visualMode = scene.visualMode ?? (scene.visualBeats?.length ? "editorial" : "layout");
  const showLayout = visualMode !== "editorial";
  const showSceneWash = showLayout;

  return (
    <AbsoluteFill style={{opacity: visibility, transform: `translateY(${exitLift}px)`}}>
      {showSceneWash ? <Overlay tone={scene.tone} /> : null}
      {showSceneWash ? <ArchiveTexture tone={scene.tone} /> : null}
      <BrandBug kicker={scene.kicker} />
      <ChapterBadge chapter={scene.chapter} />
      {showLayout ? (
        <LayoutRouter scene={scene} sceneStartFrame={sceneStartFrame} duration={duration} />
      ) : null}
      <SubtitleBar subtitles={scene.subtitles} sceneStartFrame={sceneStartFrame} />
      <TransitionWipe progress={wipe} chapter={scene.chapter} variant={index % 3} />
    </AbsoluteFill>
  );
};
