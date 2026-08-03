# Case Project Contract

## Required authored files

- `title.txt`: One-line final article/video title, authored and reviewed with the narration; canonical source for frame-0 cover copy.
- `narration.txt`: Human-readable narration and paragraph-level pauses/cut points.
- `storyboard_plan.json`: For current projects, a schema-v2 LLM-authored director plan covering visual thesis, chrome, asset casting, scene intent, visual mode, layout or `director-canvas` composition, beats, camera, transition, timing, layers, and cover. `cover.title` is a rendered copy of `title.txt`.

## Conditional narrative files

- `case_inputs.json`: Required for synthetic, parameterized, or agent-authored/materially reconstructed cases. Records generation mode, source boundaries, unknowns, and initial customer/seller/environment parameters.
- `case_model.json`: Required for newly authored or materially reconstructed sales and sales-management cases. Records customer truth, decision network, three competition classes, disclosure state, seller belief ledger, interactions, final decision, and reveal plan.
- `case_story.md`: Required when the agent authors the complete human-readable case story. Optional when an approved source story is adapted directly.

## Required generated files

- `narration.tts.txt`: Normalized spoken text.
- `narration.tts.plan.txt`: Numbered narration units.
- `narration.timeline.json`: Unit timing and total audio duration.
- `audio/narration_azure.wav`: Default narration asset.
- `rich_storyboard.json`: Deterministically compiled render IR copied from the schema-v2 director plan with resolved units and paths. It is not a second authored visual source and must not contain adapter-invented creative choices.

## Generated readiness evidence

- `qa/readiness/plan.json` and `plan.md`: Pre-image contract result with input hashes.
- `qa/readiness/render.json` and `render.md`: Pre-render result, strict-validator status, portrait pixel/provenance checks, and exact frame-0 cover geometry.
- `qa/intent-frames/manifest.json` plus `frame-*.png`: Real-pixel representative frames rendered from `CaseVideoIntentReview`. Every scene must appear at least once; remaining capacity samples Visual Beats without splitting one scene across review batches.
- `qa/intent-frame-review.json` and optional attempt files: Multimodal evidence that cites every provided frame exactly under its actual scene and compares pixels with declared directorial intent.
- These reports are generated evidence, not authored sources. Regenerate them whenever their recorded inputs change.

## Required asset directories

- `images/`: Generated or curated visual assets referenced by the storyboard.
- `audio/`: Narration and optional BGM.
- `video/`: Internal rendered artifacts with stable pipeline names. The master is `case_video.mp4`; the upload copy is `case_video_compressed_50m.mp4`.

## Optional files

- `image_prompts.json`: Reproducible asset-ID-keyed image-generation prompts.
- `asset_pool_usage.json`: Checkout-generated provenance for shared-pool images, including pool asset ID, project-local path, and SHA-256.
- `build_storyboard.py`: Case-specific storyboard builder when JSON is generated.
- `tts_overrides.json`: Explicit local pronunciation or synthesis exceptions.
- `publication.json`: Optional release metadata. Use it when the series or sequence cannot be inferred from the project directory, to customize the series label or filename prefix, or to disable a superseded render from batch publishing.
- `sfx/`: Project-specific sound effects.

## Centralized publication output

- `publish/<topic>/S001_<title>.mp4`: Upload-ready release files generated from the project compressed copies. Each topic directory contains only MP4 files and may hold the complete correctly sorted S001-S100 publishing run.
- `publish/manifest.json`, `publish/manifest.csv`, and `publish/upload-list.txt`: Rebuildable batch-upload metadata.
- `publish/_masters/<topic>/S001_<title>_master.mp4`: Optional master staging created only with `--include-master`.
- `publish/` and project `video/` directories are generated, Git-ignored artifacts. `title.txt` and optional `publication.json` are the authored sources for public naming.

## Validation invariants

