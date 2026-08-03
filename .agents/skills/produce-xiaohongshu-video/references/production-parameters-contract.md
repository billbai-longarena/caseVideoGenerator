# Production Parameters TXT Contract

Use this contract when one model plans a Xiaohongshu episode and another model executes it.

## File and lifecycle

- Write one UTF-8 plain-text file: `output/<project>/production_parameters.txt`.
- Use `SCHEMA_VERSION: 1`.
- Use one `APPROVAL_STATUS`: `DRAFT`, `WAITING_FOR_APPROVAL`, `APPROVED`, or `SUPERSEDED`.
- Execution is forbidden until status is `APPROVED` and no value contains `PENDING`.
- Record user-approved choices in the file before changing the status to `APPROVED`.
- For videos under 3 minutes, 2 named people are valid when they fully carry the story. Keep the stable `PERSON_3` key and write `NONE_NOT_NEEDED` when a third person would only be quota-filling.

## Required sections

Keep the following section names and `KEY: value` form so both humans and models can scan the handoff reliably.

```text
[DOCUMENT]
DOCUMENT_TYPE: XIAOHONGSHU_PRODUCTION_PARAMETERS
SCHEMA_VERSION: 1
APPROVAL_STATUS: WAITING_FOR_APPROVAL
PROJECT_DIR:
EPISODE_ID:
SOURCE_FILES:
PLANNING_SCOPE:

[APPROVAL]
USER_APPROVAL_REQUIRED: YES
APPROVED_AT:
APPROVED_BY:
PENDING_DECISIONS:
LOCKED_AFTER_APPROVAL:

[MATRIX]
ROLE_CODE:
STAGE_CODE:
CHALLENGE_CODE:
THEORY_CODES:
ARC_CODE:
INDUSTRY:
PROTAGONIST_AGE:
ANTI_REPETITION_RESULT:

[TITLE_AND_HOOK]
SOURCE_TITLE:
PRIMARY_TITLE:
ALTERNATE_TITLES:
COVER_TITLE:
HOOK_EVENT:
HOOK_DIRECTION:

[PEOPLE_AND_EVENT]
PERSON_1:
PERSON_2:
PERSON_3:
CORE_EVENT_CHAIN:
TURNING_BEHAVIOR:
RESULT_BEHAVIOR:

[THEORY_AND_CTA]
THEORY_GOLD_SENTENCE:
THEORY_FRAME_DIRECTION:
CLOSING_CTA:

[NARRATION]
LANGUAGE:
TARGET_CHARACTERS:
TARGET_DURATION:
STRUCTURE:
FORBIDDEN_PATTERNS:

[VIDEO]
CANVAS:
FPS:
VISUAL_MODE:
SCENE_TARGET:
BEAT_TARGET:
BEAT_DURATION:
COVER_MAX_DURATION:
SUBTITLE_LABEL:

[VISUALS]
VISUAL_FAMILY:
PALETTE:
STYLE_DIRECTION:
BACKGROUND_SIZE:
BACKGROUND_COUNT:
PORTRAIT_SIZE:
PORTRAIT_COUNT:
PORTRAIT_CONTRACT:
TEXT_SURFACE:
TREATMENT_COLOR:
ASSET_FORBIDDENS:

[TTS]
ENGINE:
VOICE:
PROFILE:
RATE:
PITCH:
PARAGRAPH_GAP:
VOICE_MODE:

[EXECUTION_HANDOFF]
EXECUTION_BLOCKED_UNTIL:
EXECUTOR_MUST_READ:
EXECUTOR_MUST_PRESERVE:
STOP_AND_ESCALATE_IF:
DO_NOT_GENERATE_YET:
```

## Promotion and precedence

1. The planning model fills every section, leaves disputed values explicit, and sets `WAITING_FOR_APPROVAL`.
2. After user approval, update the selected values, clear `PENDING_DECISIONS`, record approval, and set `APPROVED`.
3. The execution model reads the approved file before writing `title.txt` or `narration.txt`.
4. `title.txt`, `narration.txt`, `narration.timeline.json`, and `storyboard_plan.json` retain their normal source-of-truth responsibilities after creation. The approved brief is the locked intent and parameter checkpoint.
5. If source evidence, validation, or available capabilities conflict with an approved field, stop and ask for a revised approval instead of silently substituting another choice.
