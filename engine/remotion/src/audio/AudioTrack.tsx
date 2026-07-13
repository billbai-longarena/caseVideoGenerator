import React from "react";
import {Audio, Sequence, staticFile} from "remotion";
import {storyboard} from "../data/storyboard";
import type {SfxId} from "../data/types";
import {gapWindows, unitStartFrame} from "../timing/timeline";

const dbToGain = (db: number) => Math.pow(10, db / 20);

const sfxCues = storyboard.scenes.flatMap((scene) => [
  ...scene.keywords
    .filter((cue): cue is typeof cue & {sfx: SfxId} => Boolean(cue.sfx))
    .map((cue) => ({sfx: cue.sfx, frame: unitStartFrame(cue.atUnit, cue.offset ?? 0)})),
  ...scene.backgrounds
    .filter((cue): cue is typeof cue & {sfx: SfxId} => Boolean(cue.sfx))
    .map((cue) => ({sfx: cue.sfx, frame: unitStartFrame(cue.atUnit, cue.offset ?? 0)})),
]);

export const AudioTrack: React.FC<{hasBgm: boolean; hasSfx: boolean}> = ({hasBgm, hasSfx}) => {
  const bgm = storyboard.bgm;
  const gaps = gapWindows();

  return (
    <>
      <Audio src={staticFile(storyboard.audio)} volume={1} />
      {hasBgm && bgm ? (
        <Audio
          src={staticFile(bgm.src)}
          loop
          volume={(frame) => {
            const inGap = gaps.some((gap) => frame >= gap.start && frame <= gap.end);
            return dbToGain(bgm.volumeDb + (inGap ? bgm.duckBoostDb : 0));
          }}
        />
      ) : null}
      {hasSfx
        ? sfxCues.map((cue, index) => (
            <Sequence key={`${cue.sfx}-${cue.frame}-${index}`} from={cue.frame} durationInFrames={90}>
              <Audio src={staticFile(`sfx/${cue.sfx}.wav`)} volume={0.2} />
            </Sequence>
          ))
        : null}
    </>
  );
};
