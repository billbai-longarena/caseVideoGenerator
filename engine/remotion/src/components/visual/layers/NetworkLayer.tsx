import React from "react";
import {Img, interpolate, staticFile} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {getVisualAsset} from "../../../data/storyboard";
import {unitStartFrame} from "../../../timing/timeline";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, palette} from "../../../theme";
import {fitSingleLineFontSize, fitTextBlockFontSize} from "../../../textFit";
import {
  resolveNetworkLayout,
  type NetworkNodeBox,
} from "./networkLayout";

type Point = {x: number; y: number};

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(maximum, value));

const centerOf = (box: NetworkNodeBox): Point => ({
  x: box.x + box.width / 2,
  y: box.y + box.height / 2,
});

const edgePoint = (box: NetworkNodeBox, target: Point): Point => {
  const center = centerOf(box);
  const dx = target.x - center.x;
  const dy = target.y - center.y;
  if (Math.abs(dx) + Math.abs(dy) < 0.001) return center;
  const scale = 1 / Math.max(Math.abs(dx) / (box.width / 2), Math.abs(dy) / (box.height / 2));
  return {x: center.x + dx * scale, y: center.y + dy * scale};
};

const quadraticPoint = (start: Point, control: Point, end: Point, t: number): Point => {
  const inverse = 1 - t;
  return {
    x: inverse * inverse * start.x + 2 * inverse * t * control.x + t * t * end.x,
    y: inverse * inverse * start.y + 2 * inverse * t * control.y + t * t * end.y,
  };
};

const hasIntermediateCard = (
  fromId: string,
  toId: string,
  from: NetworkNodeBox,
  to: NetworkNodeBox,
  positions: Map<string, NetworkNodeBox>,
  axis: "row" | "column",
) => {
  const fromCenter = centerOf(from);
  const toCenter = centerOf(to);
  return [...positions.entries()].some(([id, box]) => {
    if (id === fromId || id === toId) return false;
    const center = centerOf(box);
    if (axis === "row") {
      const between = center.x > Math.min(fromCenter.x, toCenter.x) && center.x < Math.max(fromCenter.x, toCenter.x);
      return between && Math.abs(center.y - fromCenter.y) < Math.max(box.height, from.height) * 0.55;
    }
    const between = center.y > Math.min(fromCenter.y, toCenter.y) && center.y < Math.max(fromCenter.y, toCenter.y);
    return between && Math.abs(center.x - fromCenter.x) < Math.max(box.width, from.width) * 0.55;
  });
};

const linkRoute = ({
  fromId,
  toId,
  from,
  to,
  positions,
  width,
  height,
  headerHeight,
  index,
}: {
  fromId: string;
  toId: string;
  from: NetworkNodeBox;
  to: NetworkNodeBox;
  positions: Map<string, NetworkNodeBox>;
  width: number;
  height: number;
  headerHeight: number;
  index: number;
}) => {
  const fromCenter = centerOf(from);
  const toCenter = centerOf(to);
  const sameRow = Math.abs(fromCenter.y - toCenter.y) < Math.max(from.height, to.height) * 0.28;
  const sameColumn = Math.abs(fromCenter.x - toCenter.x) < Math.max(from.width, to.width) * 0.28;
  const rowObstructed = sameRow && hasIntermediateCard(fromId, toId, from, to, positions, "row");
  const columnObstructed =
    sameColumn && hasIntermediateCard(fromId, toId, from, to, positions, "column");

  if (rowObstructed) {
    const topSpace = Math.min(from.y, to.y) - headerHeight;
    const bottomSpace = height - Math.max(from.y + from.height, to.y + to.height);
    const above = topSpace >= bottomSpace;
    const control: Point = {
      x: (fromCenter.x + toCenter.x) / 2,
      y: above
        ? Math.max(headerHeight + 12, Math.min(from.y, to.y) - 54 - (index % 2) * 18)
        : Math.min(height - 12, Math.max(from.y + from.height, to.y + to.height) + 54 + (index % 2) * 18),
    };
    const start = edgePoint(from, control);
    const end = edgePoint(to, control);
    const label = quadraticPoint(start, control, end, 0.5);
    return {
      path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
      label,
    };
  }

  if (columnObstructed) {
    const leftSpace = Math.min(from.x, to.x);
    const rightSpace = width - Math.max(from.x + from.width, to.x + to.width);
    const left = leftSpace >= rightSpace;
    const control: Point = {
      x: left
        ? Math.max(12, Math.min(from.x, to.x) - 54 - (index % 2) * 18)
        : Math.min(width - 12, Math.max(from.x + from.width, to.x + to.width) + 54 + (index % 2) * 18),
      y: (fromCenter.y + toCenter.y) / 2,
    };
    const start = edgePoint(from, control);
    const end = edgePoint(to, control);
    const label = quadraticPoint(start, control, end, 0.5);
    return {
      path: `M ${start.x} ${start.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`,
      label,
    };
  }

  const start = edgePoint(from, toCenter);
  const end = edgePoint(to, fromCenter);
  const label = {x: (start.x + end.x) / 2, y: (start.y + end.y) / 2};
  if (!sameRow && !sameColumn) {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const offset = (index % 2 === 0 ? -1 : 1) * 12;
    label.x += (-dy / length) * offset;
    label.y += (dx / length) * offset;
  }
  return {path: `M ${start.x} ${start.y} L ${end.x} ${end.y}`, label};
};

