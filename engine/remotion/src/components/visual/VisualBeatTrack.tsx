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
  CameraPath,
  VisualAsset,
  VisualBeat,
  VisualBeatCamera,
  VisualBeatComposition,
  VisualBeatPurpose,
  VisualBeatRender,
  VisualBeatTreatment,
  VisualBox,
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

// Compatibility defaults for historical storyboards. Director plans v2 provide
// explicit render controls and do not derive visual treatment from purpose.
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

const renderFor = (beat: VisualBeat): VisualBeatRender => {
  if (beat.render) return beat.render;
  const legacy = presetFor(beat);
  return {
    cameraIntensity: legacy.cameraScale,
    ambientOpacity: 0.34,
    vignette: legacy.vignette,
    overlay: "soft",
    transitionFrames: 14,
    layerEnterFrames: 8,
    layerExitFrames: 7,
    layerStaggerFrames: legacy.layerStagger,
    emphasisScale: legacy.emphasisScale,
    pulse: legacy.pulse ?? false,
    flashbackFrame: legacy.flashback ?? false,
    canvasTone: "light",
  };
};

const normalizedBoxStyle = (box: VisualBox): React.CSSProperties => ({
  position: "absolute",
  left: `${box.x * 100}%`,
  top: `${box.y * 100}%`,
  width: `${box.width * 100}%`,
  height: `${box.height * 100}%`,
});

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

const layerPositionStyle = (
  layer: VisualLayer,
  composition?: VisualBeatComposition,
  reserveBottom = false,
) => (layer.box ? normalizedBoxStyle(layer.box) : slotStyle(layer.slot, composition, reserveBottom));

const compactTextPositionStyle = (
  layer: VisualLayer,
  composition?: VisualBeatComposition,
  reserveBottom = false,
): React.CSSProperties => {
  const style = {...layerPositionStyle(layer, composition, reserveBottom)};
  if (!layer.box) {
    delete style.bottom;
    delete style.height;
    delete style.minHeight;
  }
  return style;
};

const layerDimensions = (
  layer: VisualLayer,
  composition?: VisualBeatComposition,
  reserveBottom = false,
) =>
  layer.box
    ? {width: Math.round(layer.box.width * 1920), height: Math.round(layer.box.height * 1080)}
    : slotDimensions(layer.slot, composition, reserveBottom);

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
  return "scale(1)";
};

const cameraPathTransform = (path: CameraPath, frame: number, duration: number) => {
  const progress = clamp(frame / Math.max(1, duration), 0, 1);
  const scale = interpolate(progress, [0, 1], [path.startScale, path.endScale]);
  const x = interpolate(progress, [0, 1], [path.startX, path.endX]);
  const y = interpolate(progress, [0, 1], [path.startY, path.endY]);
  return `translate3d(${x}px, ${y}px, 0) scale(${scale})`;
};

const canvasBackground = (tone: VisualBeatRender["canvasTone"]) => {
  if (tone === "transparent") return "transparent";
  if (tone === "dark") return palette.ink;
  return "rgba(246,239,218,0.18)";
};

const overlayBackground = (beat: VisualBeat, overlay: VisualBeatRender["overlay"]) => {
  if (!beat.render) {
    if (beat.composition === "portrait-left") {
      return "linear-gradient(90deg, transparent 34%, rgba(4,14,28,0.46) 68%, rgba(4,14,28,0.62))";
    }
    if (beat.composition === "portrait-right") {
      return "linear-gradient(90deg, rgba(4,14,28,0.62), rgba(4,14,28,0.44) 34%, transparent 72%)";
    }
    if (beat.composition === "split" || beat.composition === "evidence-collage") {
      return "linear-gradient(90deg, rgba(4,14,28,0.56) 0%, rgba(4,14,28,0.38) 38%, transparent 66%)";
    }
  }
  if (overlay === "read-left") {
    return "linear-gradient(90deg, rgba(4,14,28,0.72) 0%, rgba(4,14,28,0.42) 38%, transparent 72%)";
  }
  if (overlay === "read-right") {
    return "linear-gradient(90deg, transparent 28%, rgba(4,14,28,0.42) 62%, rgba(4,14,28,0.72) 100%)";
  }
  if (overlay === "soft") {
    return "linear-gradient(180deg, rgba(4,14,28,0.02), rgba(4,14,28,0.16))";
  }
  return "transparent";
};

