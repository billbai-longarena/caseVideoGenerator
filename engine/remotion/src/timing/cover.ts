import {COVER_MAX_SECONDS} from "../canvas";
import {storyboard} from "../data/storyboard";
import {unitEndFrame} from "./timeline";

export const coverEndFrame = (fps: number) => {
  const cover = storyboard.cover;
  if (!cover) return 0;
  const splashEndFrame = Math.max(1, Math.round(COVER_MAX_SECONDS * fps));
  return Math.min(Math.max(1, unitEndFrame(cover.throughUnit, true)), splashEndFrame);
};
