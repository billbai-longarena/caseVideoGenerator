export type Tone = "dark" | "archive" | "bright";

export type BackgroundTransition = "wash" | "paper" | "ink" | "flash" | "push";
export type BackgroundMotion = "center" | "left" | "right" | "lift";

export type VisualAssetType = "image" | "video";
export type VisualAssetRole =
  | "context"
  | "person"
  | "evidence"
  | "document"
  | "map"
  | "metaphor"
  | "texture";
export type VisualAssetOrigin = "generated" | "curated";

export type VisualAsset = {
  id: string;
  type: VisualAssetType;
  src: string;
  role: VisualAssetRole;
  origin: VisualAssetOrigin;
  poolAssetId?: string;
  credit?: string;
  license?: string;
};

export type VisualMode = "layout" | "editorial" | "hybrid";
export type VisualBeatPurpose =
  | "establish"
  | "identify"
  | "evidence"
  | "explain"
  | "escalate"
  | "consequence"
  | "callback"
  | "reset";
export type VisualBeatComposition =
  | "full-bleed"
  | "portrait-left"
  | "portrait-right"
  | "split"
  | "triptych"
  | "document-focus"
  | "evidence-collage";
export type VisualBeatTransition = "cut" | "dissolve" | "push";
export type VisualBeatCamera = "static" | "push-in" | "pull-out" | "pan-left" | "pan-right";
export type VisualBeatTreatment = "natural" | "desaturated" | "blueprint" | "crisis";
export type VisualLayerKind =
  | "asset"
  | "text"
  | "tint"
  | "counter"
  | "bar-compare"
  | "network"
  | "dialogue"
  | "annotate";
export type VisualLayerSlot =
  | "canvas"
  | "left"
  | "right"
  | "center"
  | "inset-left"
  | "inset-right"
  | "top-left"
  | "top-right"
  | "bottom";

export type CounterValue = {
  from?: number;
  to: number;
  suffix?: string;
  prefix?: string;
  decimals?: number;
};

export type CompareBar = {
  label: string;
  value: number;
  max?: number;
  suffix?: string;
  tone?: "good" | "bad" | "neutral";
  revealAtUnit?: number;
};

export type NetworkNode = {
  id: string;
  label: string;
  sub?: string;
  asset?: string;
  emphasis?: boolean;
  revealAtUnit?: number;
};

export type NetworkLink = {
  from: string;
  to: string;
  label?: string;
  revealAtUnit?: number;
};

export type AnnotateShape = "ring" | "arrow" | "underline" | "box";

export type AnnotateRegion = {
  x: number;
  y: number;
  w: number;
  h: number;
};

export type VisualLayer = {
  id?: string;
  kind: VisualLayerKind;
  slot?: VisualLayerSlot;
  asset?: string;
  label?: string;
  text?: string;
  variant?: "metric" | "caption" | "quote" | "stamp" | "headline";
  color?: string;
  opacity?: number;
  revealAtUnit?: number;
  exitAtUnit?: number;
  // counter
  value?: CounterValue;
  deltaTone?: "good" | "bad" | "neutral";
  // bar-compare
  bars?: CompareBar[];
  // network
  nodes?: NetworkNode[];
  links?: NetworkLink[];
  // dialogue
  speaker?: string;
  tail?: "left" | "right";
  // annotate
  shape?: AnnotateShape;
  region?: AnnotateRegion;
};

export type VisualBeat = {
  id: string;
  atUnit: number;
  purpose: VisualBeatPurpose;
  composition: VisualBeatComposition;
  baseAsset?: string;
  transition?: VisualBeatTransition;
  camera?: VisualBeatCamera;
  treatment?: VisualBeatTreatment;
  layers?: VisualLayer[];
};

export type SfxId = "pop" | "whoosh" | "stamp" | "flash";

export type LayoutId =
  | "breaking-news"
  | "hook-alert"
  | "subject-reveal"
  | "reveal-card"
  | "split-data"
  | "insight-split"
  | "map-focus"
  | "focus-ring"
  | "local-playbook"
  | "resource-map"
  | "balance-beam"
  | "tension-line"
  | "question-storm"
  | "question-cards"
  | "timeline-roadshow"
  | "milestone-rail"
  | "decision-board"
  | "option-board"
  | "closing-quote"
  | "closing-idea"
  | "performance-ladder"
  | "decision-bottleneck"
  | "authority-matrix";

export type TimelineUnit = {
  index: number;
  text: string;
  start: number;
  end: number;
  pauseAfter: number;
};

export type Timeline = {
  audio: string;
  duration: number;
  units: TimelineUnit[];
};

export type HeadlineSpec = {
  text: string;
  reveal: "perChar" | "perClause";
  accent: string[];
};

export type KeywordCue = {
  text: string;
  atUnit: number;
  offset?: number;
  sfx?: SfxId;
};

export type SubtitleCue = {
  unit: number;
  text: string;
};

export type BackgroundCue = {
  image?: string;
  video?: string;
  atUnit: number;
  offset?: number;
  transition: BackgroundTransition;
  motion: BackgroundMotion;
  sfx?: SfxId;
};

export type Scene = {
  id: string;
  chapter: string;
  kicker: string;
  layout: LayoutId;
  tone: Tone;
  units: [number, number];
  headline: HeadlineSpec;
  keywords: KeywordCue[];
  subtitles: SubtitleCue[];
  backgrounds: BackgroundCue[];
  visualMode?: VisualMode;
  visualBeats?: VisualBeat[];
  props: Record<string, unknown>;
};

export type BgmSpec = {
  src: string;
  volumeDb: number;
  duckBoostDb: number;
};

export type Storyboard = {
  slug?: string;
  title: string;
  subtitle: string;
  brand: string;
  projectType?: string;
  visualStyle?: string;
  subtitleLabel?: string;
  fps: number;
  width: number;
  height: number;
  audio: string;
  timeline: string;
  bgm?: BgmSpec;
  visualAssets?: VisualAsset[];
  scenes: Scene[];
};
