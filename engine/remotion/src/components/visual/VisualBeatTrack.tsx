import React from "react";
import {
  AbsoluteFill,
  Img,
  Video,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import {getVisualAsset} from "../../data/storyboard";
import type {
  VisualAsset,
  VisualBeat,
  VisualBeatCamera,
  VisualBeatComposition,
  VisualBeatPurpose,
  VisualBeatTreatment,
  VisualLayer,
  VisualLayerSlot,
} from "../../data/types";
import {resolvedVisualBeats, unitStartFrame} from "../../timing/timeline";
import {clamp, fontStack, palette, visualTheme} from "../../theme";
import {idleFloat} from "../../anim/springs";
import {CounterLayer} from "./layers/CounterLayer";
import {BarCompareLayer} from "./layers/BarCompareLayer";
import {NetworkLayer} from "./layers/NetworkLayer";
import {DialogueLayer} from "./layers/DialogueLayer";
import {AnnotateLayer} from "./layers/AnnotateLayer";

const beats = resolvedVisualBeats();

// Purpose-driven rendering defaults. Every beat already declares WHY it exists;
// these presets make that intent visible without per-beat hand tuning.
type PurposePreset = {
  cameraScale: number;
  vignette: number;
  layerStagger: number;
  emphasisScale: number;
  pulse?: boolean;
  flashback?: boolean;
};

const PURPOSE_PRESETS: Record<VisualBeatPurpose, PurposePreset> = {
  establish: {cameraScale: 1, vignette: 0, layerStagger: 6, emphasisScale: 1},
  identify: {cameraScale: 0.9, vignette: 0.07, layerStagger: 7, emphasisScale: 1},
  evidence: {cameraScale: 1.5, vignette: 0.16, layerStagger: 4, emphasisScale: 1.04},
  explain: {cameraScale: 0.9, vignette: 0.04, layerStagger: 6, emphasisScale: 1},
  escalate: {cameraScale: 1.6, vignette: 0.14, layerStagger: 4, emphasisScale: 1.03, pulse: true},
  consequence: {cameraScale: 1.2, vignette: 0.1, layerStagger: 5, emphasisScale: 1.08},
  callback: {cameraScale: 0.7, vignette: 0.07, layerStagger: 6, emphasisScale: 1, flashback: true},
  reset: {cameraScale: 0.6, vignette: 0, layerStagger: 8, emphasisScale: 1},
};

const presetFor = (beat: VisualBeat): PurposePreset => PURPOSE_PRESETS[beat.purpose];

const isThreeColumnSlot = (slot: VisualLayerSlot = "canvas") =>
  slot === "left" || slot === "center" || slot === "right";

const slotStyle = (
  slot: VisualLayerSlot = "canvas",
  composition?: VisualBeatComposition,
  reserveBottom = false,
): React.CSSProperties => {
  const common: React.CSSProperties = {position: "absolute"};
  if (composition === "triptych" && isThreeColumnSlot(slot)) {
    const bottom = reserveBottom ? 386 : 244;
    if (slot === "left") return {...common, left: 80, top: 232, width: 515, bottom};
    if (slot === "center") return {...common, left: 702, top: 232, width: 515, bottom};
    return {...common, right: 80, top: 232, width: 515, bottom};
  }
  switch (slot) {
    case "left":
      return {...common, left: 78, top: 172, width: 720, bottom: reserveBottom ? 380 : 206};
    case "right":
      return {...common, right: 78, top: 172, width: 720, bottom: reserveBottom ? 380 : 206};
    case "center":
      return {...common, left: 430, right: 430, top: 190, bottom: reserveBottom ? 380 : 214};
    case "inset-left":
      return {...common, left: 92, top: 264, width: 520, height: 430};
    case "inset-right":
      return {...common, right: 92, top: 264, width: 520, height: 430};
    case "top-left":
      return {...common, left: 92, top: 178, width: 690, minHeight: 180};
    case "top-right":
      return {...common, right: 92, top: 178, width: 690, minHeight: 180};
    case "bottom":
      return {...common, left: 180, right: 180, bottom: 206, minHeight: 150};
    case "canvas":
    default:
      return {...common, inset: 0};
  }
};

const slotDimensions = (
  slot: VisualLayerSlot = "canvas",
  composition?: VisualBeatComposition,
  reserveBottom = false,
) => {
  if (composition === "triptych" && isThreeColumnSlot(slot)) {
    return {width: 515, height: 1080 - 232 - (reserveBottom ? 386 : 244)};
  }
  if (slot === "left" || slot === "right") {
    return {width: 720, height: 1080 - 172 - (reserveBottom ? 380 : 206)};
  }
  if (slot === "center") {
    return {width: 1060, height: 1080 - 190 - (reserveBottom ? 380 : 214)};
  }
  if (slot === "inset-left" || slot === "inset-right") return {width: 520, height: 430};
  if (slot === "top-left" || slot === "top-right") return {width: 690, height: 220};
  if (slot === "bottom") return {width: 1560, height: 180};
  return {width: 1920, height: 1080};
};

const reservesBottomLane = (layers: VisualLayer[]) =>
  layers.some((layer) => layer.slot === "bottom" && layer.kind !== "tint");

const treatmentTint = (treatment: VisualBeatTreatment = "natural") => {
  // Full-frame CSS filters are prohibitively expensive in Remotion's
  // software-rendered Chrome. Lightweight color plates retain the intended
  // mood while keeping long-form renders practical.
  if (treatment === "desaturated") return "rgba(8,24,39,0.20)";
  if (treatment === "blueprint") {
    return visualTheme.preserveBlueYellow
      ? "rgba(18,80,140,0.12)"
      : "rgba(12,58,112,0.22)";
  }
  if (treatment === "crisis") {
    return visualTheme.preserveBlueYellow
      ? "rgba(78,25,18,0.12)"
      : "rgba(38,12,10,0.24)";
  }
  return "transparent";
};

const cameraTransform = (
  camera: VisualBeatCamera = "static",
  frame: number,
  duration: number,
  intensity = 1,
) => {
  const progress = clamp(frame / Math.max(1, duration), 0, 1);
  const push = 0.075 * intensity;
  const pan = 56 * intensity;
  if (camera === "push-in") return `scale(${1.015 + progress * push})`;
  if (camera === "pull-out") return `scale(${1.015 + push - progress * push})`;
  if (camera === "pan-left") return `translateX(${pan / 2 - progress * pan}px) scale(1.08)`;
  if (camera === "pan-right") return `translateX(${-pan / 2 + progress * pan}px) scale(1.08)`;
  if (camera === "drift") {
    const driftIntensity = clamp(intensity, 0.7, 1.1);
    const driftX = Math.sin(progress * Math.PI * 1.12) * 16 * driftIntensity;
    const driftY = Math.cos(progress * Math.PI * 0.86) * 8 * driftIntensity - 4;
    const zoom = 1.035 + Math.sin(progress * Math.PI) * 0.018 * driftIntensity;
    return `translate3d(${driftX}px, ${driftY}px, 0) scale(${zoom})`;
  }
  if (camera === "breathe") {
    const breatheIntensity = clamp(intensity, 0.7, 1.15);
    const zoom = 1.025 + Math.sin(progress * Math.PI) * 0.024 * breatheIntensity;
    return `scale(${zoom})`;
  }
  return "scale(1.025)";
};

const compositionStyle = (composition: VisualBeatComposition): React.CSSProperties => {
  const common: React.CSSProperties = {
    position: "absolute",
    overflow: "hidden",
  };
  if (composition === "portrait-left") {
    return {...common, left: 0, top: 0, bottom: 0, width: "64%"};
  }
  if (composition === "portrait-right") {
    return {...common, right: 0, top: 0, bottom: 0, width: "64%"};
  }
  if (composition === "split") {
    return {...common, right: 0, top: 0, bottom: 0, width: "59%"};
  }
  if (composition === "triptych") {
    return {
      ...common,
      left: 610,
      right: 610,
      top: 158,
      bottom: 202,
      border: `4px solid ${palette.white}`,
      boxShadow: `14px 14px 0 rgba(5,17,31,0.64)`,
    };
  }
  if (composition === "document-focus") {
    return {
      ...common,
      left: 330,
      right: 330,
      top: 148,
      bottom: 198,
      border: `8px solid rgba(249,251,255,0.94)`,
      boxShadow: `18px 20px 0 rgba(5,17,31,0.72)`,
      backgroundColor: "rgba(246,239,218,0.92)",
    };
  }
  if (composition === "evidence-collage") {
    return {
      ...common,
      right: 72,
      top: 154,
      width: 1110,
      bottom: 202,
      border: `5px solid rgba(249,251,255,0.9)`,
      boxShadow: `16px 16px 0 rgba(5,17,31,0.66)`,
    };
  }
  return {...common, inset: 0};
};

const needsAmbientBase = (composition: VisualBeatComposition) => composition !== "full-bleed";

const replacementRegion = (slot: VisualLayerSlot = "canvas") => {
  if (slot === "left" || slot === "top-left" || slot === "inset-left") return "left";
  if (slot === "right" || slot === "top-right" || slot === "inset-right") return "right";
  return slot;
};

const AssetMedia: React.FC<{
  asset: VisualAsset;
  style?: React.CSSProperties;
  fit?: "cover" | "contain";
}> = ({asset, style, fit = "cover"}) => {
  const mediaStyle: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: fit,
    ...style,
  };
  if (asset.type === "video") {
    return <Video src={staticFile(asset.src)} muted loop style={mediaStyle} />;
  }
  return <Img src={staticFile(asset.src)} style={mediaStyle} />;
};

