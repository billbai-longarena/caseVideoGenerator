from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import argparse
import hashlib
import html
import http.client
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import wave

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent
sys.path.append(str(ENGINE_ROOT))

from tts_text_normalizer import normalize_for_tts

CLAUSE_PAUSE_SECONDS = 0.32
ENUMERATION_PAUSE_SECONDS = 0.24
SENTENCE_PAUSE_SECONDS = 0.68
PARAGRAPH_PAUSE_SECONDS = 0.95
LONG_SENTENCE_LIMIT = 30
SHORT_ENUMERATION_SPLIT_MIN_LENGTH = 16

DEFAULT_REGION = "eastus"
DEFAULT_MALE_VOICE = "zh-CN-Yunfan:DragonHDLatestNeural"
DEFAULT_FEMALE_VOICE = "zh-CN-Xiaochen:DragonHDLatestNeural"
DEFAULT_VOICE = DEFAULT_MALE_VOICE
DEFAULT_GENDER = "male"
DEFAULT_RATE = "+4%"
DEFAULT_SYNTHESIS_MODE = "sentence"
OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2
SENTENCE_RENDERING_BASE = "plain-punctuated-sentence-v2"
EXPLICIT_SENTENCE_BREAKS = {
    "钱，我来出。路，你们带着走。": (("钱，我来出", 180), ("路，你们带着走。", 0)),
}
NON_STANDALONE_BU_PHONEME = '<phoneme alphabet="sapi" ph="bu 2">不</phoneme>'
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
SEGMENT_TIMEOUT_SECONDS = 60
CONTINUOUS_TIMEOUT_SECONDS = 300
AZURE_VOICES_BY_GENDER = {
    "female": DEFAULT_FEMALE_VOICE,
    "male": DEFAULT_MALE_VOICE,
}
GENDER_ALIASES = {
    "female": "female",
    "f": "female",
    "woman": "female",
    "女": "female",
    "女声": "female",
    "male": "male",
    "m": "male",
    "man": "male",
    "男": "male",
    "男声": "male",
}


@dataclass(frozen=True)
class TtsPart:
    text: str
    pause_after: float


@dataclass(frozen=True)
class TtsUnit:
    text: str
    pause_after: float
    tts_parts: tuple[TtsPart, ...]


@dataclass(frozen=True)
class TtsSentence:
    text: str
    pause_after: float
    units: tuple[TtsUnit, ...]
    paragraph_index: int


@dataclass(frozen=True)
class VoicePlan:
    primary_voice: str
    primary_gender: str
    secondary_voice: str | None
    secondary_gender: str | None

    @property
    def mode(self) -> str:
        return "alternating-paragraphs" if self.secondary_voice else "single"

    def voice_for(self, sentence: TtsSentence) -> tuple[str, str]:
        if self.secondary_voice and sentence.paragraph_index % 2 == 0:
            return self.secondary_voice, self.secondary_gender or "custom"
        return self.primary_voice, self.primary_gender


def load_env_files(project_root: Path) -> None:
    for env_path in (REPO_ROOT / ".env", ENGINE_ROOT / ".env", project_root / ".env"):
        if not env_path.exists():
            continue
        for raw in env_path.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def split_sentences(paragraph: str) -> list[str]:
    raw_items = [
        item.strip()
        for item in re.findall(r"[^。！？!?；;]+[。！？!?；;]?[」』”’）)]*", paragraph)
        if item.strip()
    ]
    sentences: list[str] = []
    for item in raw_items:
        if re.fullmatch(r"[\"'」』”’）)]+", item) and sentences:
            sentences[-1] += item
        else:
            sentences.append(item)
    return sentences


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
    return [unit for sentence in build_sentence_groups(text) for unit in sentence.units]


def build_sentence_groups(text: str) -> list[TtsSentence]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    groups: list[TtsSentence] = []

    for paragraph_index, paragraph in enumerate(paragraphs):
        sentences = split_sentences(paragraph)
        for sentence_index, sentence in enumerate(sentences):
            parts = split_long_sentence(sentence)
            units: list[TtsUnit] = []
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
            if units:
                groups.append(TtsSentence(sentence, units[-1].pause_after, tuple(units), paragraph_index + 1))

    return groups


def normalize_units_for_alignment(display_units: list[TtsUnit]) -> list[TtsUnit]:
    units = []
    for unit in display_units:
        text = normalize_for_tts(unit.text).strip()
        units.append(TtsUnit(text, 0.0, (TtsPart(text, 0.0),)))
    return units


def normalize_sentence_groups_for_tts(display_sentences: list[TtsSentence]) -> list[TtsSentence]:
    sentences: list[TtsSentence] = []
    for sentence in display_sentences:
        units: list[TtsUnit] = []
        for unit in sentence.units:
            text = normalize_for_tts(unit.text).strip()
            units.append(TtsUnit(text, unit.pause_after, build_tts_parts(text)))
        sentence_text = normalize_for_tts(sentence.text).strip()
        sentences.append(TtsSentence(sentence_text, sentence.pause_after, tuple(units), sentence.paragraph_index))
    return sentences


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


