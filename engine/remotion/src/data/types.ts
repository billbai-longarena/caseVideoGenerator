export type Tone = "dark" | "archive" | "bright";

export type BackgroundTransition = "wash" | "paper" | "ink" | "flash" | "push";
export type BackgroundMotion = "center" | "left" | "right" | "lift" | "drift" | "breathe";

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
export type VisualIntent =
  | "context"
  | "protagonist"
  | "claim"
  | "evidence"
  | "relationship"
  | "mechanism"
  | "decision"
  | "consequence"
  | "reflection";
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
  | "evidence-collage"
  | "custom";
export type VisualBeatTransition = "cut" | "dissolve" | "push";
export type VisualBeatCamera =
  | "static"
  | "push-in"
  | "pull-out"
  | "pan-left"
  | "pan-right"
  | "drift"
  | "breathe";
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

export type NetworkLayoutMode =
  | "auto"
  | "row"
  | "column"
  | "triangle"
  | "hub"
  | "grid";

export type AnnotateShape = "arrow" | "underline";

export type AnnotateRegion = {
  x: number;
  y: number;
  w: number;
  h: number;
};

export type VisualBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type CameraPath = {
  startScale: number;
  endScale: number;
  startX: number;
  endX: number;
  startY: number;
  endY: number;
};

export type VisualBeatRender = {
  // cameraIntensity is retained for v1 storyboard compatibility. Director
  // plans use an exact camera path and treatment color instead.
  cameraIntensity?: number;
  cameraPath?: CameraPath;
  treatmentColor?: string;
  ambientOpacity: number;
  vignette: number;
  overlay: "none" | "soft" | "read-left" | "read-right";
  transitionFrames: number;
  layerEnterFrames: number;
  layerExitFrames: number;
  layerStaggerFrames: number;
  emphasisScale: number;
  pulse: boolean;
  flashbackFrame: boolean;
  canvasTone: "transparent" | "light" | "dark";
};

export type VisualLayer = {
  id?: string;
  kind: VisualLayerKind;
  slot?: VisualLayerSlot;
  box?: VisualBox;
  asset?: string;
  label?: string;
  text?: string;
  variant?: "metric" | "caption" | "quote" | "stamp" | "headline";
  surface?: "none" | "glass" | "solid" | "paper" | "accent";
  align?: "left" | "center" | "right";
  enter?: "cut" | "fade" | "slide-left" | "slide-right" | "scale";
  fontSize?: number;
  fontWeight?: number;
  lineHeight?: number;
  color?: string;
  opacity?: number;
  frame?: "none" | "white" | "paper" | "dark";
  fit?: "cover" | "contain";
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
  networkLayout?: NetworkLayoutMode;
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
  visualIntent?: VisualIntent;
  purpose: VisualBeatPurpose;
  directorialIntent?: string;
  composition: VisualBeatComposition;
  baseAsset?: string;
  baseBox?: VisualBox;
  baseFit?: "cover" | "contain";
  transition?: VisualBeatTransition;
  camera?: VisualBeatCamera;
  treatment?: VisualBeatTreatment;
  render?: VisualBeatRender;
  chrome?: SceneChrome;
  layers?: VisualLayer[];
};

export type SfxId = "pop" | "whoosh" | "stamp" | "flash";

export type LayoutId =
  | "director-canvas"
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
  display?: boolean;
  sfx?: SfxId;
  enter?: "cut" | "fade" | "rise" | "slide-left" | "slide-right" | "scale";
  enterFrames?: number;
  surface?: "none" | "chip";
  background?: string;
  color?: string;
  rotation?: number;
  fontSize?: number;
  float?: boolean;
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

export type SceneMotion = {
  enter: "cut" | "fade" | "rise";
  exit: "cut" | "fade" | "lift";
  enterFrames?: number;
  exitFrames?: number;
};

export type SceneTransition = "none" | "ink-slide" | "chapter-circle" | "paper-stripes";

export type SceneChrome = {
  brandBug?: boolean;
  chapterBadge?: boolean;
  subtitleBar?: boolean;
};

export type StoryboardChrome = {
  brandBug: boolean;
  chapterBadge: boolean;
  subtitleBar: boolean;
  progressRail: boolean;
  cover: boolean;
};

export type DirectorDirection = {
  visualThesis: string;
  pacingArc: string;
  densityStrategy: string;
  continuityRules: string[];
  avoid?: string[];
};

export type Scene = {
  id: string;
  chapter: string;
  kicker: string;
  layout: LayoutId;
  tone?: Tone;
  units: [number, number];
  dramaticFunction?: string;
  directorialIntent?: string;
  headline?: HeadlineSpec;
  keywords: KeywordCue[];
  subtitles: SubtitleCue[];
  backgrounds: BackgroundCue[];
  visualMode?: VisualMode;
  visualBeats?: VisualBeat[];
  sceneMotion?: SceneMotion;
  transition?: SceneTransition;
  transitionFrames?: number;
  chrome?: SceneChrome;
  props: Record<string, unknown>;
};

export type LayoutScene = Scene & {tone: Tone; headline: HeadlineSpec};

export type BgmSpec = {
  src: string;
  volumeDb: number;
  duckBoostDb: number;
};

export type CoverSpec = {
  title: string;
  subtitle?: string;
  kicker?: string;
  throughUnit: number;
};

export type Storyboard = {
  slug?: string;
  title: string;
  subtitle: string;
  brand: string;
  projectType?: string;
  visualStyle?: string;
  subtitleLabel?: string;
  directorPlanVersion?: string;
  direction?: DirectorDirection;
  chrome?: StoryboardChrome;
  fps: number;
  width: number;
  height: number;
  audio: string;
  timeline: string;
  bgm?: BgmSpec;
  cover?: CoverSpec;
  visualAssets?: VisualAsset[];
  scenes: Scene[];
};
