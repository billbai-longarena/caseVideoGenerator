import React from "react";
import {palette} from "../theme";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {KeywordPop} from "../components/KeywordPop";
import {InfoCard} from "../components/InfoCard";
import {unitStartFrame} from "../timing/timeline";
import {propString, sceneUnitFrame, type LayoutProps} from "./shared";

// Headline left rail, stacked keyword chips right, dark signal card lower-right.
export const SplitData: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const signalAt = sceneUnitFrame(scene, sceneStartFrame, "signalAtUnit", scene.units[1]);

  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 70,
          top: 170,
          height: 430,
          borderLeft: `10px solid ${palette.blue}`,
        }}
      />
      <HeadlineReveal headline={scene.headline} x={102} y={186} size={84} />
      {scene.keywords.map((keyword, idx) => (
        <div
          key={keyword.text}
          style={{position: "absolute", left: 700 + idx * 248, top: 240 + idx * 86}}
        >
          <KeywordPop
            cue={keyword}
            startFrame={unitStartFrame(keyword.atUnit, keyword.offset ?? 0) - sceneStartFrame}
            index={idx}
            large
          />
        </div>
      ))}
      <InfoCard
        label={propString(scene, "signalLabel", "KEY SIGNAL")}
        labelColor={palette.cyan}
        text={propString(scene, "signal", "旧评价标准正在失效")}
        delay={signalAt}
        right={96}
        bottom={220}
        width={520}
        dark
      />
    </>
  );
};