def write_continuous_plan(path: Path, units: list[TtsUnit], *, timeline_timing: str) -> None:
    lines = [
        "mode=continuous",
        "Audio is synthesized as one full Azure Speech request.",
        f"Unit times in narration.timeline.json are {timeline_timing}.",
        "No fixed inter-unit silence is inserted before Azure TTS.",
        "",
    ]
    lines.extend(f"{index:02d}. {unit.text}" for index, unit in enumerate(units, start=1))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_sentence_plan(path: Path, sentences: list[TtsSentence]) -> None:
    lines = [
        "mode=sentence",
        "Audio is synthesized and cached by sentence under audio/tts_sentences/.",
        "Each sentence file can be regenerated independently with --only.",
        "Unit numbers remain the timeline/storyboard anchors.",
        "Azure receives each full sentence as plain punctuated text; no in-sentence SSML breaks are inserted.",
        "",
    ]
    unit_index = 1
    for sentence_index, sentence in enumerate(sentences, start=1):
        unit_start = unit_index
        unit_end = unit_index + len(sentence.units) - 1
        lines.append(
            f"S{sentence_index:03d}. sentence_{sentence_index:03d}.wav "
            f"units={unit_start:02d}-{unit_end:02d} text={sentence.text}"
        )
        for sentence_unit_index, unit in enumerate(sentence.units):
            lines.append(f"{unit_index:02d}. {unit.text}")
            if unit.pause_after > 0:
                pause_label = (
                    "sentence/paragraph pause"
                    if sentence_unit_index == len(sentence.units) - 1
                    else "timeline clause gap"
                )
                lines.append(f"    [{pause_label} {unit.pause_after:.2f}s]")
            unit_index += 1
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def detect_region() -> str:
    return os.environ.get("AZURE_SPEECH_REGION") or os.environ.get("AZURE_TTS_REGION") or DEFAULT_REGION


def normalize_gender(value: str | None) -> str:
    if not value:
        return DEFAULT_GENDER
    gender = GENDER_ALIASES.get(value.strip().lower())
    if not gender:
        expected = ", ".join(sorted(GENDER_ALIASES))
        raise ValueError(f"Unsupported Azure TTS gender '{value}'. Expected one of: {expected}")
    return gender


def infer_voice_gender(voice: str) -> str | None:
    for gender, known_voice in AZURE_VOICES_BY_GENDER.items():
        if voice == known_voice:
            return gender
    return None


def resolve_voice_plan(args: argparse.Namespace, parser: argparse.ArgumentParser) -> VoicePlan:
    try:
        explicit_gender = normalize_gender(args.gender) if args.gender else None
        env_gender = normalize_gender(os.environ.get("AZURE_TTS_GENDER")) if os.environ.get("AZURE_TTS_GENDER") else None
    except ValueError as exc:
        parser.error(str(exc))

    env_voice = os.environ.get("AZURE_TTS_VOICE")
    male_voice = os.environ.get("AZURE_TTS_MALE_VOICE", DEFAULT_MALE_VOICE)
    female_voice = os.environ.get("AZURE_TTS_FEMALE_VOICE", DEFAULT_FEMALE_VOICE)
    if args.voice:
        voice = args.voice
        primary_gender = infer_voice_gender(voice) or explicit_gender or "custom"
        if args.alternate_voice and not args.single_voice:
            return VoicePlan(
                voice,
                primary_gender,
                args.alternate_voice,
                infer_voice_gender(args.alternate_voice) or "custom",
            )
        return VoicePlan(voice, primary_gender, None, None)
    if env_voice:
        return VoicePlan(env_voice, infer_voice_gender(env_voice) or env_gender or "custom", None, None)

    starting_gender = explicit_gender or env_gender or DEFAULT_GENDER
    if starting_gender == "female":
        primary_voice, primary_gender = female_voice, "female"
        secondary_voice, secondary_gender = male_voice, "male"
    else:
        primary_voice, primary_gender = male_voice, "male"
        secondary_voice, secondary_gender = female_voice, "female"

    if args.single_voice:
        return VoicePlan(primary_voice, primary_gender, None, None)
    if args.alternate_voice:
        secondary_voice = args.alternate_voice
        secondary_gender = infer_voice_gender(secondary_voice) or "custom"
    return VoicePlan(primary_voice, primary_gender, secondary_voice, secondary_gender)


def get_api_key() -> str:
    key = (
        os.environ.get("AZURE_SPEECH_KEY")
        or os.environ.get("AZURE_TTS_API_KEY")
        or os.environ.get("AZURE_TTS_KEY")
        or os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY")
    )
    if not key:
        raise RuntimeError(
            "Azure TTS key not found. Set AZURE_SPEECH_KEY or AZURE_TTS_KEY; "
            "legacy AZURE_DOCUMENT_INTELLIGENCE_KEY is accepted for this workspace."
        )
    return key


