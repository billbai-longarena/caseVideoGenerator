# Case Project Contract

## Required authored files

- `narration.txt`: Human-readable narration and paragraph-level pauses/cut points.
- `rich_storyboard.json`: Scene, subtitle, layout, keyword, background, optional Visual Beat/asset-layer, and audio declarations.

## Conditional narrative files

- `case_inputs.json`: Required for synthetic, parameterized, or agent-authored/materially reconstructed cases. Records generation mode, source boundaries, unknowns, and initial customer/seller/environment parameters.
- `case_model.json`: Required for newly authored or materially reconstructed sales and sales-management cases. Records customer truth, decision network, three competition classes, disclosure state, seller belief ledger, interactions, final decision, and reveal plan.
- `case_story.md`: Required when the agent authors the complete human-readable case story. Optional when an approved source story is adapted directly.

## Required generated files

- `narration.tts.txt`: Normalized spoken text.
- `narration.tts.plan.txt`: Numbered narration units.
- `narration.timeline.json`: Unit timing and total audio duration.
- `audio/narration_azure.wav`: Default narration asset.

## Required asset directories

- `images/`: Generated or curated visual assets referenced by the storyboard.
- `audio/`: Narration and optional BGM.
- `video/`: Rendered deliverables.

## Optional files

- `image_prompts.json`: Reproducible image-generation prompts.
- `asset_pool_usage.json`: Checkout-generated provenance for shared-pool images, including pool asset ID, project-local path, and SHA-256.
- `build_storyboard.py`: Case-specific storyboard builder when JSON is generated.
- `tts_overrides.json`: Explicit local pronunciation or synthesis exceptions.
- `sfx/`: Project-specific sound effects.

## Validation invariants

- A `source-grounded` case traces facts to source material, preserves unknowns, and does not silently convert assumptions into facts.
- A generated or reconstructed case distinguishes customer objective truth, customer disclosure, and seller/team beliefs.
- The decision network distinguishes formal approval flow from the actual influence, coalition, and veto path.
- Its competition model covers external suppliers, the customer's internal alternative, and no action, with concrete candidates inside each relevant class; the final outcome records both class and selected candidate.
- Seller beliefs distinguish verified facts, customer statements, inferences, assumptions, outdated information, and unknowns.
- The seller model distinguishes the intended sales path from the actual path and attributes deviations to new evidence, events, strengths, blind spots, or habits.
- Information cannot appear in the seller's knowledge before a plausible source or disclosure event.
- `case_story.md` and `narration.txt` do not contradict the causal facts or final decision in `case_model.json`.
- Timeline unit indices are unique, ordered, and continuous.
- Storyboard scene unit ranges are ordered, non-overlapping, and cover all timeline units.
- Visual asset IDs and Visual Beat IDs are unique. Every Visual Beat asset reference resolves through the storyboard asset manifest.
- Visual Beats are ordered, stay inside their scene, and use narration units rather than handwritten seconds. Editorial and hybrid scenes begin with a visible beat at the scene start.
- Visual Beat layer reveal/exit units stay inside the scene and cannot precede the beat that owns them.
- Every storyboard audio path exists relative to the project root.
- Every referenced local background, image, and video asset exists under the project root.
- Every current generated storyboard image maps to a declared `image_prompts.json` file and an existing image file. Legacy projects without a visual asset manifest continue to validate prompt coverage through primary scene backgrounds.
- Every checked-out pool image maps to `asset_pool_usage.json`, exists under the project root, matches its recorded SHA-256, and uses `origin: "curated"` plus the matching `poolAssetId` when declared in `visualAssets`.
- Cross-project pool reuse is expected. Repeating the same project-local primary image within one video requires an explicit fallback, callback, comparison, or evidence-reveal intent marked on the scene or background cue.
- Generated files are regenerated from their source rather than edited independently.
- Background images used for final delivery are AI-generated or curated narrative illustrations, not PIL/Canvas/SVG/programmatic diagrams, icon sets, flowcharts, dashboards, or placeholders.
- Sales image prompts use the shared blue/yellow watercolor family. Sales-management image prompts use the local warm manager-silhouette motion-graphics family unless the user explicitly approves a different visual reference.
- Generated background prompts exclude readable text, numerals, letters, logos, watermarks, UI screenshots, and source-document screenshots.
