import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {storyboard} from "../data/storyboard";
import {coverEndFrame} from "../timing/cover";
import {fontStack, glassCardBackground, palette, visualTheme} from "../theme";
import {IS_VERTICAL} from "../canvas";
import {BrandBug} from "./BrandBug";

// Mobile feeds decide in the first seconds: vertical covers use oversized
// hook type on a 920px lane so the title reads at arm's length.
const titleFontSize = (title: string) => {
  const longestLine = Math.max(...title.split("\n").map((line) => Array.from(line).length));
  if (IS_VERTICAL) {
    if (longestLine >= 19) return 68;
    if (longestLine >= 15) return 76;
    if (longestLine >= 11) return 88;
    return 100;
  }
  if (longestLine >= 19) return 60;
  if (longestLine >= 15) return 68;
  if (longestLine >= 11) return 80;
  return 96;
};

export const CoverLayer: React.FC<{proofOnly?: boolean}> = ({proofOnly = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cover = storyboard.cover;
  if (!cover) return null;

  const endFrame = coverEndFrame(fps);
  if (frame >= endFrame) return null;

  const fadeFrames = Math.min(16, Math.max(8, Math.floor(endFrame * 0.16)));
  const opacity = interpolate(
    frame,
    [Math.max(0, endFrame - fadeFrames), endFrame],
    [1, 0],
    {extrapolateLeft: "clamp", extrapolateRight: "clamp"},
  );
  const kicker = cover.kicker?.trim();
  const subtitle = cover.subtitle ?? storyboard.subtitle;
  const protectedTitle = cover.title.replace(/(\d)(?=[万千百亿元块%％年月天个])/g, "$1\u2060");

  return (
    <AbsoluteFill
      style={{
        opacity,
        overflow: "hidden",
        pointerEvents: "none",
        background: proofOnly
          ? "transparent"
          : "linear-gradient(145deg, rgba(246,239,218,0.97), rgba(237,225,196,0.94)), radial-gradient(circle at 18% 18%, rgba(239,219,86,0.28), transparent 32%), radial-gradient(circle at 82% 78%, rgba(202,77,42,0.22), transparent 36%)",
      }}
    >
      {proofOnly ? null : (
        <>
          <AbsoluteFill
            style={{
              opacity: 0.26,
              background:
                "repeating-linear-gradient(0deg, rgba(6,17,31,0.04) 0, rgba(6,17,31,0.04) 1px, transparent 1px, transparent 7px)",
            }}
          />
          <BrandBug kicker={kicker || undefined} immediate />
        </>
      )}
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
            maxWidth: IS_VERTICAL ? 920 : 960,
            padding: IS_VERTICAL ? "44px 40px 48px" : "34px 48px 38px",
            position: "relative",
            overflow: "hidden",
            borderRadius: 12,
            background: glassCardBackground,
            border: "2px solid rgba(255,255,255,0.72)",
            boxShadow:
              "14px 16px 0 rgba(5,17,31,0.28), 0 24px 54px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,255,255,0.22)",
            backdropFilter: "blur(8px)",
            color: palette.white,
            fontFamily: fontStack,
            letterSpacing: 0,
            textAlign: "center",
          }}
        >
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 0,
              height: 9,
              background: visualTheme.cardAccent,
            }}
          />
          {kicker ? (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                gap: 18,
                fontSize: IS_VERTICAL ? 32 : 28,
                fontWeight: 800,
                lineHeight: 1.2,
              }}
            >
              <div style={{width: IS_VERTICAL ? 54 : 62, height: 6, backgroundColor: palette.yellow}} />
              <div>{kicker}</div>
              <div style={{width: IS_VERTICAL ? 54 : 62, height: 6, backgroundColor: palette.yellow}} />
            </div>
          ) : null}
          <div
            style={{
              marginTop: kicker ? 22 : 4,
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
                fontSize: IS_VERTICAL ? 36 : 32,
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