def escape_ssml_text(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(
        r"(?<=[\u3400-\u9fff])不|不(?=[\u3400-\u9fff])",
        NON_STANDALONE_BU_PHONEME,
        escaped,
    )


def build_ssml_document(body: str, voice: str, rate: str) -> str:
    return f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
  <voice name="{html.escape(voice)}">
    <prosody rate="{html.escape(rate)}">{body}</prosody>
  </voice>
</speak>"""


def build_ssml_text(text: str, voice: str, rate: str) -> str:
    return build_ssml_document(escape_ssml_text(text), voice, rate)


def build_sentence_ssml(sentence: TtsSentence, voice: str, rate: str) -> str:
    # Sentence-cache mode intentionally sends the whole sentence as plain
    # punctuated text. Azure Speech then keeps its native phrase breaks and
    # prosody; unit splitting is only for timeline/storyboard alignment.
    explicit_break = EXPLICIT_SENTENCE_BREAKS.get(sentence.text)
    if explicit_break:
        body = "".join(
            escape_ssml_text(text) + (f'<break time="{pause_ms}ms"/>' if pause_ms > 0 else "")
            for text, pause_ms in explicit_break
        )
        return build_ssml_document(body, voice, rate)
    return build_ssml_document(escape_ssml_text(sentence.text), voice, rate)


def pcm_from_wav_bytes(wav_bytes: bytes) -> bytes:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != CHANNELS or wav.getsampwidth() != SAMPLE_WIDTH:
                raise RuntimeError(
                    "Unexpected Azure TTS WAV format: "
                    f"{wav.getframerate()}Hz channels={wav.getnchannels()} width={wav.getsampwidth()}"
                )
            return wav.readframes(wav.getnframes())
    except (EOFError, wave.Error) as exc:
        raise RuntimeError("Azure TTS returned empty or invalid WAV data") from exc


def synthesize_ssml(
    ssml: str,
    voice: str,
    region: str,
    api_key: str,
    *,
    timeout: int = SEGMENT_TIMEOUT_SECONDS,
) -> bytes:
    ssml_bytes = ssml.encode("utf-8")
    wav_bytes: bytes | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        req = urllib.request.Request(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            data=ssml_bytes,
            method="POST",
            headers={
                "Ocp-Apim-Subscription-Key": api_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                "User-Agent": "casevideo-azure-tts",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                wav_bytes = response.read()
            try:
                return pcm_from_wav_bytes(wav_bytes)
            except RuntimeError as error:
                if attempt >= RETRY_ATTEMPTS:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
        except urllib.error.HTTPError as error:
            detail = error.read(600).decode("utf-8", errors="ignore")
            raise RuntimeError(f"Azure TTS failed: http={error.code} detail={detail}") from error
        except (http.client.IncompleteRead, socket.timeout, urllib.error.URLError, TimeoutError) as error:
            if attempt >= RETRY_ATTEMPTS:
                raise RuntimeError(f"Azure TTS failed after {attempt} attempts: {error}") from error
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    if wav_bytes is None:
        raise RuntimeError("Azure TTS did not return audio bytes")

    return pcm_from_wav_bytes(wav_bytes)


def synthesize_part(
    text: str,
    voice: str,
    region: str,
    api_key: str,
    rate: str,
    *,
    timeout: int = SEGMENT_TIMEOUT_SECONDS,
) -> bytes:
    return synthesize_ssml(
        build_ssml_text(text, voice, rate),
        voice,
        region,
        api_key,
        timeout=timeout,
    )


def sentence_rendering_id(sentence: TtsSentence) -> str:
    if sentence.text in EXPLICIT_SENTENCE_BREAKS:
        return f"{SENTENCE_RENDERING_BASE}+explicit-phrase-break-v1"
    return SENTENCE_RENDERING_BASE


def synthesize_ssml_with_word_boundaries(
    ssml: str,
    voice: str,
    region: str,
    api_key: str,
) -> tuple[bytes, list[dict[str, float | int | str]]]:
    if speechsdk is None:
        raise RuntimeError(
            "Azure Speech SDK is required for word-boundary alignment. "
            "Install azure-cognitiveservices-speech or use estimated sentence timing."
        )

    speech_config = speechsdk.SpeechConfig(subscription=api_key, region=region)
    speech_config.speech_synthesis_voice_name = voice
    speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)

    boundaries: list[dict[str, float | int | str]] = []

    def on_word_boundary(event) -> None:
        boundary_type = getattr(event, "boundary_type", "")
        duration = getattr(event, "duration", None)
        boundaries.append(
            {
                "text": getattr(event, "text", ""),
                "audioOffset": round(getattr(event, "audio_offset", 0) / 10_000_000, 6),
                "duration": round(duration.total_seconds() if duration else 0.0, 6),
                "textOffset": getattr(event, "text_offset", 0),
                "wordLength": getattr(event, "word_length", 0),
                "boundaryType": getattr(boundary_type, "name", str(boundary_type)),
            }
        )

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    synthesizer.synthesis_word_boundary.connect(on_word_boundary)
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = getattr(result, "cancellation_details", None)
        if details:
            raise RuntimeError(f"Azure SDK TTS failed: reason={details.reason} detail={details.error_details}")
        raise RuntimeError(f"Azure SDK TTS failed: reason={result.reason}")

    return pcm_from_wav_bytes(bytes(result.audio_data)), boundaries


def synthesize_part_with_word_boundaries(
    text: str,
    voice: str,
    region: str,
    api_key: str,
    rate: str,
) -> tuple[bytes, list[dict[str, float | int | str]]]:
    return synthesize_ssml_with_word_boundaries(build_ssml_text(text, voice, rate), voice, region, api_key)


def silence_bytes(seconds: float) -> bytes:
    frames = int(round(SAMPLE_RATE * seconds))
    return b"\x00" * frames * CHANNELS * SAMPLE_WIDTH


def frame_duration(pcm: bytes) -> float:
    return len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


def write_pcm_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)


def read_pcm_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != SAMPLE_RATE or wav.getnchannels() != CHANNELS or wav.getsampwidth() != SAMPLE_WIDTH:
            raise RuntimeError(
                f"{path} must be {SAMPLE_RATE}Hz {CHANNELS}ch {SAMPLE_WIDTH * 8}-bit PCM WAV "
                f"(got {wav.getframerate()}Hz channels={wav.getnchannels()} width={wav.getsampwidth()})"
            )
        return wav.readframes(wav.getnframes())


def timeline_weight(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    weight = max(1, len(compact))
    if text.endswith(("。", "！", "？", "!", "?", "；", ";")):
        weight += 4
    elif text.endswith(("，", "、", "：", ":", ",")):
        weight += 2
    return float(weight)


def estimate_continuous_timeline(units: list[TtsUnit], duration: float) -> list[dict[str, float | int | str]]:
    total_weight = sum(timeline_weight(unit.text) for unit in units)
    timeline_units = []
    cursor = 0.0
    for unit_index, unit in enumerate(units, start=1):
        if unit_index == len(units):
            end = duration
        else:
            end = cursor + duration * (timeline_weight(unit.text) / total_weight)
        timeline_units.append(
            {
                "index": unit_index,
                "text": unit.text,
                "start": round(cursor, 3),
                "end": round(end, 3),
                "pauseAfter": 0.0,
            }
        )
        cursor = end
    return timeline_units


def compact_alignment_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def align_boundaries_to_text(
    boundaries: list[dict[str, float | int | str]],
    text: str,
) -> tuple[list[dict[str, float | int | str]], int, list[dict[str, float | int | str]]]:
    target = compact_alignment_text(text)
    cursor = 0
    aligned: list[dict[str, float | int | str]] = []
    unmatched: list[dict[str, float | int | str]] = []

    for boundary in boundaries:
        token = compact_alignment_text(str(boundary.get("text", "")))
        if not token:
            continue
        if target.startswith(token, cursor):
            start = cursor
        else:
            start = target.find(token, cursor)
        if start < 0:
            unmatched.append(boundary)
            continue
        end = start + len(token)
        aligned.append({**boundary, "charStart": start, "charEnd": end})
        cursor = end

    if not aligned:
        raise RuntimeError("Azure word-boundary alignment failed: no boundaries matched normalized text")
    return aligned, len(target), unmatched


def unit_alignment_spans(units: list[TtsUnit], expected_length: int) -> list[tuple[int, int]]:
    cursor = 0
    spans: list[tuple[int, int]] = []
    for unit in units:
        compact = compact_alignment_text(unit.text)
        start = cursor
        cursor += len(compact)
        spans.append((start, cursor))
    if cursor != expected_length:
        raise RuntimeError(
            "Timeline unit text does not match normalized narration length: "
            f"units={cursor} narration={expected_length}"
        )
    return spans


def word_boundary_timeline(
    display_units: list[TtsUnit],
    tts_units: list[TtsUnit],
    normalized_text: str,
    boundaries: list[dict[str, float | int | str]],
    duration: float,
) -> tuple[list[dict[str, float | int | str]], dict[str, int]]:
    if len(display_units) != len(tts_units):
        raise RuntimeError(f"Display/TTS unit mismatch: display={len(display_units)} tts={len(tts_units)}")

    aligned, target_length, unmatched = align_boundaries_to_text(boundaries, normalized_text)
    spans = unit_alignment_spans(tts_units, target_length)
    unit_starts: list[float] = []

    for unit_index, (span_start, span_end) in enumerate(spans):
        if unit_index == 0:
            unit_starts.append(0.0)
            continue

        candidates = [
            event
            for event in aligned
            if int(event["charEnd"]) > span_start
            and int(event["charStart"]) < span_end
            and event.get("boundaryType") != "Punctuation"
        ]
        if not candidates:
            candidates = [
                event
                for event in aligned
                if int(event["charEnd"]) > span_start and int(event["charStart"]) < span_end
            ]
        if candidates:
            start = float(candidates[0]["audioOffset"])
        elif unit_starts:
            start = unit_starts[-1]
        else:
            start = 0.0

        if start < unit_starts[-1]:
            start = unit_starts[-1]
        unit_starts.append(start)

    timeline_units: list[dict[str, float | int | str]] = []
    for unit_index, unit in enumerate(display_units):
        start = unit_starts[unit_index]
        end = unit_starts[unit_index + 1] if unit_index < len(unit_starts) - 1 else duration
        if end <= start:
            end = min(duration, start + 0.001)
        timeline_units.append(
            {
                "index": unit_index + 1,
                "text": unit.text,
                "start": round(start, 3),
                "end": round(end, 3),
                "pauseAfter": 0.0,
            }
        )

    return timeline_units, {
        "boundaryCount": len(boundaries),
        "alignedBoundaryCount": len(aligned),
        "unmatchedBoundaryCount": len(unmatched),
    }


def sentence_unit_timings_from_boundaries(
    display_sentence: TtsSentence,
    tts_sentence: TtsSentence,
    boundaries: list[dict[str, float | int | str]],
    duration: float,
) -> tuple[list[dict[str, float | int]], dict[str, int]]:
    if len(display_sentence.units) != len(tts_sentence.units):
        raise RuntimeError(
            "Display/TTS sentence unit mismatch: "
            f"display={len(display_sentence.units)} tts={len(tts_sentence.units)}"
        )

    normalized_text = "".join(unit.text for unit in tts_sentence.units)
    aligned, target_length, unmatched = align_boundaries_to_text(boundaries, normalized_text)
    spans = unit_alignment_spans(list(tts_sentence.units), target_length)
    unit_starts: list[float] = []

    for unit_index, (span_start, span_end) in enumerate(spans):
        if unit_index == 0:
            unit_starts.append(0.0)
            continue

        candidates = [
            event
            for event in aligned
            if int(event["charEnd"]) > span_start
            and int(event["charStart"]) < span_end
            and event.get("boundaryType") != "Punctuation"
        ]
        if not candidates:
            candidates = [
                event
                for event in aligned
                if int(event["charEnd"]) > span_start and int(event["charStart"]) < span_end
            ]
        start = float(candidates[0]["audioOffset"]) if candidates else unit_starts[-1]
        if start < unit_starts[-1]:
            start = unit_starts[-1]
        unit_starts.append(start)

    timings: list[dict[str, float | int]] = []
    for unit_index, unit in enumerate(display_sentence.units):
        start = unit_starts[unit_index]
        if unit_index < len(unit_starts) - 1:
            next_start = unit_starts[unit_index + 1]
            end = max(start, next_start - unit.pause_after)
        else:
            end = duration
        if end <= start:
            end = min(duration, start + 0.001)
        timings.append(
            {
                "unitOffset": unit_index,
                "start": round(start, 3),
                "end": round(min(end, duration), 3),
                "pauseAfter": unit.pause_after,
            }
        )

    return timings, {
        "boundaryCount": len(boundaries),
        "alignedBoundaryCount": len(aligned),
        "unmatchedBoundaryCount": len(unmatched),
    }


def estimate_sentence_unit_timings(sentence: TtsSentence, duration: float) -> list[dict[str, float | int]]:
    if not sentence.units:
        return []

    weights = [timeline_weight(unit.text) for unit in sentence.units]
    total_weight = sum(weights) or 1.0
    cursor = 0.0
    timings: list[dict[str, float | int]] = []

    for unit_index, (unit, weight) in enumerate(zip(sentence.units, weights)):
        speech = duration * weight / total_weight
        start = cursor
        end = min(duration, cursor + speech)
        timings.append(
            {
                "unitOffset": unit_index,
                "start": round(start, 3),
                "end": round(max(start + 0.001, end), 3),
                "pauseAfter": unit.pause_after,
            }
        )
        cursor = end

    return timings


def sentence_signature(sentence: TtsSentence, *, voice: str, rate: str, region: str) -> str:
    payload = {
        "engine": "azure-speech",
        "synthesisMode": "sentence",
        "rendering": sentence_rendering_id(sentence),
        "outputFormat": OUTPUT_FORMAT,
        "sampleRate": SAMPLE_RATE,
        "channels": CHANNELS,
        "sampleWidth": SAMPLE_WIDTH,
        "voice": voice,
        "rate": rate,
        "region": region,
        "text": sentence.text,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sentence_paths(sentence_dir: Path, index: int) -> dict[str, Path]:
    stem = f"sentence_{index:03d}"
    return {
        "wav": sentence_dir / f"{stem}.wav",
        "text": sentence_dir / f"{stem}.txt",
        "tts": sentence_dir / f"{stem}.tts.txt",
        "meta": sentence_dir / f"{stem}.meta.json",
    }


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def cache_matches(paths: dict[str, Path], signature: str) -> bool:
    if not paths["wav"].exists() or not paths["meta"].exists():
        return False
    meta = load_json(paths["meta"])
    return bool(meta and meta.get("signature") == signature)


def parse_index_selection(value: str | None, max_index: int) -> set[int] | None:
    if not value:
        return None
    selected: set[int] = set()
    for raw in value.split(","):
        item = raw.strip()
        if not item:
            continue
        if "-" in item:
            start_text, end_text = item.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"Invalid --only range '{item}'")
            selected.update(range(start, end + 1))
        else:
            selected.add(int(item))
    invalid = [index for index in sorted(selected) if index < 1 or index > max_index]
    if invalid:
        raise ValueError(f"--only indexes out of range 1..{max_index}: {invalid}")
    return selected


def write_sentence_cache_texts(paths: dict[str, Path], display_sentence: TtsSentence, tts_sentence: TtsSentence) -> None:
    paths["text"].write_text(display_sentence.text + "\n", encoding="utf-8")
    paths["tts"].write_text(tts_sentence.text + "\n", encoding="utf-8")


def synthesize_sentence_record(
    *,
    index: int,
    display_sentence: TtsSentence,
    tts_sentence: TtsSentence,
    paths: dict[str, Path],
    signature: str,
    voice: str,
    voice_gender: str,
    region: str,
    api_key: str,
    rate: str,
) -> dict:
    timing = "estimated"
    alignment_stats: dict[str, int] | None = None

    ssml = build_sentence_ssml(tts_sentence, voice, rate)
    if speechsdk is not None:
        try:
            pcm, boundaries = synthesize_ssml_with_word_boundaries(ssml, voice, region, api_key)
            duration = frame_duration(pcm)
            try:
                unit_timings, alignment_stats = sentence_unit_timings_from_boundaries(
                    display_sentence,
                    tts_sentence,
                    boundaries,
                    duration,
                )
                timing = "word-boundary"
            except RuntimeError:
                unit_timings = estimate_sentence_unit_timings(display_sentence, duration)
                alignment_stats = {
                    "boundaryCount": len(boundaries),
                    "alignedBoundaryCount": 0,
                    "unmatchedBoundaryCount": len(boundaries),
                }
        except RuntimeError:
            pcm = synthesize_ssml(
                ssml,
                voice,
                region,
                api_key,
                timeout=SEGMENT_TIMEOUT_SECONDS,
            )
            duration = frame_duration(pcm)
            unit_timings = estimate_sentence_unit_timings(display_sentence, duration)
    else:
        pcm = synthesize_ssml(
            ssml,
            voice,
            region,
            api_key,
            timeout=SEGMENT_TIMEOUT_SECONDS,
        )
        duration = frame_duration(pcm)
        unit_timings = estimate_sentence_unit_timings(display_sentence, duration)

    write_pcm_wav(paths["wav"], pcm)
    write_sentence_cache_texts(paths, display_sentence, tts_sentence)

    meta = {
        "index": index,
        "engine": "azure-speech",
        "synthesisMode": "sentence",
        "rendering": sentence_rendering_id(tts_sentence),
        "signature": signature,
        "audio": f"audio/tts_sentences/sentence_{index:03d}.wav",
        "text": display_sentence.text,
        "ttsText": tts_sentence.text,
        "duration": round(duration, 3),
        "pauseAfter": display_sentence.pause_after,
        "voice": voice,
        "voiceGender": voice_gender,
        "region": region,
        "rate": rate,
        "timelineTiming": timing,
        "alignmentStats": alignment_stats,
        "unitTimings": unit_timings,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    paths["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def scaled_unit_timings(meta: dict, sentence: TtsSentence, duration: float) -> list[dict[str, float | int]]:
    timings = meta.get("unitTimings")
    if not isinstance(timings, list) or len(timings) != len(sentence.units):
        return estimate_sentence_unit_timings(sentence, duration)

    original_duration = float(meta.get("duration") or duration or 0.0)
    scale = duration / original_duration if original_duration > 0 else 1.0
    scaled: list[dict[str, float | int]] = []
    for unit_index, (timing, unit) in enumerate(zip(timings, sentence.units)):
        start = float(timing.get("start", 0.0)) * scale
        end = float(timing.get("end", start + 0.001)) * scale
        if end <= start:
            end = min(duration, start + 0.001)
        scaled.append(
            {
                "unitOffset": unit_index,
                "start": round(max(0.0, start), 3),
                "end": round(min(duration, end), 3),
                "pauseAfter": unit.pause_after,
            }
        )
    return scaled


def run_sentence_mode(
    *,
    project_root: Path,
    display_sentences: list[TtsSentence],
    tts_sentences: list[TtsSentence],
    output_path: Path,
    timeline_path: Path,
    voice_plan: VoicePlan,
    region: str,
    rate: str,
    only: set[int] | None,
    force: bool,
) -> tuple[bytes, float, list[dict[str, float | int | str]], dict[str, int]]:
    if len(display_sentences) != len(tts_sentences):
        raise RuntimeError(f"Display/TTS sentence mismatch: display={len(display_sentences)} tts={len(tts_sentences)}")

    sentence_dir = project_root / "audio" / "tts_sentences"
    sentence_dir.mkdir(parents=True, exist_ok=True)

    sentence_voices = [voice_plan.voice_for(sentence) for sentence in tts_sentences]
    signatures = [
        sentence_signature(sentence, voice=sentence_voice, rate=rate, region=region)
        for sentence, (sentence_voice, _) in zip(tts_sentences, sentence_voices)
    ]
    needs_synthesis = []
    for index, signature in enumerate(signatures, start=1):
        paths = sentence_paths(sentence_dir, index)
        selected = only is not None and index in only
        if force or selected or not cache_matches(paths, signature):
            needs_synthesis.append(index)

    api_key = get_api_key() if needs_synthesis else ""
    records: list[dict] = []
    reused = 0
    generated = 0

    for index, (display_sentence, tts_sentence, signature, sentence_voice) in enumerate(
        zip(display_sentences, tts_sentences, signatures, sentence_voices),
        start=1,
    ):
        voice, voice_gender = sentence_voice
        paths = sentence_paths(sentence_dir, index)
        write_sentence_cache_texts(paths, display_sentence, tts_sentence)
        selected = only is not None and index in only
        should_generate = force or selected or not cache_matches(paths, signature)
        if should_generate:
            meta = synthesize_sentence_record(
                index=index,
                display_sentence=display_sentence,
                tts_sentence=tts_sentence,
                paths=paths,
                signature=signature,
                voice=voice,
                voice_gender=voice_gender,
                region=region,
                api_key=api_key,
                rate=rate,
            )
            generated += 1
            action = "generated"
        else:
            meta = load_json(paths["meta"])
            if meta is None:
                raise RuntimeError(f"Missing sentence metadata after cache check: {paths['meta']}")
            reused += 1
            action = "reused"

        pcm = read_pcm_wav(paths["wav"])
        duration = frame_duration(pcm)
        meta["duration"] = round(duration, 3)
        meta["action"] = action
        meta["audio"] = f"audio/tts_sentences/sentence_{index:03d}.wav"
        meta["paragraph"] = display_sentence.paragraph_index
        records.append(meta)
        print(
            f"sentence={index:03d} action={action} duration={duration:.2f}s "
            f"units={len(display_sentence.units)} text={display_sentence.text}",
            flush=True,
        )

    chunks: list[bytes] = []
    timeline_units: list[dict[str, float | int | str]] = []
    cursor = 0.0
    unit_index = 1

    for sentence_index, (display_sentence, record) in enumerate(zip(display_sentences, records), start=1):
        paths = sentence_paths(sentence_dir, sentence_index)
        pcm = read_pcm_wav(paths["wav"])
        duration = frame_duration(pcm)
        unit_timings = scaled_unit_timings(record, display_sentence, duration)
        chunks.append(pcm)

        for unit, timing in zip(display_sentence.units, unit_timings):
            start = cursor + float(timing["start"])
            end = cursor + float(timing["end"])
            timeline_units.append(
                {
                    "index": unit_index,
                    "text": unit.text,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "pauseAfter": unit.pause_after,
                    "sentence": sentence_index,
                    "paragraph": display_sentence.paragraph_index,
                    "voice": record.get("voice"),
                    "voiceGender": record.get("voiceGender"),
                    "sentenceAudio": f"audio/tts_sentences/sentence_{sentence_index:03d}.wav",
                }
            )
            unit_index += 1

        if display_sentence.pause_after > 0:
            chunks.append(silence_bytes(display_sentence.pause_after))
        cursor += duration + display_sentence.pause_after

    speech = b"".join(chunks)
    duration = frame_duration(speech)
    write_pcm_wav(output_path, speech)

    manifest = {
        "engine": "azure-speech",
        "synthesisMode": "sentence",
        "audio": "audio/narration_azure.wav",
        "timeline": str(timeline_path.relative_to(project_root)),
        "voiceMode": voice_plan.mode,
        "primaryVoice": voice_plan.primary_voice,
        "primaryVoiceGender": voice_plan.primary_gender,
        "secondaryVoice": voice_plan.secondary_voice,
        "secondaryVoiceGender": voice_plan.secondary_gender,
        "region": region,
        "rate": rate,
        "sentenceCount": len(records),
        "unitCount": len(timeline_units),
        "generatedCount": generated,
        "reusedCount": reused,
        "sentences": records,
    }
    (sentence_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return speech, duration, timeline_units, {"generatedSentenceCount": generated, "reusedSentenceCount": reused}


def normalize_mode(value: str | None) -> str:
    if not value:
        return DEFAULT_SYNTHESIS_MODE
    mode = value.strip().lower()
    aliases = {
        "sentence": "sentence",
        "sentences": "sentence",
        "sentence-cache": "sentence",
        "cached": "sentence",
        "cache": "sentence",
        "句子": "sentence",
        "continuous": "continuous",
        "full": "continuous",
        "single": "continuous",
        "azure": "continuous",
        "segmented": "segmented",
        "segments": "segmented",
        "unit": "segmented",
        "legacy": "segmented",
    }
    if mode not in aliases:
        expected = ", ".join(sorted(aliases))
        raise ValueError(f"Unsupported Azure synthesis mode '{value}'. Expected one of: {expected}")
    return aliases[mode]


def project_root_from_args() -> tuple[Path, VoicePlan, str, str, str | None, bool]:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        default=os.environ.get("VIDEO_PROJECT_DIR"),
        help="Project directory containing narration.txt and receiving audio/timeline outputs.",
    )
    parser.add_argument(
        "--gender",
        help="Starting voice gender: female/male, 女声/男声. Paragraph alternation remains enabled.",
    )
    parser.add_argument(
        "--voice",
        help="Full primary Azure voice name. Uses one voice unless --alternate-voice is also provided.",
    )
    parser.add_argument(
        "--alternate-voice",
        help="Second Azure voice used on even-numbered paragraphs. Requires sentence mode.",
    )
    parser.add_argument(
        "--single-voice",
        action="store_true",
        help="Disable the default male/female paragraph alternation.",
    )
    parser.add_argument("--rate", help="Azure SSML prosody rate, for example +4%%, 0%%, or -4%%.")
    parser.add_argument(
        "--mode",
        default=os.environ.get("AZURE_TTS_MODE"),
        help="Azure synthesis mode: sentence (default), continuous, or segmented/legacy.",
    )
    parser.add_argument(
        "--only",
        help="Regenerate only selected sentence cache slots, for example 3 or 3,5-7. Sentence mode only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all sentence cache slots even when text/voice/rate metadata matches. Sentence mode only.",
    )
    args = parser.parse_args()
    project_root = Path(args.project).expanduser().resolve() if args.project else ENGINE_ROOT
    load_env_files(project_root)
    voice_plan = resolve_voice_plan(args, parser)
    rate = args.rate or os.environ.get("AZURE_TTS_RATE", DEFAULT_RATE)
    try:
        mode = normalize_mode(args.mode)
    except ValueError as exc:
        parser.error(str(exc))
    if mode != "sentence" and voice_plan.secondary_voice:
        parser.error("Paragraph voice alternation requires sentence mode. Use --single-voice for other modes.")
    return project_root, voice_plan, rate, mode, args.only, args.force


def update_storyboard_audio(project_root: Path) -> None:
    storyboard_path = project_root / "rich_storyboard.json"
    if not storyboard_path.exists():
        return
    data = json.loads(storyboard_path.read_text(encoding="utf-8"))
    data["audio"] = "audio/narration_azure.wav"
    data["timeline"] = "narration.timeline.json"
    storyboard_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated_storyboard_audio={storyboard_path}", flush=True)


def main() -> None:
    project_root, voice_plan, rate, mode, only_arg, force = project_root_from_args()
    region = detect_region()

    text_path = project_root / "narration.txt"
    normalized_text_path = project_root / "narration.tts.txt"
    pause_plan_path = project_root / "narration.tts.plan.txt"
    timeline_path = project_root / "narration.timeline.json"
    word_boundary_path = project_root / "narration.word_boundaries.json"
    output_path = project_root / "audio" / "narration_azure.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    human_text = text_path.read_text(encoding="utf-8").strip()
    text = normalize_for_tts(human_text).strip()
    normalized_text_path.write_text(text + "\n", encoding="utf-8")
    display_sentences = build_sentence_groups(human_text)
    tts_sentences = normalize_sentence_groups_for_tts(display_sentences)
    display_units = build_tts_units(human_text)
    tts_units = [unit for sentence in tts_sentences for unit in sentence.units]
    alignment_units = [TtsUnit(unit.text, 0.0, (TtsPart(unit.text, 0.0),)) for unit in tts_units]
    if len(display_units) != len(tts_units):
        raise RuntimeError(f"Display/TTS unit mismatch: display={len(display_units)} tts={len(tts_units)}")

    start = time.time()
    print(
        f"region={region} voiceMode={voice_plan.mode} primaryVoice={voice_plan.primary_voice} "
        f"secondaryVoice={voice_plan.secondary_voice or '<none>'} rate={rate} mode={mode}",
        flush=True,
    )

    chunks: list[bytes] = []
    timeline_units = []
    timeline_timing = "estimated" if mode == "continuous" else "exact-segmented"
    alignment_stats: dict[str, int] | None = None
    if mode == "sentence":
        try:
            only = parse_index_selection(only_arg, len(display_sentences))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if only:
            print(f"sentence_selection={','.join(str(index) for index in sorted(only))}", flush=True)
        write_sentence_plan(pause_plan_path, display_sentences)
        speech, duration, timeline_units, sentence_stats = run_sentence_mode(
            project_root=project_root,
            display_sentences=display_sentences,
            tts_sentences=tts_sentences,
            output_path=output_path,
            timeline_path=timeline_path,
            voice_plan=voice_plan,
            region=region,
            rate=rate,
            only=only,
            force=force,
        )
        timeline_timing = "sentence-word-boundary" if speechsdk is not None else "sentence-estimated"
        alignment_stats = sentence_stats
        print(
            f"sentence_cache generated={sentence_stats['generatedSentenceCount']} "
            f"reused={sentence_stats['reusedSentenceCount']} duration={duration:.2f}s",
            flush=True,
        )
    elif mode == "continuous":
        api_key = get_api_key()
        voice = voice_plan.primary_voice
        write_continuous_plan(pause_plan_path, display_units, timeline_timing="word-boundary aligned")
        speech, boundaries = synthesize_part_with_word_boundaries(
            text,
            voice,
            region,
            api_key,
            rate,
        )
        duration = frame_duration(speech)
        timeline_units, alignment_stats = word_boundary_timeline(display_units, alignment_units, text, boundaries, duration)
        timeline_timing = "word-boundary"
        word_boundary_path.write_text(
            json.dumps(
                {
                    "engine": "azure-speech-sdk",
                    "voice": voice,
                    "rate": rate,
                    "duration": round(duration, 3),
                    "stats": alignment_stats,
                    "boundaries": boundaries,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"continuous_synthesis units={len(display_units)} duration={duration:.2f}s "
            f"timeline=word-boundary boundaries={alignment_stats['boundaryCount']} "
            f"aligned={alignment_stats['alignedBoundaryCount']} unmatched={alignment_stats['unmatchedBoundaryCount']}",
            flush=True,
        )
    else:
        voice = voice_plan.primary_voice
        api_key = get_api_key()
        write_pause_plan(pause_plan_path, tts_units)
        cursor = 0.0
        for unit_index, unit in enumerate(tts_units):
            unit_chunks: list[bytes] = []
            for part in unit.tts_parts:
                part_pcm = synthesize_part(
                    part.text,
                    voice,
                    region,
                    api_key,
                    rate,
                    timeout=SEGMENT_TIMEOUT_SECONDS,
                )
                unit_chunks.append(part_pcm)
                if part.pause_after > 0:
                    unit_chunks.append(silence_bytes(part.pause_after))
            unit_pcm = b"".join(unit_chunks)
            chunks.append(unit_pcm)
            if unit.pause_after > 0:
                chunks.append(silence_bytes(unit.pause_after))

            seconds = frame_duration(unit_pcm)
            timeline_units.append(
                {
                    "index": unit_index + 1,
                    "text": unit.text,
                    "start": round(cursor, 3),
                    "end": round(cursor + seconds, 3),
                    "pauseAfter": unit.pause_after,
                }
            )
            cursor += seconds + unit.pause_after
            print(
                f"unit={unit_index + 1:02d} speech={seconds:.2f}s pause={unit.pause_after:.2f}s "
                f"parts={len(unit.tts_parts)} text={unit.text}",
                flush=True,
            )
        speech = b"".join(chunks)
        duration = frame_duration(speech)

    if mode != "sentence":
        write_pcm_wav(output_path, speech)

    timeline_path.write_text(
        json.dumps(
            {
                "audio": "audio/narration_azure.wav",
                "duration": round(duration, 3),
                "engine": "azure-speech",
                "synthesisMode": mode,
                "timelineTiming": timeline_timing,
                "region": region,
                "voiceMode": voice_plan.mode,
                "voice": voice_plan.primary_voice,
                "voiceGender": voice_plan.primary_gender,
                "secondaryVoice": voice_plan.secondary_voice,
                "secondaryVoiceGender": voice_plan.secondary_gender,
                "rate": rate,
                "alignmentStats": alignment_stats,
                "units": timeline_units,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    update_storyboard_audio(project_root)
    elapsed = time.time() - start
    print(f"timeline={timeline_path}", flush=True)
    print(f"saved={output_path}", flush=True)
    print(f"duration={duration:.2f}", flush=True)
    print(f"elapsed={elapsed:.2f}", flush=True)


if __name__ == "__main__":
    main()
