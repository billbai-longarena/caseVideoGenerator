from pathlib import Path
from dataclasses import dataclass
import argparse
import json
import os
import re
import sys
import time

ENGINE_ROOT = Path(__file__).resolve().parents[1]
COSY_ROOT = ENGINE_ROOT / "tts_compare" / "CosyVoice"
sys.path.append(str(ENGINE_ROOT))
sys.path.append(str(COSY_ROOT))
sys.path.append(str(COSY_ROOT / "third_party" / "Matcha-TTS"))

import torch
import torchaudio
from cosyvoice.cli.cosyvoice import AutoModel
from tts_text_normalizer import normalize_for_tts

CLAUSE_PAUSE_SECONDS = 0.32
ENUMERATION_PAUSE_SECONDS = 0.24
SENTENCE_PAUSE_SECONDS = 0.68
PARAGRAPH_PAUSE_SECONDS = 0.95
LONG_SENTENCE_LIMIT = 30
SHORT_ENUMERATION_SPLIT_MIN_LENGTH = 16


@dataclass(frozen=True)
class TtsPart:
    text: str
    pause_after: float


@dataclass(frozen=True)
class TtsUnit:
    text: str
    pause_after: float
    tts_parts: tuple[TtsPart, ...]


def split_sentences(paragraph: str) -> list[str]:
    return [
        item.strip()
        for item in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", paragraph)
        if item.strip()
    ]


def split_long_sentence(sentence: str) -> list[str]:
    if len(sentence) <= LONG_SENTENCE_LIMIT and "：" not in sentence and ":" not in sentence:
        return [sentence]

    pieces = re.split(r"([，、：,:])", sentence)
    units: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        current += piece
        if piece in "，、：,:" and len(current) >= 12:
            units.append(current.strip())
            current = ""
    if current.strip():
        units.append(current.strip())

    if len(units) <= 1:
        return [sentence]

    merged: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        if len(current) < 10:
            current += unit
        else:
            merged.append(current)
            current = unit
    if current:
        merged.append(current)

    return merged


def build_tts_parts(unit_text: str) -> tuple[TtsPart, ...]:
    if "、" not in unit_text or len(unit_text) < SHORT_ENUMERATION_SPLIT_MIN_LENGTH:
        return (TtsPart(unit_text, 0.0),)

    pieces = re.split(r"(、)", unit_text)
    parts: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        current += piece
        if piece == "、" and len(current) >= 6:
            parts.append(current.strip())
            current = ""
    if current.strip():
        parts.append(current.strip())

    if len(parts) <= 1:
        return (TtsPart(unit_text, 0.0),)

    return tuple(
        TtsPart(part, ENUMERATION_PAUSE_SECONDS if index < len(parts) - 1 else 0.0)
        for index, part in enumerate(parts)
    )


def build_tts_units(text: str) -> list[TtsUnit]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[TtsUnit] = []

    for paragraph_index, paragraph in enumerate(paragraphs):
        sentences = split_sentences(paragraph)
        for sentence_index, sentence in enumerate(sentences):
            parts = split_long_sentence(sentence)
            for part_index, part in enumerate(parts):
                is_last_part = part_index == len(parts) - 1
                is_last_sentence = sentence_index == len(sentences) - 1
                is_last_paragraph = paragraph_index == len(paragraphs) - 1
                is_last_unit = is_last_part and is_last_sentence and is_last_paragraph

                if is_last_unit:
                    pause = 0.0
                elif is_last_part and is_last_sentence:
                    pause = PARAGRAPH_PAUSE_SECONDS
                elif is_last_part:
                    pause = SENTENCE_PAUSE_SECONDS
                elif part.endswith("、"):
                    pause = ENUMERATION_PAUSE_SECONDS
                else:
                    pause = CLAUSE_PAUSE_SECONDS

                units.append(TtsUnit(part, pause, build_tts_parts(part)))

    return units


