import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {SPRING_POP, SPRING_SETTLE} from "../anim/springs";
import {HeadlineReveal} from "../components/HeadlineReveal";
import {fontStack, palette} from "../theme";
import {unitStartFrame} from "../timing/timeline";
import {propNumberList, propString, sceneUnitFrame, type LayoutProps} from "./shared";

const positions = [[1020, 200], [1430, 280], [1430, 560], [1020, 640]];

export const DecisionBottleneck: React.FC<LayoutProps> = ({scene, sceneStartFrame, duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const nodes = propString(scene, "nodes", "客户负责人|销售经理|交付负责人|一线销售").split("|");
  const nodeAtUnits = propNumberList(scene, "nodeAtUnits", nodes.map((_, index) => scene.units[0] + index + 1));
  const centerAt = sceneUnitFrame(scene, sceneStartFrame, "centerAtUnit", scene.units[0]);
  const warningAt = sceneUnitFrame(scene, sceneStartFrame, "warningAtUnit", scene.units[1]);
  const centerIn = spring({frame: frame - centerAt, fps, config: SPRING_POP, durationInFrames: 40});
  const warningIn = spring({frame: frame - warningAt, fps, config: SPRING_SETTLE, durationInFrames: 40});
  const pulse = interpolate(frame, [20, duration / 2, duration - 10], [0.92, 1.05, 0.96], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});

  return (
    <>
      <HeadlineReveal headline={scene.headline} x={92} y={150} size={78} width={790} />
      <div style={{position: "absolute", left: 760, top: 440, width: 250, height: 250, borderRadius: "50%", background: palette.red, border: `9px solid ${palette.white}`, boxShadow: `16px 16px 0 ${palette.ink}`, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", color: palette.white, fontFamily: fontStack, fontSize: 54, fontWeight: 950, lineHeight: 1.05, opacity: centerIn, transform: `scale(${centerIn * pulse})`, zIndex: 2}}>
        {propString(scene, "center", "周锐\n亲自拍板")}
      </div>
      {nodes.map((node, index) => {
        const [left, top] = positions[index] ?? positions[positions.length - 1];
        const nodeAt = unitStartFrame(nodeAtUnits[index] ?? nodeAtUnits[nodeAtUnits.length - 1]) - sceneStartFrame;
        const nodeIn = spring({frame: frame - nodeAt, fps, config: SPRING_SETTLE, durationInFrames: 38});
        const centerX = 885;
        const centerY = 565;
        const nodeX = left + 130;
        const nodeY = top + 55;
        const distance = Math.hypot(nodeX - centerX, nodeY - centerY);
        const angle = Math.atan2(nodeY - centerY, nodeX - centerX) * 180 / Math.PI;
        return (
          <React.Fragment key={node}>
            <div style={{position: "absolute", left: centerX, top: centerY, width: distance, height: 8, background: palette.yellow, transformOrigin: "left center", transform: `rotate(${angle}deg) scaleX(${nodeIn})`, border: `2px solid ${palette.ink}`}} />
            <div style={{position: "absolute", left, top, width: 260, padding: "20px 16px", background: index % 2 ? palette.cyan : palette.white, border: `6px solid ${palette.ink}`, boxShadow: `10px 10px 0 ${palette.blue}`, color: palette.ink, textAlign: "center", fontFamily: fontStack, fontSize: 36, fontWeight: 950, opacity: nodeIn, transform: `scale(${0.82 + nodeIn * 0.18})`, zIndex: 2}}>{node}</div>
          </React.Fragment>
        );
      })}
      <div style={{position: "absolute", left: 96, top: 530, width: 560, color: palette.yellow, fontFamily: fontStack, fontSize: 52, fontWeight: 950, lineHeight: 1.12, WebkitTextStroke: `2px ${palette.ink}`, textShadow: `8px 8px 0 ${palette.blue}`, opacity: warningIn, transform: `translateY(${(1 - warningIn) * 26}px)`}}>
        {propString(scene, "warning", "所有问题都向一个人汇集\n团队判断力开始萎缩")}
      </div>
    </>
  );
};
