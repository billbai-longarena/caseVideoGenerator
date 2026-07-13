import React from "react";
import {Img, interpolate, staticFile} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {getVisualAsset} from "../../../data/storyboard";
import {unitStartFrame} from "../../../timing/timeline";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, palette} from "../../../theme";

const NODE_W = 340;
const NODE_H = 150;

// Node/link diagram for decision networks. Layout is deterministic: nodes are
// placed on a horizontal rail (2 nodes) or a triangle (3+), links draw with a
// stroke-dash sweep once both endpoints are visible.
const nodePosition = (index: number, total: number, width: number, height: number) => {
  if (total <= 2) {
    const y = height / 2 - NODE_H / 2;
    const gap = width - NODE_W * 2 - 120;
    return {x: 60 + index * (NODE_W + gap + 120 - 60), y};
  }
  if (index === 0) return {x: width / 2 - NODE_W / 2, y: 30};
  const bottomTotal = total - 1;
  const slot = width / bottomTotal;
  return {
    x: slot * (index - 1) + slot / 2 - NODE_W / 2,
    y: height - NODE_H - 40,
  };
};

export const NetworkLayer: React.FC<{
  layer: VisualLayer;
  visibility: number;
  frame: number;
  layerRevealFrame: number;
}> = ({layer, visibility, frame, layerRevealFrame}) => {
  const nodes = layer.nodes ?? [];
  const links = layer.links ?? [];
  if (nodes.length === 0) return null;

  const width = 1180;
  const height = 620;
  const positions = new Map(
    nodes.map((node, index) => [node.id, nodePosition(index, nodes.length, width, height)]),
  );
  const nodeReveal = (index: number) => {
    const node = nodes[index];
    return node.revealAtUnit ? unitStartFrame(node.revealAtUnit) : layerRevealFrame + index * 10;
  };
  const revealByNodeId = new Map(nodes.map((node, index) => [node.id, nodeReveal(index)]));

  return (
    <div
      style={{
        position: "relative",
        width,
        height,
        opacity: visibility,
        transform: `translateY(${(1 - visibility) * 20}px)`,
        fontFamily: fontStack,
      }}
    >
      {layer.label ? (
        <div
          style={{
            position: "absolute",
            top: -6,
            left: 0,
            fontSize: 30,
            fontWeight: 900,
            letterSpacing: 4,
            color: palette.yellow,
            background: "rgba(5,17,31,0.8)",
            padding: "8px 18px",
            zIndex: 3,
          }}
        >
          {layer.label}
        </div>
      ) : null}
      <svg
        width={width}
        height={height}
        style={{position: "absolute", inset: 0, zIndex: 1}}
      >
        {links.map((link, index) => {
          const from = positions.get(link.from);
          const to = positions.get(link.to);
          if (!from || !to) return null;
          const start = link.revealAtUnit
            ? unitStartFrame(link.revealAtUnit)
            : Math.max(revealByNodeId.get(link.from) ?? 0, revealByNodeId.get(link.to) ?? 0) + 8;
          const draw = interpolate(frame, [start, start + 18], [0, 1], {
            easing: EASE_OUT,
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          if (draw <= 0) return null;
          const x1 = from.x + NODE_W / 2;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x + NODE_W / 2;
          const y2 = to.y + NODE_H / 2;
          const length = Math.hypot(x2 - x1, y2 - y1);
          const midX = (x1 + x2) / 2;
          const midY = (y1 + y2) / 2;
          return (
            <g key={`link-${index}`}>
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={palette.cyan}
                strokeWidth={5}
                strokeDasharray={length}
                strokeDashoffset={length * (1 - draw)}
                opacity={0.9}
              />
              {link.label && draw >= 1 ? (
                <g>
                  <rect
                    x={midX - 90}
                    y={midY - 26}
                    width={180}
                    height={52}
                    fill="rgba(5,17,31,0.92)"
                    stroke={palette.cyan}
                    strokeWidth={2}
                  />
                  <text
                    x={midX}
                    y={midY + 10}
                    textAnchor="middle"
                    fill={palette.white}
                    fontSize={26}
                    fontWeight={800}
                    fontFamily={fontStack}
                  >
                    {link.label}
                  </text>
                </g>
              ) : null}
            </g>
          );
        })}
      </svg>
      {nodes.map((node, index) => {
        const pos = positions.get(node.id);
        if (!pos) return null;
        const start = nodeReveal(index);
        const pop = interpolate(frame, [start, start + 14], [0, 1], {
          easing: EASE_OUT,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        if (pop <= 0) return null;
        const assetSrc = node.asset ? getVisualAsset(node.asset).src : null;
        return (
          <div
            key={node.id}
            style={{
              position: "absolute",
              left: pos.x,
              top: pos.y,
              width: NODE_W,
              height: NODE_H,
              display: "flex",
              alignItems: "center",
              gap: 16,
              padding: "14px 20px",
              boxSizing: "border-box",
              background: node.emphasis ? "rgba(11,98,214,0.9)" : "rgba(5,17,31,0.88)",
              border: node.emphasis
                ? `5px solid ${palette.yellow}`
                : "3px solid rgba(255,255,255,0.6)",
              boxShadow: "10px 10px 0 rgba(5,17,31,0.6)",
              opacity: pop,
              transform: `scale(${0.9 + pop * 0.1})`,
              zIndex: 2,
            }}
          >
            {assetSrc ? (
              <Img
                src={staticFile(assetSrc)}
                style={{
                  width: 96,
                  height: 96,
                  objectFit: "cover",
                  border: "3px solid rgba(255,255,255,0.85)",
                  flexShrink: 0,
                }}
              />
            ) : null}
            <div style={{minWidth: 0}}>
              <div
                style={{
                  fontSize: 40,
                  fontWeight: 950,
                  color: palette.white,
                  lineHeight: 1.1,
                  whiteSpace: "nowrap",
                }}
              >
                {node.label}
              </div>
              {node.sub ? (
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 700,
                    color: node.emphasis ? "rgba(255,255,255,0.92)" : "rgba(255,255,255,0.7)",
                    marginTop: 6,
                    lineHeight: 1.25,
                  }}
                >
                  {node.sub}
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};
