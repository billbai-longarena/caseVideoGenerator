import React from "react";
import type {LayoutId} from "../data/types";
import type {LayoutProps} from "./shared";
import {BreakingNews} from "./BreakingNews";
import {SubjectReveal} from "./SubjectReveal";
import {SplitData} from "./SplitData";
import {MapFocus} from "./MapFocus";
import {LocalPlaybook} from "./LocalPlaybook";
import {BalanceBeam} from "./BalanceBeam";
import {QuestionStorm} from "./QuestionStorm";
import {TimelineRoadshow} from "./TimelineRoadshow";
import {DecisionBoard} from "./DecisionBoard";
import {ClosingQuote} from "./ClosingQuote";
import {PerformanceLadder} from "./PerformanceLadder";
import {DecisionBottleneck} from "./DecisionBottleneck";
import {AuthorityMatrix} from "./AuthorityMatrix";

const DirectorCanvas: React.FC<LayoutProps> = () => null;

const LAYOUTS: Record<LayoutId, React.FC<LayoutProps>> = {
  "director-canvas": DirectorCanvas,
  "breaking-news": BreakingNews,
  "hook-alert": BreakingNews,
  "subject-reveal": SubjectReveal,
  "reveal-card": SubjectReveal,
  "split-data": SplitData,
  "insight-split": SplitData,
  "map-focus": MapFocus,
  "focus-ring": MapFocus,
  "local-playbook": LocalPlaybook,
  "resource-map": LocalPlaybook,
  "balance-beam": BalanceBeam,
  "tension-line": BalanceBeam,
  "question-storm": QuestionStorm,
  "question-cards": QuestionStorm,
  "timeline-roadshow": TimelineRoadshow,
  "milestone-rail": TimelineRoadshow,
  "decision-board": DecisionBoard,
  "option-board": DecisionBoard,
  "closing-quote": ClosingQuote,
  "closing-idea": ClosingQuote,
  "performance-ladder": PerformanceLadder,
  "decision-bottleneck": DecisionBottleneck,
  "authority-matrix": AuthorityMatrix,
};

export const LayoutRouter: React.FC<LayoutProps> = (props) => {
  const Layout = LAYOUTS[props.scene.layout];
  return <Layout {...props} />;
};
