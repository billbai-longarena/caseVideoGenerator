#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parents[1]
AZURE_GENERATOR = SCRIPT_ROOT / "generate_azure_full.py"
PROFILE_PATH = SCRIPT_ROOT / "dragon_broadcast_profile.json"
SALES_COLUMN_OPENER = "这里是《销售不复杂》。帮你揭开销售的魔法秘密，让销售不再复杂。"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def paragraph_signature(*, text: str, voice: str, rate: str, pitch: str, region: str) -> str:
    payload = json.dumps(
        {"text": text, "voice": voice, "rate": rate, "pitch": pitch, "region": region},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_ssml(azure, text: str, voice: str, rate: str, pitch: str) -> str:
    return f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
  <voice name="{voice}"><prosody rate="{rate}" pitch="{pitch}">{azure.escape_ssml_text(text)}</prosody></voice>
</speak>'''


def synthesize_with_retry(azure, ssml: str, voice: str, region: str, api_key: str, *, attempts: int = 4):
    """Retry transient Azure streaming timeouts without changing synthesis inputs."""
    for attempt in range(1, attempts + 1):
        try:
            return azure.synthesize_ssml_with_word_boundaries(ssml, voice, region, api_key)
        except RuntimeError as exc:
            if "Timeout while synthesizing" not in str(exc) or attempt == attempts:
                raise
            delay = min(2 ** attempt, 8)
            print(
                f"Azure TTS timeout; retrying paragraph in {delay}s "
                f"(attempt {attempt + 1}/{attempts})",
                file=sys.stderr,
            )
            time.sleep(delay)


def load_paragraph_overrides(project_root: Path) -> dict[str, dict]:
    path = project_root / "tts_overrides.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    overrides = data.get("paragraphs", data)
    if not isinstance(overrides, dict):
        raise ValueError(f"Invalid paragraph overrides in {path}")
    return overrides


def group_sentences_by_paragraph(sentences):
    grouped: dict[int, list[tuple[int, object]]] = {}
    for sentence_index, sentence in enumerate(sentences, start=1):
        grouped.setdefault(sentence.paragraph_index, []).append((sentence_index, sentence))
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the default Dragon broadcast paragraph narration.")
    parser.add_argument("--project", required=True, help="Project directory containing narration.txt.")
    parser.add_argument("--gender", choices=("male", "female"), help="Starting paragraph gender.")
    parser.add_argument("--male-rate", help="Override the profile male rate.")
    parser.add_argument("--female-rate", help="Override the profile female rate.")
    parser.add_argument("--male-pitch", help="Override the profile male pitch.")
    parser.add_argument("--female-pitch", help="Override the profile female pitch.")
    parser.add_argument("--paragraph-pause", type=float, help="Override paragraph pause seconds.")
    parser.add_argument("--single-voice", action="store_true", help="Use the starting gender for every paragraph.")
    parser.add_argument("--force", action="store_true", help="Regenerate cached paragraph audio.")
    args = parser.parse_args()

    azure = load_module(AZURE_GENERATOR, "casevideo_azure_generator")
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    project_root = Path(args.project).expanduser().resolve()
    narration_path = project_root / "narration.txt"
    if not narration_path.exists():
        raise FileNotFoundError(narration_path)

    azure.load_env_files(project_root)
    region = azure.detect_region()
    api_key = azure.get_api_key()
    human_text = narration_path.read_text(encoding="utf-8").strip()
    normalized_text = azure.normalize_for_tts(human_text).strip()
    (project_root / "narration.tts.txt").write_text(normalized_text + "\n", encoding="utf-8")

    display_sentences = azure.build_sentence_groups(human_text)
    tts_sentences = azure.normalize_sentence_groups_for_tts(display_sentences)
    display_groups = group_sentences_by_paragraph(display_sentences)
    tts_groups = group_sentences_by_paragraph(tts_sentences)
    paragraph_count = len(display_groups)
    start_gender = args.gender or profile["startGender"]
    male_rate = args.male_rate or profile["maleRate"]
    female_rate = args.female_rate or profile["femaleRate"]
    male_pitch = args.male_pitch or profile["malePitch"]
    female_pitch = args.female_pitch or profile["femalePitch"]
    paragraph_pause = args.paragraph_pause if args.paragraph_pause is not None else profile["paragraphPauseSeconds"]
    paragraph_overrides = load_paragraph_overrides(project_root)

    cache_root = project_root / "audio" / "tts_paragraphs"
    cache_root.mkdir(parents=True, exist_ok=True)
    paragraph_records = []
    paragraph_pcm = []
    timeline_units = []
    cursor = 0.0
    alignment_totals = {"boundaryCount": 0, "alignedBoundaryCount": 0, "unmatchedBoundaryCount": 0}

    for paragraph_index in range(1, paragraph_count + 1):
        odd_gender = start_gender
        even_gender = "female" if start_gender == "male" else "male"
        gender = start_gender if args.single_voice else (odd_gender if paragraph_index % 2 else even_gender)
        voice = profile[f"{gender}Voice"]
        rate = male_rate if gender == "male" else female_rate
        pitch = male_pitch if gender == "male" else female_pitch
        override = paragraph_overrides.get(str(paragraph_index), {})
        display_pairs = display_groups[paragraph_index]
        tts_pairs = tts_groups[paragraph_index]
        display_units = [unit for _, sentence in display_pairs for unit in sentence.units]
        tts_units = [unit for _, sentence in tts_pairs for unit in sentence.units]
        paragraph_text = "".join(unit.text for unit in tts_units)
        if paragraph_text == SALES_COLUMN_OPENER:
            rate = profile.get(f"opener{gender.title()}Rate", rate)
        rate = override.get("rate", rate)
        pitch = override.get("pitch", pitch)
        pause_after = float(override.get("pauseAfterSeconds", paragraph_pause))
        synthesis_text = override.get("spokenText", paragraph_text)
        signature = paragraph_signature(
            text=synthesis_text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            region=region,
        )
        wav_path = cache_root / f"paragraph_{paragraph_index:03d}.wav"
        meta_path = cache_root / f"paragraph_{paragraph_index:03d}.json"
        cached = azure.load_json(meta_path)
        if not args.force and cached and cached.get("signature") == signature and wav_path.exists():
            pcm = azure.read_pcm_wav(wav_path)
            boundaries = cached["boundaries"]
            action = "reuse"
        else:
            ssml = build_ssml(azure, synthesis_text, voice, rate, pitch)
            pcm, boundaries = synthesize_with_retry(azure, ssml, voice, region, api_key)
            azure.write_pcm_wav(wav_path, pcm)
            meta_path.write_text(
                json.dumps(
                    {
                        "signature": signature,
                        "voice": voice,
                        "gender": gender,
                        "rate": rate,
                        "pitch": pitch,
                        "text": synthesis_text,
                        "boundaries": boundaries,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            action = "generate"

        duration = azure.frame_duration(pcm)
        local_units, stats = azure.word_boundary_timeline(
            display_units,
            tts_units,
            synthesis_text,
            boundaries,
            duration,
        )
        for key in alignment_totals:
            alignment_totals[key] += stats[key]

        sentence_by_unit = []
        for sentence_index, sentence in display_pairs:
            sentence_by_unit.extend([sentence_index] * len(sentence.units))
        for local_index, unit in enumerate(local_units):
            unit["start"] = round(float(unit["start"]) + cursor, 3)
            unit["end"] = round(float(unit["end"]) + cursor, 3)
            unit["index"] = len(timeline_units) + 1
            unit["sentence"] = sentence_by_unit[local_index]
            unit["paragraph"] = paragraph_index
            unit["voice"] = voice
            unit["voiceGender"] = gender
            unit["sentenceAudio"] = str(wav_path.relative_to(project_root))
            unit["pauseAfter"] = pause_after if local_index == len(local_units) - 1 and paragraph_index < paragraph_count else 0.0
            timeline_units.append(unit)

        paragraph_records.append(
            {
                "index": paragraph_index,
                "voice": voice,
                "gender": gender,
                "rate": rate,
                "pitch": pitch,
                "pauseAfterSeconds": pause_after if paragraph_index < paragraph_count else 0.0,
                "duration": round(duration, 3),
                "action": action,
                "audio": str(wav_path.relative_to(project_root)),
            }
        )
        paragraph_pcm.append(pcm)
        cursor += duration
        if paragraph_index < paragraph_count:
            paragraph_pcm.append(azure.silence_bytes(pause_after))
            cursor += pause_after

    output_path = project_root / "audio" / "narration_azure.wav"
    azure.write_pcm_wav(output_path, b"".join(paragraph_pcm))
    duration = azure.frame_duration(azure.read_pcm_wav(output_path))
    timeline = {
        "audio": "audio/narration_azure.wav",
        "duration": round(duration, 3),
        "engine": "azure-speech",
        "synthesisMode": "paragraph",
        "timelineTiming": "paragraph-word-boundary",
        "region": region,
        "profile": profile["name"],
        "sourceSample": profile["sourceSample"],
        "voiceMode": "single" if args.single_voice else "alternating-paragraphs",
        "voice": profile[f"{start_gender}Voice"],
        "voiceGender": start_gender,
        "secondaryVoice": None if args.single_voice else profile[f"{even_gender}Voice"],
        "secondaryVoiceGender": None if args.single_voice else even_gender,
        "maleRate": male_rate,
        "femaleRate": female_rate,
        "malePitch": male_pitch,
        "femalePitch": female_pitch,
        "paragraphPauseSeconds": paragraph_pause,
        "alignmentStats": alignment_totals,
        "units": timeline_units,
    }
    (project_root / "narration.timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (project_root / "narration.tts.plan.txt").write_text(
        "\n".join(
            f"{record['index']:03d} {record['gender']} {record['voice']} rate={record['rate']} pitch={record['pitch']} {record['action']}"
            for record in paragraph_records
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": profile,
        "project": str(project_root.relative_to(REPO_ROOT)) if project_root.is_relative_to(REPO_ROOT) else str(project_root),
        "duration": round(duration, 3),
        "paragraphs": paragraph_records,
    }
    (project_root / "audio" / "dragon_broadcast.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    storyboard_path = project_root / "rich_storyboard.json"
    if storyboard_path.exists():
        storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
        storyboard["audio"] = "audio/narration_azure.wav"
        storyboard["duration"] = round(duration, 3)
        storyboard_path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated profile={profile['name']} paragraphs={paragraph_count} duration={duration:.3f}s output={output_path}")


if __name__ == "__main__":
    main()
