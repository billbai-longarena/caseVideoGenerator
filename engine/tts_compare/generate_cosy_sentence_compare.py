#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
ENGINE_ROOT = SCRIPT_ROOT.parent
COSY_ROOT = SCRIPT_ROOT / "CosyVoice"
sys.path.append(str(ENGINE_ROOT))
sys.path.append(str(COSY_ROOT))
sys.path.append(str(COSY_ROOT / "third_party" / "Matcha-TTS"))

import torch
import torchaudio
from cosyvoice.cli.cosyvoice import AutoModel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a CosyVoice comparison track using the current Azure sentence manifest.",
    )
    parser.add_argument("--project", required=True, help="Project containing audio/tts_sentences/manifest.json.")
    parser.add_argument("--speaker", default="中文男")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--model",
        default="CosyVoice-300M-SFT",
        help="Model directory name under CosyVoice/pretrained_models.",
    )
    parser.add_argument(
        "--variant",
        default="sentence",
        help="Output suffix used for the narration file and sentence cache directory.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def silence_like(speech: torch.Tensor, sample_rate: int, seconds: float) -> torch.Tensor:
    sample_count = int(round(sample_rate * seconds))
    return speech.new_zeros((speech.shape[0], max(sample_count, 0)))


def signature(text: str, speaker: str, speed: float, model_name: str) -> str:
    value = json.dumps(
        {"text": text, "speaker": speaker, "speed": speed, "model": model_name},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    args = parse_args()
    project_root = Path(args.project).expanduser().resolve()
    azure_manifest_path = project_root / "audio" / "tts_sentences" / "manifest.json"
    cache_root = project_root / "audio" / f"tts_sentences_cosyvoice_{args.variant}"
    output_path = project_root / "audio" / f"narration_cosyvoice_{args.variant}.wav"
    cache_root.mkdir(parents=True, exist_ok=True)

    azure_manifest = json.loads(azure_manifest_path.read_text(encoding="utf-8"))
    sentences = azure_manifest.get("sentences", [])
    if not sentences:
        raise RuntimeError(f"No Azure sentence records found in {azure_manifest_path}")

    model_path = COSY_ROOT / "pretrained_models" / args.model
    started_at = time.time()
    model = AutoModel(model_dir=str(model_path))
    print(
        f"sentences={len(sentences)} speaker={args.speaker} speed={args.speed} model={args.model}",
        flush=True,
    )

    assembled_chunks: list[torch.Tensor] = []
    cosy_records: list[dict[str, object]] = []
    cursor = 0.0

    for sentence in sentences:
        index = int(sentence["index"])
        text = str(sentence.get("ttsText") or sentence["text"]).strip()
        pause_after = float(sentence.get("pauseAfter", 0.0))
        wav_path = cache_root / f"sentence_{index:03d}.wav"
        meta_path = cache_root / f"sentence_{index:03d}.meta.json"
        expected_signature = signature(text, args.speaker, args.speed, args.model)
        action = "generated"

        if not args.force and wav_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("signature") == expected_signature:
                speech, sample_rate = torchaudio.load(str(wav_path))
                if sample_rate != model.sample_rate:
                    raise RuntimeError(f"Unexpected cache sample rate for {wav_path}: {sample_rate}")
                action = "reused"
            else:
                speech = None
        else:
            speech = None

        if speech is None:
            sentence_chunks = [
                item["tts_speech"]
                for item in model.inference_sft(text, args.speaker, stream=False, speed=args.speed)
            ]
            if not sentence_chunks:
                raise RuntimeError(f"CosyVoice returned no audio for sentence {index}: {text}")
            speech = torch.cat(sentence_chunks, dim=-1)
            torchaudio.save(str(wav_path), speech, model.sample_rate)

        duration = speech.shape[-1] / model.sample_rate
        record = {
            "index": index,
            "engine": "cosyvoice",
            "synthesisMode": "sentence",
            "signature": expected_signature,
            "audio": f"audio/tts_sentences_cosyvoice_{args.variant}/sentence_{index:03d}.wav",
            "text": sentence["text"],
            "ttsText": text,
            "duration": round(duration, 3),
            "pauseAfter": pause_after,
            "speaker": args.speaker,
            "speed": args.speed,
            "model": args.model,
            "action": action,
        }
        meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cosy_records.append(record)
        assembled_chunks.append(speech)
        if pause_after > 0:
            assembled_chunks.append(silence_like(speech, model.sample_rate, pause_after))
        cursor += duration + pause_after
        print(
            f"sentence={index:03d} action={action} duration={duration:.2f}s "
            f"pause={pause_after:.2f}s text={sentence['text']}",
            flush=True,
        )

    full_speech = torch.cat(assembled_chunks, dim=-1)
    torchaudio.save(str(output_path), full_speech, model.sample_rate)
    duration = full_speech.shape[-1] / model.sample_rate
    manifest = {
        "engine": "cosyvoice",
        "synthesisMode": "sentence",
        "sourceManifest": "audio/tts_sentences/manifest.json",
        "audio": f"audio/narration_cosyvoice_{args.variant}.wav",
        "duration": round(duration, 3),
        "sentenceCount": len(cosy_records),
        "speaker": args.speaker,
        "speed": args.speed,
        "model": args.model,
        "sentences": cosy_records,
    }
    (cache_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"saved={output_path}", flush=True)
    print(f"manifest={cache_root / 'manifest.json'}", flush=True)
    print(f"duration={duration:.2f}s elapsed={time.time() - started_at:.2f}s", flush=True)


if __name__ == "__main__":
    main()
