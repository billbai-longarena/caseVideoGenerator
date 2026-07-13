import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {SPRING_SETTLE} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {fontStack, palette} from "../theme";
import {unitStartFrame} from "../timing/timeline";
import {propNumberList, propString, sceneUnitFrame, type LayoutProps} from "./shared";

export const PerformanceLadder: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const years = propString(scene, "years", "2022|2023|2024").split("|");
  const values = propString(scene, "values", "3900万|4300万|4800万").split("|");
  const valueAtUnits = propNumberList(scene, "valueAtUnits", values.map((_, index) => scene.units[0] + index));
  const badgeAt = sceneUnitFrame(scene, sceneStartFrame, "badgeAtUnit", scene.units[1]);
  const badgeIn = spring({frame: frame - badgeAt, fps, config: SPRING_SETTLE, durationInFrames: 42});
  const maxHeight = 360;

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={92} y={150} size={82} width={780} />
      <div style={{position: "absolute", left: 900, top: 210, display: "flex", gap: 54, alignItems: "flex-end", height: 470}}>
        {values.map((value, index) => {
          const startFrame = unitStartFrame(valueAtUnits[index] ?? valueAtUnits[valueAtUnits.length - 1]) - sceneStartFrame;
          const progress = spring({frame: frame - startFrame, fps, config: SPRING_SETTLE, durationInFrames: 44});
          const height = (210 + index * 70) * progress;
          return (
            <div key={`${years[index]}-${value}`} style={{width: 220, textAlign: "center", fontFamily: fontStack}}>
              <div style={{fontSize: 48, fontWeight: 950, color: palette.yellow, marginBottom: 14, opacity: progress}}>{value}</div>
              <div style={{height: maxHeight, display: "flex", alignItems: "flex-end"}}>
                <div style={{width: "100%", height, background: [palette.cyan, palette.blue, palette.red][index % 3], border: `7px solid ${palette.white}`, boxShadow: `12px 12px 0 ${palette.ink}`}} />
              </div>
              <div style={{marginTop: 16, fontSize: 36, fontWeight: 950, color: palette.white}}>{years[index]}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: "absolute", left: 100, top: 500, width: 650, padding: "28px 34px", background: palette.yellow, border: `7px solid ${palette.white}`, boxShadow: `14px 14px 0 ${palette.blue}`, color: palette.ink, fontFamily: fontStack, fontSize: 56, fontWeight: 950, lineHeight: 1.08, opacity: badgeIn, transform: `translateY(${(1 - badgeIn) * 30}px) scale(${0.9 + badgeIn * 0.1}) rotate(-2deg)`}}>
        {propString(scene, "badge", "连续三年销冠\n升任区域总监")}
      </div>
    </>
  );
};
