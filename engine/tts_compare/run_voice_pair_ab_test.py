#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import azure.cognitiveservices.speech as speechsdk


SCRIPT_ROOT = Path(__file__).resolve().parent
ENGINE_ROOT = SCRIPT_ROOT.parent
REPO_ROOT = ENGINE_ROOT.parent
AZURE_GENERATOR = SCRIPT_ROOT / "generate_azure_full.py"
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHANNELS = 1
PARAGRAPH_PAUSE_SECONDS = 0.45


@dataclass(frozen=True)
class VoicePair:
    key: str
    label: str
    odd_voice: str
    even_voice: str


VOICE_PAIRS = (
    VoicePair(
        key="dragon_hd",
        label="Yunfan Dragon HD Latest + Xiaochen Dragon HD Latest",
        odd_voice="zh-CN-Yunfan:DragonHDLatestNeural",
        even_voice="zh-CN-Xiaochen:DragonHDLatestNeural",
    ),
    VoicePair(
        key="multilingual",
        label="Yunfan Multilingual + Xiaoyu Multilingual",
        odd_voice="zh-CN-YunfanMultilingualNeural",
        even_voice="zh-CN-XiaoyuMultilingualNeural",
    ),
    VoicePair(
        key="requested_xiaochen_xiaoyu",
        label="Xiaochen Multilingual + Xiaoyu Multilingual (both female)",
        odd_voice="zh-CN-XiaochenMultilingualNeural",
        even_voice="zh-CN-XiaoyuMultilingualNeural",
    ),
)


