import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "remotion";
import {SPRING_SETTLE} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {fontStack, palette} from "../theme";
import {unitStartFrame} from "../timing/timeline";
import {propNumberList, propString, sceneUnitFrame, type LayoutProps} from "./shared";

export const AuthorityMatrix: React.FC<LayoutProps> = ({scene, sceneStartFrame}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const roles = propString(scene, "roles", "客户负责人|销售经理|交付负责人|区域总监").split("|");
  const tasks = propString(scene, "tasks", "客户关系与商务判断|资源与折扣边界|交付可行性否决权|只追问证据与责任人").split("|");
  const roleAtUnits = propNumberList(scene, "roleAtUnits", roles.map((_, index) => scene.units[0] + index + 1));
  const footerAt = sceneUnitFrame(scene, sceneStartFrame, "footerAtUnit", scene.units[1]);
  const footerIn = spring({frame: frame - footerAt, fps, config: SPRING_SETTLE, durationInFrames: 40});

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={92} y={142} size={78} width={1120} />
      <div style={{position: "absolute", left: 92, top: 340, display: "flex", gap: 24}}>
        {roles.map((role, index) => {
          const cardAt = unitStartFrame(roleAtUnits[index] ?? roleAtUnits[roleAtUnits.length - 1]) - sceneStartFrame;
          const cardIn = spring({frame: frame - cardAt, fps, config: SPRING_SETTLE, durationInFrames: 42});
          const color = [palette.yellow, palette.cyan, palette.white, palette.red][index % 4];
          return (
            <div key={role} style={{width: 405, height: 330, padding: 26, background: color, color: index === 3 ? palette.white : palette.ink, border: `7px solid ${palette.ink}`, boxShadow: `12px 12px 0 ${palette.blue}`, fontFamily: fontStack, opacity: cardIn, transform: `translateY(${(1 - cardIn) * 40}px) rotate(${[-2, 1, -1, 2][index]}deg)`}}>
              <div style={{fontSize: 28, fontWeight: 950, opacity: 0.75}}>决策角色 {index + 1}</div>
              <div style={{fontSize: 48, fontWeight: 950, marginTop: 18}}>{role}</div>
              <div style={{height: 7, background: palette.ink, margin: "20px 0"}} />
              <div style={{fontSize: 36, fontWeight: 900, lineHeight: 1.18}}>{tasks[index] ?? "明确责任边界"}</div>
            </div>
          );
        })}
      </div>
      <div style={{position: "absolute", left: 480, top: 715, padding: "16px 44px", background: palette.ink, border: `5px solid ${palette.white}`, color: palette.yellow, fontFamily: fontStack, fontSize: 42, fontWeight: 950, opacity: footerIn, transform: `translateY(${(1 - footerIn) * 22}px)`}}>
        {propString(scene, "footer", "谁判断，谁行动，谁承担结果")}
      </div>
    </>
  );
};
