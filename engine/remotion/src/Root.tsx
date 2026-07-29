import React from "react";
import {Composition} from "remotion";
import {
  CoverProofOverlay,
  RichCaseVideo,
  RichCaseVideoIntentReview,
  RichCaseVideoNoAudio,
} from "./RichCaseVideo";
import {storyboard} from "./data/storyboard";
import {totalDurationInFrames} from "./timing/timeline";

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="CaseVideo"
        component={RichCaseVideo}
        durationInFrames={totalDurationInFrames}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
      <Composition
        id="CaseVideoVideoOnly"
        component={RichCaseVideoNoAudio}
        durationInFrames={totalDurationInFrames}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
      <Composition
        id="CaseVideoIntentReview"
        component={RichCaseVideoIntentReview}
        durationInFrames={totalDurationInFrames}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
      <Composition
        id="CaseVideoCoverOverlay"
        component={CoverProofOverlay}
        durationInFrames={1}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
    </>
  );
};