- A `source-grounded` case traces facts to source material, preserves unknowns, and does not silently convert assumptions into facts.
- A generated or reconstructed case distinguishes customer objective truth, customer disclosure, and seller/team beliefs.
- The decision network distinguishes formal approval flow from the actual influence, coalition, and veto path.
- Its competition model covers external suppliers, the customer's internal alternative, and no action, with concrete candidates inside each relevant class; the final outcome records both class and selected candidate.
- Seller beliefs distinguish verified facts, customer statements, inferences, assumptions, outdated information, and unknowns.
- The seller model distinguishes the intended sales path from the actual path and attributes deviations to new evidence, events, strengths, blind spots, or habits.
- Information cannot appear in the seller's knowledge before a plausible source or disclosure event.
- `case_story.md` and `narration.txt` do not contradict the causal facts or final decision in `case_model.json`.
- `title.txt` contains exactly one non-empty logical line, makes a factual promise supported by the case, and matches both the v2 plan and `rich_storyboard.json` `cover.title` exactly. Legacy projects without `title.txt` remain validator-readable, but production readiness requires the file before the next render.
- A current v2 plan uses direct 1-based narration units and explicitly declares every aesthetic choice the runtime needs. The compiler may validate, normalize paths, resolve references, and copy fields; it must not choose a layout, rotate variants, create beats, infer a card surface, or assign camera/transition/timing by scene or beat index.
- An editorial v2 scene uses `director-canvas`; semantic layouts are selected only when their fixed structure is intentionally part of the scene. A scene cannot disable the persistent subtitle bar.
- Every v2 scene states `directorialIntent`, and every beat explicitly states composition, camera, treatment, transition, transition frame count, layer entrance frame count, and local chrome. Custom boxes remain inside the 1920x1080 canvas and preserve the subtitle safe area.
- A background/context base asset is the visual stage. Beats that reference background-like assets (`bg-*`, `*-bg`, `background-*`, or similar project-local background names) use `render.canvasTone: "transparent"` and preserve the generated illustration; readability belongs in tint/overlay, local boxes, glass/none text, or controlled crop/camera choices. Opaque text surfaces (`paper`, `solid`, `accent`) require an explicit `box` and must not become full-screen replacement cards.
- `render.treatmentColor` is painted as a full-canvas overlay above the base image. On any beat with a `baseAsset`, it must be `transparent` or an 8-digit `#RRGGBBAA` value with a non-opaque alpha channel; a 6-digit hex (or `alpha=ff`) hides the generated background and is rejected by the compiler. Opaque colors are only legitimate on beats that intentionally paint a blank canvas (no `baseAsset`).
- When the approved directorial idea cannot be represented by the current v2 contract, the shared schema and Remotion capability are extended before the plan is compiled. Falling back to the nearest template is not a valid compatibility behavior.
- Pre-image visual-contract approval and post-pixel visual approval are separate checkpoints. Asset generation and an internal composition-only revision preserve the approved contract checkpoint and must not trigger duplicate paid generation after final approval.
- Intent-frame repair is limited to one composition-only attempt. It may change composition, crop, boxes, slots, layer visibility/timing, beat boundaries within the same scene, camera paths, treatment colors, transitions, and local chrome. It must preserve title, facts, copy, scene structure and ranges, layout/visualMode, all asset IDs, dramatic function, directorial intent, beat semantic identity, and layer semantic content.
- Timeline unit indices are unique, ordered, and continuous.
- Every newly built storyboard defines a non-empty hook title in `cover.title`; `cover.throughUnit` is a narration unit inside the first scene. The cover is a short title splash: narration starts at 0s, so the engine clamps the hold to `COVER_MAX_SECONDS` (2.0s) regardless of `throughUnit`; prefer the first unit and do not author multi-unit title holds that cover the opening narration. The complete essential copy group is centered, remains inside the centered 1:1 crop, and uses at most a compact translucent scrim fitted around the text. Legacy storyboards without `cover` remain readable but should be rebuilt before delivery.
- Storyboard scene unit ranges are ordered, non-overlapping, and cover all timeline units.
- Visual asset IDs and Visual Beat IDs are unique. Every Visual Beat asset reference resolves through the storyboard asset manifest.
- Visual Beats are ordered, stay inside their scene, and use narration units rather than handwritten seconds. Editorial and hybrid scenes begin with a visible beat at the scene start. New scenes explicitly declare `visualMode`; omitted mode with Visual Beats renders as editorial.
- Visual Beat layer reveal/exit units stay inside the scene and cannot precede the beat that owns them.
- Layout owns fixed business structures; editorial owns Visual Beat semantic panels; hybrid keeps the layout and permits only a base asset plus tint layers. The same fact is not rendered by both systems.
- Production semantic visual gaps stay within 12 seconds. Camera, composition, transition, treatment, slot, and timing changes do not count without a changed asset or story-bearing layer event. Callbacks remain occasional and cannot manufacture repeated beats.
- At most one active panel occupies a slot at a time. A `bar-compare` has at most four bars and a `network` has at most four nodes; larger structures are split across beats. Network geometry defaults to topology- and aspect-aware `networkLayout: "auto"`; explicit values are `row`, `column`, `triangle`, `hub`, and `grid`, and are used only when narration requires a fixed reading direction.
- New `annotate` layers use only `arrow` or `underline`. Legacy `box`, omitted-shape implicit boxes, and `ring` data are accepted only for compatibility, are not rendered or counted as semantic visual changes, and emit validator warnings.
- Every storyboard audio path exists relative to the project root.
- Every referenced local background, image, and video asset exists under the project root.
- Final referenced image assets are delivery images, not QA frames, contact sheets, overview grids, thumbnails, placeholders, or other review artifacts. The validator must reject both suspicious final-image paths and contact-sheet/overview-like image content.
- Every current generated storyboard image maps to a declared `image_prompts.json` file and an existing image file. Legacy projects without a visual asset manifest continue to validate prompt coverage through primary scene backgrounds.
- Every checked-out pool image maps to `asset_pool_usage.json`, exists under the project root, matches its recorded SHA-256, and uses `origin: "curated"` plus the matching `poolAssetId` when declared in `visualAssets`.
- Every portrait used by a portrait layer or declared as a portrait/character asset is square and at least 512px, shows one half-body or chest-up person on a white background, and matches the project's visual family. Generated portraits declare that crop, background, and style in `image_prompts.json`; curated portraits have accepted character-pool review, local provenance, and a matching SHA-256. A generic background with `role: "person"` or a pool ID is not automatically a portrait.
- Cross-project pool reuse is allowed only as a deliberate source: explicit user reuse, revision continuity, callback, comparison, or evidence-reveal. New visual generation must not default to pool checkout, and repeating the same project-local primary image within one video requires an explicit fallback, callback, comparison, or evidence-reveal intent marked on the scene or background cue.
- Generated files are regenerated from their source rather than edited independently. When `storyboard_plan.json` is schema v2, edits go to the plan and `rich_storyboard.json` is rebuilt.
- Background images used for final delivery are AI-generated or curated narrative illustrations, not PIL/Canvas/SVG/programmatic diagrams, icon sets, flowcharts, dashboards, or placeholders.
- Sales image prompts use the shared blue/yellow watercolor family. Sales-management image prompts use the local warm manager-silhouette motion-graphics family unless the user explicitly approves a different visual reference.
- Generated background prompts exclude readable text, numerals, letters, logos, watermarks, UI screenshots, source-document screenshots, clear human faces, and story characters. Backgrounds carry scene and atmosphere only; people always appear as separate portrait assets, never inside background art.
- Production image generation requires a passing plan-readiness report for the current declarations. Production rendering requires a passing render-readiness report for the current storyboard, timeline, prompts, provenance, and real asset bytes; stale hashes require regeneration of the report.
