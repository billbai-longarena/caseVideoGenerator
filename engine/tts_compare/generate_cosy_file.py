from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
COSY_ROOT = ROOT / "tts_compare" / "CosyVoice"
sys.path.append(str(ROOT))
sys.path.append(str(COSY_ROOT))
sys.path.append(str(COSY_ROOT / "third_party" / "Matcha-TTS"))

import torch
import torchaudio
from cosyvoice.cli.cosyvoice import AutoModel
from tts_text_normalizer import normalize_for_tts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speaker", default="中文女")
    args = parser.parse_args()

    normalized_path = args.input.with_suffix(".tts.txt")
    text = normalize_for_tts(args.input.read_text(encoding="utf-8")).strip()
    normalized_path.write_text(text + "\n", encoding="utf-8")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    model = AutoModel(model_dir=str(COSY_ROOT / "pretrained_models" / "CosyVoice-300M-SFT"))

    chunks = []
    for index, item in enumerate(model.inference_sft(text, args.speaker, stream=False)):
        speech = item["tts_speech"]
        chunks.append(speech)
        seconds = speech.shape[-1] / model.sample_rate
        print(f"chunk={index} seconds={seconds:.2f}", flush=True)

    if not chunks:
        raise RuntimeError("CosyVoice returned no audio chunks")

    speech = torch.cat(chunks, dim=-1)
    torchaudio.save(str(args.output), speech, model.sample_rate)
    elapsed = time.time() - start
    duration = speech.shape[-1] / model.sample_rate
    print(f"normalized={normalized_path}", flush=True)
    print(f"saved={args.output}", flush=True)
    print(f"duration={duration:.2f}", flush=True)
    print(f"elapsed={elapsed:.2f}", flush=True)


if __name__ == "__main__":
    main()
