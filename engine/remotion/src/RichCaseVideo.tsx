import React from "react";
import {AbsoluteFill, Sequence} from "remotion";
import {palette} from "./theme";
import {storyboard} from "./data/storyboard";
import {sceneBounds} from "./timing/timeline";
import {BackgroundTrack} from "./components/background/BackgroundTrack";
import {VisualBeatTrack} from "./components/visual/VisualBeatTrack";
import {ProgressRail} from "./components/ProgressRail";
import {CoverLayer} from "./components/CoverLayer";
import {AudioTrack} from "./audio/AudioTrack";
import {SceneLayer} from "./SceneLayer";
import assets from "./data/generated/assets.json";

const bounds = sceneBounds();

type RichCaseVideoProps = {
  withAudio?: boolean;
};

export const RichCaseVideo: React.FC<RichCaseVideoProps> = ({withAudio = true}) => {
  return (
    <AbsoluteFill style={{backgroundColor: palette.ink}}>
      <BackgroundTrack />
      <VisualBeatTrack />
      {withAudio ? <AudioTrack hasBgm={assets.hasBgm} hasSfx={assets.hasSfx} /> : null}
      {storyboard.scenes.map((scene, index) => (
        <Sequence
          key={scene.id}
          from={bounds[index].from}
          durationInFrames={bounds[index].duration}
        >
          <SceneLayer
            scene={scene}
            index={index}
            sceneStartFrame={bounds[index].from}
            duration={bounds[index].duration}
          />
        </Sequence>
      ))}
      <ProgressRail />
      <CoverLayer />
    </AbsoluteFill>
  );
};

export const RichCaseVideoNoAudio: React.FC = () => <RichCaseVideo withAudio={false} />;

export const CoverProofOverlay: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: "transparent"}}>
    <CoverLayer />
  </AbsoluteFill>
);