def write_pause_plan(path: Path, units: list[TtsUnit]) -> None:
    lines = []
    for index, unit in enumerate(units, start=1):
        lines.append(f"{index:02d}. {unit.text}")
        if len(unit.tts_parts) > 1:
            for part in unit.tts_parts:
                lines.append(f"    tts: {part.text}")
                if part.pause_after > 0:
                    lines.append(f"        [inner pause {part.pause_after:.2f}s]")
        if unit.pause_after > 0:
            lines.append(f"    [pause {unit.pause_after:.2f}s]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def silence_like(speech: torch.Tensor, sample_rate: int, seconds: float) -> torch.Tensor:
    samples = int(round(sample_rate * seconds))
    if samples <= 0:
        return speech.new_zeros((speech.shape[0], 0))
    return speech.new_zeros((speech.shape[0], samples))


def project_root_from_args() -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        default=os.environ.get("VIDEO_PROJECT_DIR"),
        help="Project directory containing narration.txt and receiving audio/timeline outputs.",
    )
    args = parser.parse_args()
    if args.project:
        return Path(args.project).expanduser().resolve()
    return ENGINE_ROOT


def main() -> None:
    project_root = project_root_from_args()
    text_path = project_root / "narration.txt"
    normalized_text_path = project_root / "narration.tts.txt"
    pause_plan_path = project_root / "narration.tts.plan.txt"
    timeline_path = project_root / "narration.timeline.json"
    output_path = project_root / "audio" / "narration_cosyvoice.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = normalize_for_tts(text_path.read_text(encoding="utf-8")).strip()
    normalized_text_path.write_text(text + "\n", encoding="utf-8")
    units = build_tts_units(text)
    write_pause_plan(pause_plan_path, units)
    start = time.time()
    model = AutoModel(model_dir=str(COSY_ROOT / "pretrained_models" / "CosyVoice-300M-SFT"))
    speaker = os.environ.get("COSYVOICE_SPEAKER", "中文女")
    speed = float(os.environ.get("COSYVOICE_SPEED", "1.0"))
    print(f"speaker={speaker} speed={speed}", flush=True)

    chunks = []
    timeline_units = []
    cursor = 0.0
    for unit_index, unit in enumerate(units):
        unit_segments = []
        for part in unit.tts_parts:
            part_chunks = []
            for item in model.inference_sft(part.text, speaker, stream=False, speed=speed):
                part_chunks.append(item["tts_speech"])
            if not part_chunks:
                raise RuntimeError(f"CosyVoice returned no audio for unit {unit_index}: {part.text}")
            part_speech = torch.cat(part_chunks, dim=-1)
            unit_segments.append(part_speech)
            if part.pause_after > 0:
                unit_segments.append(silence_like(part_speech, model.sample_rate, part.pause_after))

        unit_speech = torch.cat(unit_segments, dim=-1)
        chunks.append(unit_speech)
        if unit.pause_after > 0:
            chunks.append(silence_like(unit_speech, model.sample_rate, unit.pause_after))

        seconds = unit_speech.shape[-1] / model.sample_rate
        timeline_units.append({
            "index": unit_index + 1,
            "text": unit.text,
            "start": round(cursor, 3),
            "end": round(cursor + seconds, 3),
            "pauseAfter": unit.pause_after,
        })
        cursor += seconds + unit.pause_after
        print(
            f"unit={unit_index:02d} speech={seconds:.2f}s pause={unit.pause_after:.2f}s "
            f"parts={len(unit.tts_parts)} text={unit.text}",
            flush=True,
        )

    if not chunks:
        raise RuntimeError("CosyVoice returned no audio chunks")

    speech = torch.cat(chunks, dim=-1)
    torchaudio.save(str(output_path), speech, model.sample_rate)
    elapsed = time.time() - start
    duration = speech.shape[-1] / model.sample_rate
    timeline_path.write_text(
        json.dumps(
            {
                "audio": "audio/narration_cosyvoice.wav",
                "duration": round(duration, 3),
                "speaker": speaker,
                "speed": speed,
                "units": timeline_units,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"timeline={timeline_path}", flush=True)
    print(f"saved={output_path}", flush=True)
    print(f"duration={duration:.2f}", flush=True)
    print(f"elapsed={elapsed:.2f}", flush=True)


if __name__ == "__main__":
    main()