const compositionStyle = (
  composition: VisualBeatComposition,
  baseBox?: VisualBox,
): React.CSSProperties => {
  const common: React.CSSProperties = {
    position: "absolute",
    overflow: "hidden",
  };
  if (baseBox) return {...common, ...normalizedBoxStyle(baseBox)};
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

const isBackgroundLikeAsset = (asset: VisualAsset) =>
  asset.id.startsWith("bg-") || /(^|\/)bg[-_]/.test(asset.src);

// v2 makes the cascade explicit. Historical plans retain their purpose preset.
const layerRevealFrame = (layer: VisualLayer, beat: VisualBeat, layerIndex: number) => {
  const stagger = layer.revealAtUnit ? 0 : layerIndex * renderFor(beat).layerStaggerFrames;
  return unitStartFrame(layer.revealAtUnit ?? beat.atUnit) + stagger;
};

const alignItemsFor = (align: VisualLayer["align"] = "left") => {
  if (align === "center") return "center";
  if (align === "right") return "flex-end";
  return "flex-start";
};

const entryTransform = (
  layer: VisualLayer,
  visibility: number,
  float = 0,
  targetScale = 1,
) => {
  const enter = layer.enter ?? (layer.slot?.includes("right") ? "slide-right" : "slide-left");
  const distance = 34 * (1 - visibility);
  const x = enter === "slide-left" ? -distance : enter === "slide-right" ? distance : 0;
  const y = (enter === "fade" ? 0 : 14 * (1 - visibility)) + float;
  const entryScale = enter === "scale" ? 0.9 + visibility * 0.1 : 1;
  return `translate(${x}px, ${y}px) scale(${entryScale * targetScale})`;
};

const legacyTextSurface = (
  isStamp: boolean,
  isHeadline: boolean,
): React.CSSProperties => ({
  background: isStamp
    ? "rgba(5,17,31,0.72)"
    : isHeadline
      ? "linear-gradient(90deg, rgba(5,17,31,0.9), rgba(5,17,31,0.34))"
      : "rgba(5,17,31,0.76)",
  border: isStamp ? `5px solid ${palette.yellow}` : `2px solid rgba(255,255,255,0.5)`,
  boxShadow: isStamp ? `10px 10px 0 ${palette.ink}` : "10px 12px 30px rgba(0,0,0,0.34)",
});

const textSurfaceStyle = (
  layer: VisualLayer,
  isStamp: boolean,
  isHeadline: boolean,
): React.CSSProperties => {
  if (!layer.surface) return legacyTextSurface(isStamp, isHeadline);
  if (layer.surface === "none") return {background: "transparent", border: "none", boxShadow: "none"};
  if (layer.surface === "glass") {
    return {
      background: "rgba(5,17,31,0.68)",
      border: "1px solid rgba(255,255,255,0.42)",
      boxShadow: "0 12px 30px rgba(0,0,0,0.24)",
    };
  }
  if (layer.surface === "paper") {
    return {
      background: "rgba(246,239,218,0.96)",
      border: "2px solid rgba(5,17,31,0.28)",
      boxShadow: "8px 10px 0 rgba(5,17,31,0.28)",
    };
  }
  if (layer.surface === "accent") {
    return {
      background: palette.yellow,
      border: `2px solid ${palette.ink}`,
      boxShadow: `8px 10px 0 ${palette.ink}`,
    };
  }
  return {
    background: "rgba(5,17,31,0.92)",
    border: "none",
    boxShadow: "0 12px 30px rgba(0,0,0,0.3)",
  };
};

const assetFrameStyle = (frame: VisualLayer["frame"]): React.CSSProperties => {
  if (!frame || frame === "none") return {};
  if (frame === "paper") {
    return {
      border: "10px solid rgba(246,239,218,0.98)",
      boxShadow: "12px 14px 0 rgba(5,17,31,0.54)",
    };
  }
  if (frame === "dark") {
    return {
      border: "6px solid rgba(5,17,31,0.94)",
      boxShadow: "12px 14px 0 rgba(5,17,31,0.5)",
    };
  }
  return {
    border: "4px solid rgba(255,255,255,0.92)",
    boxShadow: "12px 14px 0 rgba(5,17,31,0.62)",
  };
};

const layerVisibility = (
  layer: VisualLayer,
  beat: VisualBeat,
  frame: number,
  layerIndex: number,
  layers: VisualLayer[],
) => {
  const revealFrame = layerRevealFrame(layer, beat, layerIndex);
  const enter =
    layer.enter === "cut"
      ? frame >= revealFrame
        ? 1
        : 0
      : interpolate(
          frame,
          [revealFrame, revealFrame + renderFor(beat).layerEnterFrames],
          [0, 1],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          },
        );
  const explicitExitFrame = layer.exitAtUnit ? unitStartFrame(layer.exitAtUnit) : null;
  const autoExitFrame =
    !beat.render && layer.kind === "text"
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
  const exitFrames = renderFor(beat).layerExitFrames;
  const exit = interpolate(frame, [exitFrame - exitFrames, exitFrame], [1, 0], {
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
  const isTriptychText = beat.composition === "triptych" && isThreeColumnSlot(layer.slot);
  const text = layer.text ?? "";
  const textLines = text.split("\n");
  const longestLine = Math.max(1, ...textLines.map((line) => [...line.trim()].length));
  const maxTextSize = isMetric ? 94 : isHeadline ? (isTriptychText ? 43 : 58) : isStamp ? 54 : variant === "quote" ? 43 : 36;
  const textFontSize =
    layer.fontSize ??
    (isMetric
      ? maxTextSize
      : clamp(maxTextSize - Math.max(0, longestLine - 7) * 2.2 - Math.max(0, textLines.length - 2) * 3, 30, maxTextSize));
  const float = beat.render ? 0 : idleFloat(frame, revealFrame + 12);
  const emphasis = renderFor(beat).emphasisScale;
  const scaleTarget = isMetric || isStamp ? emphasis : 1;
  const align = layer.align ?? (layer.slot?.includes("right") ? "right" : "left");
  const darkText = layer.surface === "paper" || layer.surface === "accent";
  const foreground = layer.color ?? (darkText ? palette.ink : isMetric ? palette.yellow : palette.white);
  const surface = textSurfaceStyle(layer, isStamp, isHeadline);
  const position = beat.render
    ? compactTextPositionStyle(layer, beat.composition, reserveBottom)
    : layerPositionStyle(layer, beat.composition, reserveBottom);
  return (
    <div
      style={{
        ...position,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: alignItemsFor(align),
        boxSizing: "border-box",
        padding: isMetric ? "30px 38px" : "24px 30px",
        opacity: visibility,
        transform: entryTransform(layer, visibility, float, scaleTarget),
        transformOrigin: align === "right" ? "right center" : align === "center" ? "center" : "left center",
        color: foreground,
        fontFamily: fontStack,
        textAlign: align,
        ...surface,
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
            letterSpacing: 0,
            color: darkText ? palette.ink : isMetric || isStamp ? palette.yellow : "rgba(255,255,255,0.76)",
            marginBottom: 10,
          }}
        >
          {layer.label}
        </div>
      ) : null}
      <div
        style={{
          fontSize: textFontSize,
          lineHeight: layer.lineHeight ?? (isMetric ? 0.98 : 1.18),
          fontWeight: layer.fontWeight ?? (isMetric || isHeadline || isStamp ? 950 : 800),
          color: foreground,
          whiteSpace: "pre-line",
          overflowWrap: "anywhere",
          textShadow: darkText ? "none" : "0 4px 0 rgba(0,0,0,0.52)",
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
  visibility: number;
  children: React.ReactNode;
}> = ({layer, composition, reserveBottom, visibility, children}) => (
  <div
    style={{
      ...layerPositionStyle(layer, composition, reserveBottom),
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      alignItems: alignItemsFor(layer.align ?? (layer.slot?.includes("right") ? "right" : "left")),
      boxSizing: "border-box",
      minWidth: 0,
      minHeight: 0,
      opacity: visibility,
      transform: entryTransform(layer, visibility),
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
          ...layerPositionStyle(layer, beat.composition, reserveBottom),
          backgroundColor: layer.color,
          opacity: (layer.opacity ?? 0.25) * visibility,
          transform: entryTransform(layer, visibility),
        }}
      />
    );
  }
  if (layer.kind === "counter") {
    return (
      <SlotWrap layer={layer} composition={beat.composition} reserveBottom={reserveBottom} visibility={visibility}>
        <CounterLayer layer={layer} visibility={visibility} localFrame={localFrame} />
      </SlotWrap>
    );
  }
  if (layer.kind === "bar-compare") {
    return (
      <SlotWrap layer={layer} composition={beat.composition} reserveBottom={reserveBottom} visibility={visibility}>
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
    const dimensions = layerDimensions(networkLayer, beat.composition, reserveBottom);
    return (
      <SlotWrap
        layer={networkLayer}
        composition={beat.composition}
        reserveBottom={reserveBottom}
        visibility={visibility}
      >
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
      <SlotWrap layer={layer} composition={beat.composition} reserveBottom={reserveBottom} visibility={visibility}>
        <DialogueLayer layer={layer} visibility={visibility} localFrame={localFrame} />
      </SlotWrap>
    );
  }
  if (layer.kind === "annotate") {
    return <AnnotateLayer layer={layer} visibility={visibility} localFrame={localFrame} />;
  }
  if (!layer.asset) return null;
  const asset = getVisualAsset(layer.asset);
  const float = beat.render ? 0 : idleFloat(frame, revealFrame + 10);
  const legacyFrame = !layer.frame && layer.slot !== "canvas" ? assetFrameStyle("white") : {};
  return (
    <div
      style={{
        ...layerPositionStyle(layer, beat.composition, reserveBottom),
        overflow: "hidden",
        opacity: visibility,
        transform: entryTransform(layer, visibility, float),
        ...legacyFrame,
        ...assetFrameStyle(layer.frame),
      }}
    >
      <AssetMedia asset={asset} fit={layer.fit ?? "cover"} />
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
  const render = renderFor(beat);
  const baseIsBackground = Boolean(base && render.canvasTone === "transparent" && isBackgroundLikeAsset(base));
  const transform = render.cameraPath
    ? cameraPathTransform(render.cameraPath, localFrame, duration)
    : cameraTransform(beat.camera, localFrame, duration, render.cameraIntensity ?? 1);
  const tint = render.treatmentColor ?? treatmentTint(beat.treatment);
  const pulse = render.pulse ? (Math.sin(localFrame / 22) + 1) * 0.045 : 0;
  const ambientOpacity = beat.render
    ? render.ambientOpacity
    : composition === "full-bleed"
      ? 0
      : render.ambientOpacity;
  return (
    <AbsoluteFill style={{overflow: "hidden", backgroundColor: canvasBackground(render.canvasTone)}}>
      {base && ambientOpacity > 0 && !baseIsBackground ? (
        <AssetMedia
          asset={base}
          style={{
            transform: "scale(1.04)",
            opacity: ambientOpacity,
          }}
        />
      ) : null}
      {base ? (
        <div style={baseIsBackground ? {position: "absolute", inset: 0, overflow: "hidden"} : compositionStyle(composition, beat.baseBox)}>
          <AssetMedia
            asset={base}
            fit={baseIsBackground ? "cover" : beat.baseFit ?? (composition === "document-focus" ? "contain" : "cover")}
            style={{transform}}
          />
        </div>
      ) : null}
      {tint !== "transparent" ? <AbsoluteFill style={{background: tint}} /> : null}
      <AbsoluteFill
        style={{
          background: overlayBackground(beat, render.overlay),
        }}
      />
      {render.vignette > 0 ? (
        <AbsoluteFill
          style={{
            background: `radial-gradient(ellipse at center, transparent 46%, rgba(4,14,28,${
              render.vignette + pulse
            }) 100%)`,
          }}
        />
      ) : null}
      {render.flashbackFrame ? (
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
  const transitionFrames = transition === "cut" ? 1 : renderFor(current.beat).transitionFrames;
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
