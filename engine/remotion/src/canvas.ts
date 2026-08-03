import {storyboard} from "./data/storyboard";

// Canvas geometry helpers. The storyboard JSON is the single source of truth
// for output dimensions (1920x1080 landscape or 1080x1920 vertical 9:16).
// Components read these constants instead of hard-coding 1920/1080 so the
// same engine renders both orientations.

export const CANVAS_WIDTH = storyboard.width || 1920;
export const CANVAS_HEIGHT = storyboard.height || 1080;
export const IS_VERTICAL = CANVAS_HEIGHT > CANVAS_WIDTH;

// Vertical 9:16 mobile layout contract (1080x1920):
// - Platform overlay safe zones (视频号/小红书/抖音 float their own UI over
//   the video): keep essential content below VERTICAL_SAFE_TOP (y 320) and
//   above VERTICAL_CONTENT_FLOOR (y 1240). Persistent chrome (brand chip)
//   sits at VERTICAL_CHROME_TOP; the subtitle bar floats at
//   VERTICAL_SUBTITLE_BOTTOM, clear of bottom avatar/description overlays.
// - Text lanes run full width with 64px side margins (952px content width).
// - See docs/knowledge-base/vertical-mobile-video.md for the full contract.
export const VERTICAL_MARGIN_X = 64;
export const VERTICAL_CONTENT_WIDTH = CANVAS_WIDTH - VERTICAL_MARGIN_X * 2;
export const VERTICAL_SAFE_TOP = 320;
export const VERTICAL_CHROME_TOP = 310;
export const VERTICAL_SUBTITLE_BOTTOM = 400;
export const VERTICAL_CONTENT_FLOOR = 1240;

// Frame-0 cover splash: narration starts at t=0, so a cover that holds
// "through" whole narration units overlays the first seconds of spoken
// content (subtitles and beat visuals) with the centered title card. The
// cover is a short title splash: it always yields within COVER_MAX_SECONDS
// regardless of the authored cover.throughUnit, which can only shorten the
// window further. Feed thumbnails still get the full title at frame 0.
export const COVER_MAX_SECONDS = 2.0;
