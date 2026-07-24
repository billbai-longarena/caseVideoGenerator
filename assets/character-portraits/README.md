# Character Portrait Pool

This pool contains reusable square portraits for character introductions, dialogue staging, and role cards in case videos.

## Sets

- `sales-watercolor-blue-yellow`: 10 Chinese men and 10 Chinese women in the sales-case blue/yellow watercolor family.
- `manager-silhouette-warm`: 10 Chinese men and 10 Chinese women in the sales-management warm silhouette family.

Every portrait is a 1024×1024 PNG with a white background, a stable asset ID, an approximate age, an age band, a face direction, and a recommended Remotion placement. The default profile family uses formal business attire, but individual profiles may define role-appropriate industry attire when a case needs non-office characters.

## Commands

```bash
scripts/character-portraits prepare
scripts/character-portraits finalize --reviewed
scripts/character-portraits search --style sales-watercolor-blue-yellow --gender female --min-age 35 --max-age 50
scripts/character-portraits checkout cn-sales-watercolor-f-05 output/<project>
scripts/character-portraits audit
```

`checkout` copies the portrait into `images/characters/` inside the case project and records the SHA-256 and pool provenance in the existing `asset_pool_usage.json` file. Add the printed JSON object to `rich_storyboard.json.visualAssets`, then reference its ID from a Visual Beat image layer. The asset role is `person`.

For dialogue layouts, choose a portrait whose `faceDirection` points inward:

- place `screen-right` portraits on the left;
- place `screen-left` portraits on the right;
- use `front` portraits for introductions, centered role cards, or either side.

`specs.json` is the compact character and style source. The initial baseline contains 40 portraits, but the pool is additive: when no existing portrait fits a case, append a new profile and optionally set `styles` to one or more target visual-family IDs. Run `prepare`, generate only missing files, visually review them, then run `finalize --reviewed` and `audit` before checkout.

`generation_prompts.json` records the exact prompts sent to the image model. `catalog.json` is the runtime/search index. Contact sheets are review aids and are not video assets.
