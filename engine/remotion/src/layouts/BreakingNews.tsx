import React from "react";
import {palette} from "../theme";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {PaperLabel} from "../components/PaperLabel";
import {InfoCard} from "../components/InfoCard";
import {KeywordCueRow, propString, sceneUnitFrame, type LayoutProps} from "./shared";

export const BreakingNews: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const stampAt = sceneUnitFrame(scene, sceneStartFrame, "stampAtUnit", scene.units[0]);
  const infoAt = sceneUnitFrame(scene, sceneStartFrame, "infoAtUnit", scene.units[1]);

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={92} y={218} size={116} />
      <PaperLabel
        text={propString(scene, "stamp", "突发")}
        x={1310}
        y={330}
        color={palette.red}
        delay={stampAt}
        rotate={-6}
        large
      />
      <KeywordCueRow scene={scene} sceneStartFrame={sceneStartFrame} />
      <InfoCard
        label={propString(scene, "infoLabel", "CASE FILE")}
        text={propString(scene, "info", "关键线索 · 冲突升级 · 决策转折")}
        delay={infoAt}
        right={86}
        bottom={194}
        width={500}
        rotate={1.5}
      />
    </>
  );
};
