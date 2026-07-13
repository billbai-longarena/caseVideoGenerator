import storyboardJson from "./generated/rich_storyboard.json";
import timelineJson from "./generated/narration.timeline.json";
import type {Storyboard, Timeline, VisualAsset} from "./types";

export const storyboard = storyboardJson as unknown as Storyboard;
export const timeline = timelineJson as unknown as Timeline;

const unitByIndex = new Map(timeline.units.map((u) => [u.index, u]));
const visualAssetById = new Map((storyboard.visualAssets ?? []).map((asset) => [asset.id, asset]));

export const getUnit = (index: number) => {
  const unit = unitByIndex.get(index);
  if (!unit) {
    throw new Error(`timeline unit ${index} not found`);
  }
  return unit;
};

export const getVisualAsset = (id: string): VisualAsset => {
  const asset = visualAssetById.get(id);
  if (!asset) {
    throw new Error(`visual asset ${id} not found`);
  }
  return asset;
};

const validate = () => {
  if (visualAssetById.size !== (storyboard.visualAssets ?? []).length) {
    throw new Error("visual asset ids must be unique");
  }
  let expected = 1;
  for (const scene of storyboard.scenes) {
    const [first, last] = scene.units;
    if (first !== expected) {
      throw new Error(
        `scene ${scene.id}: units start at ${first}, expected ${expected} (ranges must be contiguous)`,
      );
    }
    if (last < first) {
      throw new Error(`scene ${scene.id}: invalid unit range [${first}, ${last}]`);
    }
    getUnit(first);
    getUnit(last);
    const beats = scene.visualBeats ?? [];
    for (let index = 0; index < beats.length; index += 1) {
      const beat = beats[index];
      if (beat.atUnit < first || beat.atUnit > last) {
        throw new Error(`scene ${scene.id}: visual beat ${beat.id} falls outside scene units`);
      }
      if (index > 0 && beat.atUnit <= beats[index - 1].atUnit) {
        throw new Error(`scene ${scene.id}: visual beats must be ordered by atUnit`);
      }
      if (beat.baseAsset) getVisualAsset(beat.baseAsset);
      for (const layer of beat.layers ?? []) {
        if (layer.asset) getVisualAsset(layer.asset);
      }
    }
    expected = last + 1;
  }
  if (expected - 1 !== timeline.units.length) {
    throw new Error(
      `scenes cover units 1..${expected - 1} but timeline has ${timeline.units.length}`,
    );
  }
};

validate();