// Layer reveal frame including the purpose-driven per-index stagger, so
// several layers revealed on the same unit still enter as a cascade.
const layerRevealFrame = (layer: VisualLayer, beat: VisualBeat, layerIndex: number) => {
  const stagger = layer.revealAtUnit ? 0 : layerIndex * presetFor(beat).layerStagger;
  return unitStartFrame(layer.revealAtUnit ?? beat.atUnit) + stagger;
};

const layerVisibility = (
  layer: VisualLayer,
  beat: VisualBeat,
  frame: number,
  layerIndex: number,
  layers: VisualLayer[],
) => {
  const revealFrame = layerRevealFrame(layer, beat, layerIndex);
  const enter = interpolate(frame, [revealFrame, revealFrame + 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const explicitExitFrame = layer.exitAtUnit ? unitStartFrame(layer.exitAtUnit) : null;
  const autoExitFrame =
    layer.kind === "text"
      ? layers
          .map((candidate, candidateIndex) => ({candidate, candidateIndex}))
          .find(
            ({candidate, candidateIndex}) =>
              candidateIndex > layerIndex &&
              candidate.kind === "text" &&
              candidate.revealAtUnit !== undefined &&
              replacementRegion(candidate.slot) === replacementRegion(layer.slot) &&
              layerRevealFrame(candidate, beat, candidateIndex) > revealFrame,
          )
      : null;
  const exitFrame = explicitExitFrame ?? (autoExitFrame ? layerRevealFrame(autoExitFrame.candidate, beat, autoExitFrame.candidateIndex) : null);
  if (!exitFrame) return enter;
  const exit = interpolate(frame, [exitFrame - 7, exitFrame], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return Math.min(enter, exit);
};

const TextLayer: React.FC<{
  layer: VisualLayer;
  beat: VisualBeat;
  frame: number;
  visibility: number;
  revealFrame: number;
  reserveBottom: boolean;
}> = ({layer, beat, frame, visibility, revealFrame, reserveBottom}) => {
  const variant = layer.variant ?? "caption";
  const isMetric = variant === "metric";
  const isStamp = variant === "stamp";
  const isHeadline = variant === "headline";
  const fromRight = layer.slot?.includes("right") ?? false;
  const isTriptychText = beat.composition === "triptych" && isThreeColumnSlot(layer.slot);
  const text = layer.text ?? "";
  const textLines = text.split("\n");
  const longestLine = Math.max(1, ...textLines.map((line) => [...line.trim()].length));
  const maxTextSize = isMetric ? 94 : isHeadline ? (isTriptychText ? 43 : 58) : isStamp ? 54 : variant === "quote" ? 43 : 36;
  const textFontSize = isMetric
    ? maxTextSize
    : clamp(maxTextSize - Math.max(0, longestLine - 7) * 2.2 - Math.max(0, textLines.length - 2) * 3, 30, maxTextSize);
  const slideX = (1 - visibility) * (fromRight ? 34 : -34);
  const float = idleFloat(frame, revealFrame + 12);
  const emphasis = presetFor(beat).emphasisScale;
  const scaleTarget = isMetric || isStamp ? emphasis : 1;
  return (
    <div
      style={{
        ...slotStyle(layer.slot, beat.composition, reserveBottom),
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: layer.slot === "right" || layer.slot === "top-right" ? "flex-end" : "flex-start",
        boxSizing: "border-box",
        padding: isMetric ? "30px 38px" : "24px 30px",
        opacity: visibility,
        transform: `translate(${slideX}px, ${(1 - visibility) * 20 + float}px) scale(${
          0.97 + visibility * (0.03 * scaleTarget + (scaleTarget - 1))
        })`,
        transformOrigin: layer.slot?.includes("right") ? "right center" : "left center",
        color: palette.white,
        fontFamily: fontStack,
        textAlign: layer.slot?.includes("right") ? "right" : "left",
        background: isStamp
          ? "rgba(5,17,31,0.72)"
          : isHeadline
            ? "linear-gradient(90deg, rgba(5,17,31,0.9), rgba(5,17,31,0.34))"
            : "rgba(5,17,31,0.76)",
        border: isStamp
          ? `5px solid ${palette.yellow}`
          : `2px solid rgba(255,255,255,0.5)`,
        boxShadow: isStamp ? `10px 10px 0 ${palette.ink}` : "10px 12px 30px rgba(0,0,0,0.34)",
        overflow: "hidden",
        maxWidth: "100%",
      }}
    >
      {layer.label ? (
        <div
          style={{
            fontSize: isMetric ? 28 : 23,
            lineHeight: 1.2,
            fontWeight: 800,
            letterSpacing: 2,
            color: isMetric || isStamp ? palette.yellow : "rgba(255,255,255,0.76)",
            marginBottom: 10,
          }}
        >
          {layer.label}
        </div>
      ) : null}
      <div
        style={{
          fontSize: textFontSize,
          lineHeight: isMetric ? 0.98 : 1.18,
          fontWeight: isMetric || isHeadline || isStamp ? 950 : 800,
          color: isMetric ? palette.yellow : palette.white,
          whiteSpace: "pre-line",
          overflowWrap: "anywhere",
          textShadow: "0 4px 0 rgba(0,0,0,0.52)",
        }}
      >
        {layer.text}
      </div>
    </div>
  );
};

// Wraps data-driven layers (counter/bar/network/dialogue) in their slot box.
const SlotWrap: React.FC<{
  layer: VisualLayer;
  composition: VisualBeatComposition;
  reserveBottom: boolean;
  children: React.ReactNode;
}> = ({layer, composition, reserveBottom, children}) => (
  <div
    style={{
      ...slotStyle(layer.slot, composition, reserveBottom),
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      alignItems: layer.slot === "right" || layer.slot === "top-right" ? "flex-end" : "flex-start",
      boxSizing: "border-box",
      minWidth: 0,
      minHeight: 0,
    }}
  >
    {children}
  </div>
);

const VisualLayerView: React.FC<{
  layer: VisualLayer;
  beat: VisualBeat;
  frame: number;
  layerIndex: number;
  layers: VisualLayer[];
}> = ({layer, beat, frame, layerIndex, layers}) => {
  const visibility = layerVisibility(layer, beat, frame, layerIndex, layers);
  if (visibility <= 0) return null;
  const revealFrame = layerRevealFrame(layer, beat, layerIndex);
  const localFrame = Math.max(0, frame - revealFrame);
  const reserveBottom = reservesBottomLane(layers);

  if (layer.kind === "text") {
    return (
      <TextLayer
        layer={layer}
        beat={beat}
        frame={frame}
        visibility={visibility}
        revealFrame={revealFrame}
        reserveBottom={reserveBottom}
      />
    );
  }
  if (layer.kind === "tint") {
    return (
      <div
        style={{
          ...slotStyle(layer.slot, beat.composition, reserveBottom),
          backgroundColor: layer.color,
          opacity: (layer.opacity ?? 0.25) * visibility,
        }}
      />
    );
  }
  if (layer.kind === "counter") {
    return (
      <SlotWrap layer={layer} composition={beat.composition} reserveBottom={reserveBottom}>
        <CounterLayer layer={layer} visibility={visibility} localFrame={localFrame} />
      </SlotWrap>
    );
  }
  if (layer.kind === "bar-compare") {
    return (
      <SlotWrap layer={layer} composition={beat.composition} reserveBottom={reserveBottom}>
        <BarCompareLayer
          layer={layer}
          visibility={visibility}
          frame={frame}
          layerRevealFrame={revealFrame}
        />
      </SlotWrap>
    );
  }
  if (layer.kind === "network") {
    const networkLayer = {...layer, slot: layer.slot ?? "center"} as VisualLayer;
    const dimensions = slotDimensions(networkLayer.slot, beat.composition, reserveBottom);
    return (
      <SlotWrap layer={networkLayer} composition={beat.composition} reserveBottom={reserveBottom}>
        <NetworkLayer
          layer={layer}
          visibility={visibility}
          frame={frame}
          layerRevealFrame={revealFrame}
          width={dimensions.width}
          height={dimensions.height}
        />
      </SlotWrap>
    );
  }
  if (layer.kind === "dialogue") {
    return (
      <SlotWrap layer={layer} composition={beat.composition} reserveBottom={reserveBottom}>
        <DialogueLayer layer={layer} visibility={visibility} localFrame={localFrame} />
      </SlotWrap>
    );
  }
  if (layer.kind === "annotate") {
    return <AnnotateLayer layer={layer} visibility={visibility} localFrame={localFrame} />;
  }
  if (!layer.asset) return null;
  const asset = getVisualAsset(layer.asset);
  const float = idleFloat(frame, revealFrame + 10);
  return (
    <div
      style={{
        ...slotStyle(layer.slot, beat.composition, reserveBottom),
        overflow: "hidden",
        opacity: visibility,
        transform: `translateY(${(1 - visibility) * 18 + float}px) scale(${0.96 + visibility * 0.04})`,
        border: layer.slot === "canvas" ? undefined : `4px solid rgba(255,255,255,0.9)`,
        boxShadow: layer.slot === "canvas" ? undefined : "12px 14px 0 rgba(5,17,31,0.62)",
      }}
    >
      <AssetMedia asset={asset} />
    </div>
  );
};

const BeatCanvas: React.FC<{
  beat: VisualBeat;
  frame: number;
  startFrame: number;
  endFrame: number;
}> = ({beat, frame, startFrame, endFrame}) => {
  const base = beat.baseAsset ? getVisualAsset(beat.baseAsset) : null;
  const composition = beat.composition;
  const localFrame = Math.max(0, frame - startFrame);
  const duration = Math.max(1, endFrame - startFrame);
  const preset = presetFor(beat);
  const transform = cameraTransform(beat.camera, localFrame, duration, preset.cameraScale);
  const tint = treatmentTint(beat.treatment);
  // escalate beats breathe: a slow tint pulse keeps tension visible.
  const pulse = preset.pulse ? (Math.sin(localFrame / 22) + 1) * 0.045 : 0;
  return (
    <AbsoluteFill style={{overflow: "hidden", backgroundColor: "rgba(246,239,218,0.18)"}}>
      {base && needsAmbientBase(composition) ? (
        <AssetMedia
          asset={base}
          style={{
            // A static ambient plate keeps the canvas filled without forcing
            // software Chrome to recompute a full-frame animated blur.
            transform: "scale(1.04)",
            opacity: 0.34,
          }}
        />
      ) : null}
      {base ? (
        <div style={compositionStyle(composition)}>
          <AssetMedia
            asset={base}
            fit={composition === "document-focus" ? "contain" : "cover"}
            style={{transform}}
          />
        </div>
      ) : null}
      {tint !== "transparent" ? <AbsoluteFill style={{background: tint}} /> : null}
      <AbsoluteFill
        style={{
          background:
            composition === "portrait-left"
              ? "linear-gradient(90deg, transparent 34%, rgba(4,14,28,0.46) 68%, rgba(4,14,28,0.62))"
              : composition === "portrait-right"
                ? "linear-gradient(90deg, rgba(4,14,28,0.62), rgba(4,14,28,0.44) 34%, transparent 72%)"
                : composition === "split" || composition === "evidence-collage"
                  ? "linear-gradient(90deg, rgba(4,14,28,0.56) 0%, rgba(4,14,28,0.38) 38%, transparent 66%)"
                  : "linear-gradient(180deg, rgba(4,14,28,0.02), rgba(4,14,28,0.12))",
        }}
      />
      {preset.vignette > 0 ? (
        <AbsoluteFill
          style={{
            background: `radial-gradient(ellipse at center, transparent 46%, rgba(4,14,28,${
              preset.vignette + pulse
            }) 100%)`,
          }}
        />
      ) : null}
      {preset.flashback ? (
        <AbsoluteFill
          style={{
            border: "14px solid rgba(249,251,255,0.28)",
            boxSizing: "border-box",
            background: "rgba(249,251,255,0.05)",
          }}
        />
      ) : null}
      {(beat.layers ?? []).map((layer, index) => (
        <div key={layer.id ?? `${beat.id}-layer-${index}`} style={{position: "absolute", inset: 0, zIndex: index + 2}}>
          <VisualLayerView layer={layer} beat={beat} frame={frame} layerIndex={index} layers={beat.layers ?? []} />
        </div>
      ))}
    </AbsoluteFill>
  );
};

export const VisualBeatTrack: React.FC = () => {
  const frame = useCurrentFrame();
  const currentIndex = beats.findIndex((entry) => frame >= entry.startFrame && frame < entry.endFrame);
  if (currentIndex < 0) return null;

  const current = beats[currentIndex];
  const previous = currentIndex > 0 ? beats[currentIndex - 1] : null;
  const transition = current.beat.transition ?? "cut";
  const transitionFrames = transition === "cut" ? 1 : 14;
  const progress = interpolate(
    frame,
    [current.startFrame, current.startFrame + transitionFrames],
    [transition === "cut" ? 1 : 0, 1],
    {extrapolateLeft: "clamp", extrapolateRight: "clamp"},
  );
  const previousIsContiguous = previous?.endFrame === current.startFrame;
  const currentX = transition === "push" ? (1 - progress) * 120 : 0;
  const previousX = transition === "push" ? progress * -72 : 0;

  return (
    <AbsoluteFill style={{overflow: "hidden"}}>
      {previous && previousIsContiguous && progress < 1 ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            opacity: 1 - progress * (transition === "dissolve" ? 0.9 : 0.35),
            transform: `translateX(${previousX}px)`,
          }}
        >
          <BeatCanvas
            beat={previous.beat}
            frame={Math.min(frame, current.startFrame - 1)}
            startFrame={previous.startFrame}
            endFrame={previous.endFrame}
          />
        </div>
      ) : null}
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: transition === "cut" ? 1 : progress,
          transform: `translateX(${currentX}px)`,
        }}
      >
        <BeatCanvas
          beat={current.beat}
          frame={frame}
          startFrame={current.startFrame}
          endFrame={current.endFrame}
        />
      </div>
    </AbsoluteFill>
  );
};
