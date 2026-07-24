import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import {storyboard} from "../data/storyboard";
import {unitEndFrame} from "../timing/timeline";
import {fontStack, palette} from "../theme";

const titleFontSize = (title: string) => {
  const longestLine = Math.max(...title.split("\n").map((line) => Array.from(line).length));
  if (longestLine >= 19) return 60;
  if (longestLine >= 15) return 68;
  if (longestLine >= 11) return 80;
  return 96;
};

export const CoverLayer: React.FC = () => {
  const frame = useCurrentFrame();
  const cover = storyboard.cover;
  if (!cover) return null;

  const endFrame = Math.max(1, unitEndFrame(cover.throughUnit, true));
  if (frame >= endFrame) return null;

  const fadeFrames = Math.min(16, Math.max(8, Math.floor(endFrame * 0.16)));
  const opacity = interpolate(
    frame,
    [Math.max(0, endFrame - fadeFrames), endFrame],
    [1, 0],
    {extrapolateLeft: "clamp", extrapolateRight: "clamp"},
  );
  const kicker = cover.kicker ?? storyboard.brand;
  const subtitle = cover.subtitle ?? storyboard.subtitle;
  const protectedTitle = cover.title.replace(/(\d)(?=[万千百亿元块%％年月天个])/g, "$1\u2060");

  return (
    <AbsoluteFill style={{opacity, overflow: "hidden", pointerEvents: "none"}}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          padding: "72px 0",
        }}
      >
        <div
          style={{
            boxSizing: "border-box",
            width: "fit-content",
            maxWidth: 960,
            padding: "34px 48px 38px",
            borderRadius: 28,
            backgroundColor: "rgba(3, 12, 24, 0.62)",
            boxShadow: "0 10px 24px rgba(0, 0, 0, 0.2)",
            backdropFilter: "blur(5px)",
            color: palette.white,
            fontFamily: fontStack,
            letterSpacing: 0,
            textAlign: "center",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: 18,
              fontSize: 28,
              fontWeight: 800,
              lineHeight: 1.2,
            }}
          >
            <div style={{width: 62, height: 6, backgroundColor: palette.yellow}} />
            <div>{kicker}</div>
            <div style={{width: 62, height: 6, backgroundColor: palette.yellow}} />
          </div>
          <div
            style={{
              marginTop: 22,
              fontSize: titleFontSize(cover.title),
              fontWeight: 950,
              lineHeight: 1.1,
              whiteSpace: "pre-line",
              overflowWrap: "anywhere",
              textShadow: "0 8px 28px rgba(0, 0, 0, 0.34)",
            }}
          >
            {protectedTitle}
          </div>
          {subtitle ? (
            <div
              style={{
                marginTop: 24,
                color: "rgba(255, 255, 255, 0.88)",
                fontSize: 32,
                fontWeight: 650,
                lineHeight: 1.35,
                whiteSpace: "pre-line",
              }}
            >
              {subtitle}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