def load_azure_generator():
    spec = importlib.util.spec_from_file_location("casevideo_azure_generator", AZURE_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {AZURE_GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def split_paragraphs(text: str) -> list[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def paragraph_signature(*, text: str, voice: str, rate: str, pitch: str) -> str:
    payload = json.dumps(
        {"text": text, "voice": voice, "rate": rate, "pitch": pitch, "sampleRate": SAMPLE_RATE},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def synthesize_paragraph(
    *,
    speech_config: speechsdk.SpeechConfig,
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    output_path: Path,
) -> float:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
  <voice name="{voice}"><prosody rate="{rate}" pitch="{pitch}">{escaped}</prosody></voice>
</speak>'''
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = speechsdk.SpeechSynthesisCancellationDetails.from_result(result)
        raise RuntimeError(
            f"Azure synthesis failed for {voice}: reason={details.reason} "
            f"code={details.error_code} details={details.error_details}"
        )
    return wav_duration(output_path)


def append_silence(output: wave.Wave_write, seconds: float) -> None:
    frame_count = math.ceil(SAMPLE_RATE * seconds)
    output.writeframes(b"\x00" * frame_count * SAMPLE_WIDTH * CHANNELS)


def concatenate_wavs(inputs: list[Path], output_path: Path, paragraph_pause_seconds: float) -> float:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(CHANNELS)
        output.setsampwidth(SAMPLE_WIDTH)
        output.setframerate(SAMPLE_RATE)
        for index, input_path in enumerate(inputs):
            with wave.open(str(input_path), "rb") as source:
                params = (source.getnchannels(), source.getsampwidth(), source.getframerate())
                if params != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE):
                    raise RuntimeError(f"Unexpected WAV format for {input_path}: {params}")
                output.writeframes(source.readframes(source.getnframes()))
            if index < len(inputs) - 1:
                append_silence(output, paragraph_pause_seconds)
    return wav_duration(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate alternating-paragraph Azure voice-pair A/B samples.")
    parser.add_argument(
        "--script",
        default=str(REPO_ROOT / "output" / "azure_voice_pair_ab_test" / "script.txt"),
        help="UTF-8 text file with paragraphs separated by blank lines.",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "output" / "azure_voice_pair_ab_test"),
        help="Output directory for WAV files and manifest.",
    )
    parser.add_argument("--rate", default="+7%", help="Fallback Azure prosody rate.")
    parser.add_argument("--odd-rate", default="+14%", help="Odd-paragraph voice rate.")
    parser.add_argument("--even-rate", default="+7%", help="Even-paragraph voice rate.")
    parser.add_argument("--odd-pitch", default="+4%", help="Odd-paragraph voice pitch.")
    parser.add_argument("--even-pitch", default="+1%", help="Even-paragraph voice pitch.")
    parser.add_argument(
        "--paragraph-pause",
        type=float,
        default=PARAGRAPH_PAUSE_SECONDS,
        help="Silence inserted between paragraphs in seconds.",
    )
    parser.add_argument(
        "--pair",
        choices=[pair.key for pair in VOICE_PAIRS],
        action="append",
        help="Generate only the selected voice pair. May be repeated.",
    )
    args = parser.parse_args()

    script_path = Path(args.script).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()
    paragraphs = split_paragraphs(script_path.read_text(encoding="utf-8"))
    if len(paragraphs) < 2:
        raise RuntimeError("The test script must contain at least two paragraphs.")

    azure_generator = load_azure_generator()
    azure_generator.load_env_files(output_root)
    region = azure_generator.detect_region()
    speech_config = speechsdk.SpeechConfig(subscription=azure_generator.get_api_key(), region=region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
    )

    manifest: dict[str, object] = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script": str(script_path.relative_to(REPO_ROOT)),
        "scriptSha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "region": region,
        "rate": args.rate,
        "oddRate": args.odd_rate or args.rate,
        "evenRate": args.even_rate or args.rate,
        "oddPitch": args.odd_pitch,
        "evenPitch": args.even_pitch,
        "paragraphPauseSeconds": args.paragraph_pause,
        "paragraphCount": len(paragraphs),
        "pairs": [],
    }

    selected_pairs = [pair for pair in VOICE_PAIRS if not args.pair or pair.key in args.pair]
    for pair in selected_pairs:
        pair_root = output_root / "audio" / pair.key
        paragraph_paths: list[Path] = []
        paragraph_records: list[dict[str, object]] = []
        for index, paragraph in enumerate(paragraphs, start=1):
            voice = pair.odd_voice if index % 2 else pair.even_voice
            paragraph_rate = (args.odd_rate or args.rate) if index % 2 else (args.even_rate or args.rate)
            paragraph_pitch = args.odd_pitch if index % 2 else args.even_pitch
            paragraph_path = pair_root / f"paragraph_{index:02d}.wav"
            paragraph_meta_path = pair_root / f"paragraph_{index:02d}.json"
            signature = paragraph_signature(
                text=paragraph,
                voice=voice,
                rate=paragraph_rate,
                pitch=paragraph_pitch,
            )
            cached_meta = None
            if paragraph_meta_path.exists():
                cached_meta = json.loads(paragraph_meta_path.read_text(encoding="utf-8"))
            if (
                paragraph_path.exists()
                and paragraph_path.stat().st_size > 44
                and cached_meta
                and cached_meta.get("signature") == signature
            ):
                duration = wav_duration(paragraph_path)
                action = "reuse"
            else:
                duration = synthesize_paragraph(
                    speech_config=speech_config,
                    text=paragraph,
                    voice=voice,
                    rate=paragraph_rate,
                    pitch=paragraph_pitch,
                    output_path=paragraph_path,
                )
                action = "generate"
                paragraph_meta_path.write_text(
                    json.dumps(
                        {
                            "signature": signature,
                            "voice": voice,
                            "rate": paragraph_rate,
                            "pitch": paragraph_pitch,
                            "text": paragraph,
                            "durationSeconds": round(duration, 3),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            paragraph_paths.append(paragraph_path)
            paragraph_records.append(
                {
                    "index": index,
                    "voice": voice,
                    "text": paragraph,
                    "durationSeconds": round(duration, 3),
                    "audio": str(paragraph_path.relative_to(output_root)),
                }
            )
            print(
                f"pair={pair.key} paragraph={index} action={action} "
                f"voice={voice} duration={duration:.2f}s",
                flush=True,
            )

        combined_path = output_root / "audio" / f"{pair.key}.wav"
        total_duration = concatenate_wavs(paragraph_paths, combined_path, args.paragraph_pause)
        manifest["pairs"].append(
            {
                "key": pair.key,
                "label": pair.label,
                "oddParagraphVoice": pair.odd_voice,
                "evenParagraphVoice": pair.even_voice,
                "durationSeconds": round(total_duration, 3),
                "audio": str(combined_path.relative_to(output_root)),
                "paragraphs": paragraph_records,
            }
        )
        print(f"pair={pair.key} combined={combined_path} duration={total_duration:.2f}s", flush=True)

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={manifest_path}", flush=True)


if __name__ == "__main__":
    main()
