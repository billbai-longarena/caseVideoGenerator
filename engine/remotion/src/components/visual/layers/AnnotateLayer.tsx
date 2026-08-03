import React from "react";
import {interpolate} from "remotion";
import type {VisualLayer} from "../../../data/types";
import {EASE_OUT} from "../../../anim/springs";
import {fontStack, palette} from "../../../theme";
import {CANVAS_HEIGHT, CANVAS_WIDTH} from "../../../canvas";

// Directional evidence annotation drawn over the beat's base image. `region`
// is relative (0-1) to the full canvas so plans stay resolution-independent.
export const AnnotateLayer: React.FC<{
  layer: VisualLayer;
  visibility: number;
  localFrame: number;
}> = ({layer, visibility, localFrame}) => {
  const shape = layer.shape as string | undefined;
  if (shape !== "arrow" && shape !== "underline") return null;
  const region = layer.region;
  if (!region) return null;
  const draw = interpolate(localFrame, [2, 22], [0, 1], {
    easing: EASE_OUT,
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const color = layer.color ?? palette.yellow;
  const W = CANVAS_WIDTH;
  const H = CANVAS_HEIGHT;
  const x = region.x * W;
  const y = region.y * H;
  const w = region.w * W;
  const h = region.h * H;

  return (
    <div style={{position: "absolute", inset: 0, opacity: visibility, pointerEvents: "none"}}>
      <svg width={W} height={H} style={{position: "absolute", inset: 0}}>
        {shape === "underline" ? (
          <line
            x1={x}
            y1={y + h}
            x2={x + w * draw}
            y2={y + h}
            stroke={color}
            strokeWidth={9}
            strokeLinecap="round"
          />
        ) : null}
        {shape === "arrow" ? (
          (() => {
            const tipX = x + w / 2;
            const tipY = y + h;
            const startY = tipY - Math.max(120, h);
            const lineY = startY + (tipY - startY) * draw;
            return (
              <g>
                <line
                  x1={tipX}
                  y1={startY}
                  x2={tipX}
                  y2={lineY - 26}
                  stroke={color}
                  strokeWidth={10}
                  strokeLinecap="round"
                />
                {draw > 0.85 ? (
                  <polygon
                    points={`${tipX - 24},${tipY - 34} ${tipX + 24},${tipY - 34} ${tipX},${tipY}`}
                    fill={color}
                  />
                ) : null}
              </g>
            );
          })()
        ) : null}
      </svg>
      {layer.text && draw >= 1 ? (
        <div
          style={{
            position: "absolute",
            left: x,
            top: shape === "arrow" ? Math.max(20, y - Math.max(120, h) - 76) : y + h + 18,
            background: "rgba(5,17,31,0.88)",
            border: `3px solid ${color}`,
            color: palette.white,
            fontFamily: fontStack,
            fontSize: 34,
            fontWeight: 900,
            padding: "10px 22px",
            boxShadow: "8px 8px 0 rgba(5,17,31,0.55)",
            whiteSpace: "pre-line",
          }}
        >
          {layer.text}
        </div>
      ) : null}
    </div>
  );
};
