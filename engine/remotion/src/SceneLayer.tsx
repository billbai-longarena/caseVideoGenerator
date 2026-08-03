import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import type {LayoutScene, Scene, StoryboardChrome} from "./data/types";
import {EASE_EXIT, EASE_OUT} from "./anim/springs";
import {BrandBug, ChapterBadge} from "./components/BrandBug";
import {SubtitleBar} from "./components/SubtitleBar";
import {TransitionWipe} from "./components/TransitionWipe";
import {LayoutRouter} from "./layouts/LayoutRouter";
import {ArchiveTexture, Overlay} from "./layouts/shared";
import {unitStartFrame} from "./timing/timeline";
import {coverEndFrame} from "./timing/cover";

export const SceneLayer: React.FC<{
  scene: Scene;
  chrome?: StoryboardChrome;
  sceneStartFrame: number;
  duration: number;
  suppressChromeForCover?: boolean;
}> = ({scene, chrome, sceneStartFrame, duration, suppressChromeForCover = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enterMode = scene.sceneMotion?.enter ?? "fade";
  const exitMode = scene.sceneMotion?.exit ?? "lift";
  const enterFrames = scene.sceneMotion?.enterFrames ?? 14;
  const exitFrames = scene.sceneMotion?.exitFrames ?? 8;
  const transitionFrames = scene.transitionFrames ?? 24;
  const enter =
    enterMode === "cut"
      ? 1
      : interpolate(frame, [0, enterFrames], [0, 1], {
          easing: EASE_OUT,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
  const exit =
    exitMode === "cut"
      ? 1
      : interpolate(frame, [duration - exitFrames, duration], [1, 0], {
          easing: EASE_EXIT,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
  const visibility = Math.min(enter, exit);
  const enterRise = enterMode === "rise" ? (1 - enter) * 24 : 0;
  const exitLift = exitMode === "lift" ? (1 - exit) * -12 : 0;
  const wipePeak = Math.max(1, Math.round(transitionFrames * 0.42));
  const wipe = interpolate(frame, [0, wipePeak, transitionFrames], [0, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const visualMode = scene.visualMode ?? (scene.visualBeats?.length ? "editorial" : "layout");
  const showLayout = visualMode !== "editorial";
  if (showLayout && (!scene.tone || !scene.headline)) {
    throw new Error(`Template scene ${scene.id} requires tone and headline`);
  }
  const layoutScene = showLayout ? (scene as LayoutScene) : null;
  const globalChrome = chrome ?? {
    brandBug: true,
    chapterBadge: true,
    subtitleBar: true,
    progressRail: true,
    cover: true,
  };
  const absoluteFrame = sceneStartFrame + frame;
  const activeBeat = [...(scene.visualBeats ?? [])]
    .reverse()
    .find((beat) => unitStartFrame(beat.atUnit) <= absoluteFrame);
  const showBrandBug = activeBeat?.chrome?.brandBug ?? scene.chrome?.brandBug ?? globalChrome.brandBug;
  const showChapterBadge =
    activeBeat?.chrome?.chapterBadge ?? scene.chrome?.chapterBadge ?? globalChrome.chapterBadge;
  const showSubtitleBar =
    activeBeat?.chrome?.subtitleBar ?? scene.chrome?.subtitleBar ?? globalChrome.subtitleBar;
  const coverOwnsChrome = suppressChromeForCover && absoluteFrame < coverEndFrame(fps);

  return (
    <AbsoluteFill
      style={{opacity: visibility, transform: `translateY(${enterRise + exitLift}px)`}}
    >
      {layoutScene ? <Overlay tone={layoutScene.tone} /> : null}
      {layoutScene ? <ArchiveTexture tone={layoutScene.tone} /> : null}
      {showBrandBug && !coverOwnsChrome ? <BrandBug kicker={scene.kicker} /> : null}
      {showChapterBadge && !coverOwnsChrome ? <ChapterBadge chapter={scene.chapter} /> : null}
      {layoutScene ? (
        <LayoutRouter scene={layoutScene} sceneStartFrame={sceneStartFrame} duration={duration} />
      ) : null}
      {showSubtitleBar && !coverOwnsChrome ? (
        <SubtitleBar subtitles={scene.subtitles} sceneStartFrame={sceneStartFrame} />
      ) : null}
      <TransitionWipe
        progress={wipe}
        chapter={scene.chapter}
        variant={scene.transition ?? "ink-slide"}
      />
    </AbsoluteFill>
  );
};