// Nodes and links are storyboard data. Geometry is chosen from graph shape and
// slot aspect ratio, with an optional storyboard override for unusual beats.
export const NetworkLayer: React.FC<{
  layer: VisualLayer;
  visibility: number;
  frame: number;
  layerRevealFrame: number;
  width?: number;
  height?: number;
}> = ({layer, visibility, frame, layerRevealFrame, width = 1180, height = 620}) => {
  const nodes = layer.nodes ?? [];
  const links = layer.links ?? [];
  if (nodes.length === 0) return null;

  const layout = resolveNetworkLayout({
    nodes,
    links,
    width,
    height,
    label: layer.label,
    requested: layer.networkLayout,
  });
  const {positions, compact, headerHeight} = layout;
  const nodeReveal = (index: number) => {
    const node = nodes[index];
    return node.revealAtUnit ? unitStartFrame(node.revealAtUnit) : layerRevealFrame + index * 10;
  };
  const revealByNodeId = new Map(nodes.map((node, index) => [node.id, nodeReveal(index)]));
  const headingSize = fitSingleLineFontSize({
    text: layer.label ?? "",
    maxWidth: width - 24,
    preferred: compact ? 22 : 30,
    min: compact ? 16 : 20,
  });

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
            top: 0,
            left: 0,
            maxWidth: width - 12,
            boxSizing: "border-box",
            fontSize: headingSize,
            lineHeight: 1,
            fontWeight: 900,
            letterSpacing: compact ? 2 : 4,
            whiteSpace: "nowrap",
            color: palette.yellow,
            background: "rgba(5,17,31,0.84)",
            padding: compact ? "7px 12px" : "9px 18px",
            zIndex: 4,
          }}
        >
          {layer.label}
        </div>
      ) : null}
      <svg width={width} height={height} style={{position: "absolute", inset: 0, zIndex: 1}}>
        {links.map((link, index) => {
          const from = positions.get(link.from);
          const to = positions.get(link.to);
          if (!from || !to) return null;
          const startFrame = link.revealAtUnit
            ? unitStartFrame(link.revealAtUnit)
            : Math.max(revealByNodeId.get(link.from) ?? 0, revealByNodeId.get(link.to) ?? 0) + 8;
          const draw = interpolate(frame, [startFrame, startFrame + 18], [0, 1], {
            easing: EASE_OUT,
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          });
          if (draw <= 0) return null;
          const route = linkRoute({
            fromId: link.from,
            toId: link.to,
            from,
            to,
            positions,
            width,
            height,
            headerHeight,
            index,
          });
          const labelText = link.label ?? "";
          const labelWidth = clamp(
            Array.from(labelText).length * (compact ? 19 : 24) + (compact ? 22 : 30),
            compact ? 76 : 104,
            compact ? 148 : 192,
          );
          const labelHeight = compact ? 36 : 48;
          const labelX = clamp(route.label.x, labelWidth / 2 + 4, width - labelWidth / 2 - 4);
          const labelY = clamp(
            route.label.y,
            Math.max(headerHeight + labelHeight / 2 + 4, labelHeight / 2 + 4),
            height - labelHeight / 2 - 4,
          );
          const labelSize = fitSingleLineFontSize({
            text: labelText,
            maxWidth: labelWidth - (compact ? 14 : 20),
            preferred: compact ? 19 : 25,
            min: compact ? 14 : 17,
          });
          return (
            <g key={`link-${index}`}>
              <path
                d={route.path}
                pathLength={1}
                fill="none"
                stroke={palette.cyan}
                strokeWidth={compact ? 4 : 5}
                strokeDasharray={1}
                strokeDashoffset={1 - draw}
                opacity={0.9}
              />
              {link.label && draw >= 1 ? (
                <g>
                  <rect
                    x={labelX - labelWidth / 2}
                    y={labelY - labelHeight / 2}
                    width={labelWidth}
                    height={labelHeight}
                    fill="rgba(5,17,31,0.94)"
                    stroke={palette.cyan}
                    strokeWidth={2}
                  />
                  <text
                    x={labelX}
                    y={labelY + labelSize * 0.36}
                    textAnchor="middle"
                    fill={palette.white}
                    fontSize={labelSize}
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
        const box = positions.get(node.id);
        if (!box) return null;
        const startFrame = nodeReveal(index);
        const pop = interpolate(frame, [startFrame, startFrame + 14], [0, 1], {
          easing: EASE_OUT,
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        if (pop <= 0) return null;
        const assetSrc = node.asset ? getVisualAsset(node.asset).src : null;
        const assetSize = clamp(
          Math.min(box.height - (compact ? 18 : 24), box.width * 0.28, compact ? 58 : 90),
          38,
          compact ? 58 : 90,
        );
        const labelWidth = box.width - (assetSrc ? assetSize + (compact ? 32 : 50) : compact ? 24 : 36);
        const labelSize = fitTextBlockFontSize({
          text: node.label,
          maxWidth: Math.max(70, labelWidth),
          maxLines: 2,
          preferred: compact ? 27 : 40,
          min: compact ? 16 : 21,
        });
        const subSize = node.sub
          ? fitSingleLineFontSize({
              text: node.sub,
              maxWidth: Math.max(70, labelWidth),
              preferred: compact ? 16 : 23,
              min: compact ? 12 : 15,
            })
          : 0;
        return (
          <div
            key={node.id}
            style={{
              position: "absolute",
              left: box.x,
              top: box.y,
              width: box.width,
              height: box.height,
              display: "flex",
              alignItems: "center",
              gap: compact ? 10 : 16,
              padding: compact ? "8px 12px" : "14px 20px",
              boxSizing: "border-box",
              background: node.emphasis ? "rgba(11,98,214,0.92)" : "rgba(5,17,31,0.9)",
              border: node.emphasis
                ? `${compact ? 4 : 5}px solid ${palette.yellow}`
                : `${compact ? 2 : 3}px solid rgba(255,255,255,0.66)`,
              boxShadow: compact ? "5px 6px 0 rgba(5,17,31,0.58)" : "10px 10px 0 rgba(5,17,31,0.6)",
              opacity: pop,
              transform: `scale(${0.9 + pop * 0.1})`,
              transformOrigin: "center",
              zIndex: 2,
            }}
          >
            {assetSrc ? (
              <Img
                src={staticFile(assetSrc)}
                style={{
                  width: assetSize,
                  height: assetSize,
                  objectFit: "cover",
                  border: `${compact ? 2 : 3}px solid rgba(255,255,255,0.85)`,
                  flexShrink: 0,
                }}
              />
            ) : null}
            <div style={{minWidth: 0, flex: 1}}>
              <div
                style={{
                  fontSize: labelSize,
                  fontWeight: 950,
                  color: palette.white,
                  lineHeight: 1.08,
                  overflowWrap: "anywhere",
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                  overflow: "hidden",
                }}
              >
                {node.label}
              </div>
              {node.sub ? (
                <div
                  style={{
                    fontSize: subSize,
                    fontWeight: 700,
                    color: node.emphasis ? "rgba(255,255,255,0.92)" : "rgba(255,255,255,0.72)",
                    marginTop: compact ? 3 : 6,
                    lineHeight: 1.18,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
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
