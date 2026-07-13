from pathlib import Path
import argparse
import gc
import json
import sys
import time

ENGINE_ROOT = Path(__file__).resolve().parents[1]
COSY_ROOT = ENGINE_ROOT / "tts_compare" / "CosyVoice"
sys.path.append(str(ENGINE_ROOT))
sys.path.append(str(COSY_ROOT))
sys.path.append(str(COSY_ROOT / "third_party" / "Matcha-TTS"))

import torch
import torchaudio
from modelscope import snapshot_download

from cosyvoice.cli.cosyvoice import AutoModel
from generate_cosy_full import build_tts_units, silence_like
from tts_text_normalizer import normalize_for_tts


SAMPLE_TEXT = """为什么老客户会被低价样机打动？为什么医院明明在采购机器，却总像还有一件更大的事没有说出来？

于是她去拜访了一位临床主任。主任提到一个关键人物：医院书记，同时也是教学院长。

这位书记快要退休了。他现在最关心的，不是再多买几台设备，而是年轻医生培养、学术水平和教学能力。
"""

PROMPT_TEXT = "希望你以后能够做的比我还好呦。"
PROMPT_WAV = COSY_ROOT / "asset" / "zero_shot_prompt.wav"
BUSINESS_MALE_PROMPT_TEXT = "销售不复杂，帮你揭开销售的魔法秘密，让销售不再复杂。"


VARIANTS = {
    "a": {
        "label": "A-current-cosyvoice-300m-sft",
        "mode": "sft",
        "local_name": "CosyVoice-300M-SFT",
        "model_ids": [],
        "output": "a_cosyvoice_300m_sft.wav",
        "speaker": "中文女",
    },
    "b": {
        "label": "B-cosyvoice2-0.5b-zero-shot",
        "mode": "zero_shot",
        "local_name": "CosyVoice2-0.5B",
        "model_ids": ["iic/CosyVoice2-0.5B"],
        "output": "b_cosyvoice2_0_5b_zero_shot.wav",
        "prompt": "default",
    },
    "c": {
        "label": "C-cosyvoice3-0.5b-zero-shot",
        "mode": "zero_shot_cosy3",
        "local_name": "Fun-CosyVoice3-0.5B-2512",
        "model_ids": ["FunAudioLLM/Fun-CosyVoice3-0.5B-2512", "FunAudioLLM/Fun-CosyVoice3-0.5B"],
        "output": "c_cosyvoice3_0_5b_zero_shot.wav",
        "prompt": "default",
    },
    "bm": {
        "label": "B-cosyvoice2-0.5b-zero-shot-business-male",
        "mode": "zero_shot",
        "local_name": "CosyVoice2-0.5B",
        "model_ids": ["iic/CosyVoice2-0.5B"],
        "output": "b_cosyvoice2_0_5b_business_male.wav",
        "prompt": "business_male_a_sft",
    },
    "cm": {
        "label": "C-cosyvoice3-0.5b-zero-shot-business-male",
        "mode": "zero_shot_cosy3",
        "local_name": "Fun-CosyVoice3-0.5B-2512",
        "model_ids": ["FunAudioLLM/Fun-CosyVoice3-0.5B-2512", "FunAudioLLM/Fun-CosyVoice3-0.5B"],
        "output": "c_cosyvoice3_0_5b_business_male.wav",
        "prompt": "business_male_a_sft",
    },
}

VARIANT_ORDER = ("a", "b", "c", "bm", "cm")


def has_model_yaml(path: Path) -> bool:
    return any((path / name).exists() for name in ("cosyvoice.yaml", "cosyvoice2.yaml", "cosyvoice3.yaml"))


def resolve_model_dir(spec: dict[str, object]) -> Path:
    local_dir = COSY_ROOT / "pretrained_models" / str(spec["local_name"])
    if has_model_yaml(local_dir):
        return local_dir
    model_ids = list(spec["model_ids"])
    if not model_ids:
        raise FileNotFoundError(f"missing local model: {local_dir}")
    errors: list[str] = []
    for index, model_id in enumerate(model_ids):
        target = local_dir if index == 0 else COSY_ROOT / "pretrained_models" / model_id.split("/")[-1]
        if has_model_yaml(target):
            return target
        try:
            print(f"download model_id={model_id} local_dir={target}", flush=True)
            downloaded = Path(snapshot_download(model_id, local_dir=str(target)))
            if has_model_yaml(downloaded):
                return downloaded
            errors.append(f"{model_id}: downloaded but no cosyvoice yaml at {downloaded}")
        except Exception as exc:
            errors.append(f"{model_id}: {exc}")
    raise RuntimeError("model download failed:\n" + "\n".join(errors))


def ensure_business_male_prompt(output_dir: Path) -> Path:
    prompt_path = output_dir / "prompt_business_male_a_sft.wav"
    if prompt_path.exists():
        return prompt_path

    model_dir = resolve_model_dir(VARIANTS["a"])
    print(f"create business male prompt={prompt_path} model_dir={model_dir}", flush=True)
    prompt_model = AutoModel(model_dir=str(model_dir))
    chunks = []
    for item in prompt_model.inference_sft(BUSINESS_MALE_PROMPT_TEXT, "中文男", stream=False):
        chunks.append(item["tts_speech"])
    if not chunks:
        raise RuntimeError("business male prompt generation produced no audio")
    speech = torch.cat(chunks, dim=-1)
    torchaudio.save(str(prompt_path), speech, prompt_model.sample_rate)
    del prompt_model
    gc.collect()
    return prompt_path


def resolve_prompt(spec: dict[str, object], output_dir: Path) -> tuple[str, Path]:
    prompt = spec.get("prompt", "default")
    if prompt == "default":
        return PROMPT_TEXT, PROMPT_WAV
    if prompt == "business_male_a_sft":
        return BUSINESS_MALE_PROMPT_TEXT, ensure_business_male_prompt(output_dir)
    raise ValueError(f"unknown prompt: {prompt}")


def render_variant(key: str, spec: dict[str, object], units, output_dir: Path) -> dict[str, object]:
    model_dir = resolve_model_dir(spec)
    print(f"load variant={key} model_dir={model_dir}", flush=True)
    model = AutoModel(model_dir=str(model_dir))
    prompt_text, prompt_wav = resolve_prompt(spec, output_dir)
    chunks = []
    timeline_units = []
    cursor = 0.0
    start = time.time()

    for unit_index, unit in enumerate(units, start=1):
        unit_segments = []
        for part in unit.tts_parts:
            part_chunks = []
            if spec["mode"] == "sft":
                for item in model.inference_sft(part.text, str(spec.get("speaker", "中文女")), stream=False):
                    part_chunks.append(item["tts_speech"])
            elif spec["mode"] == "zero_shot":
                for item in model.inference_zero_shot(
                    part.text,
                    prompt_text,
                    str(prompt_wav),
                    stream=False,
                ):
                    part_chunks.append(item["tts_speech"])
            elif spec["mode"] == "zero_shot_cosy3":
                for item in model.inference_zero_shot(
                    part.text,
                    f"You are a helpful assistant.<|endofprompt|>{prompt_text}",
                    str(prompt_wav),
                    stream=False,
                ):
                    part_chunks.append(item["tts_speech"])
            else:
                raise ValueError(f"unknown mode: {spec['mode']}")

            if not part_chunks:
                raise RuntimeError(f"{key}: no audio for unit {unit_index}: {part.text}")
            part_speech = torch.cat(part_chunks, dim=-1)
            unit_segments.append(part_speech)
            if part.pause_after > 0:
                unit_segments.append(silence_like(part_speech, model.sample_rate, part.pause_after))

        unit_speech = torch.cat(unit_segments, dim=-1)
        chunks.append(unit_speech)
        if unit.pause_after > 0:
            chunks.append(silence_like(unit_speech, model.sample_rate, unit.pause_after))

        seconds = unit_speech.shape[-1] / model.sample_rate
        timeline_units.append(
            {
                "index": unit_index,
                "text": unit.text,
                "start": round(cursor, 3),
                "end": round(cursor + seconds, 3),
                "pauseAfter": unit.pause_after,
                "ttsParts": [
                    {"text": part.text, "pauseAfter": part.pause_after}
                    for part in unit.tts_parts
                ],
            }
        )
        cursor += seconds + unit.pause_after
        print(
            f"{key} unit={unit_index:02d} speech={seconds:.2f}s pause={unit.pause_after:.2f}s "
            f"parts={len(unit.tts_parts)} text={unit.text}",
            flush=True,
        )

    speech = torch.cat(chunks, dim=-1)
    output_path = output_dir / str(spec["output"])
    torchaudio.save(str(output_path), speech, model.sample_rate)
    duration = speech.shape[-1] / model.sample_rate
    elapsed = time.time() - start
    return {
        "variant": key,
        "label": spec["label"],
        "mode": spec["mode"],
        "modelDir": str(model_dir),
        "prompt": str(spec.get("prompt", "default")),
        "promptText": prompt_text,
        "promptWav": str(prompt_wav.relative_to(output_dir)) if prompt_wav.is_relative_to(output_dir) else str(prompt_wav),
        "audio": str(output_path.relative_to(output_dir)),
        "duration": round(duration, 3),
        "elapsed": round(elapsed, 3),
        "sampleRate": model.sample_rate,
        "units": timeline_units,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--variants", default="a,b,c", help="Comma-separated list from: a,b,c,bm,cm")
    args = parser.parse_args()

    project_root = Path(args.project).expanduser().resolve()
    output_dir = project_root / "tts_ab_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    text = normalize_for_tts(SAMPLE_TEXT).strip()
    (output_dir / "sample_text.txt").write_text(SAMPLE_TEXT.strip() + "\n", encoding="utf-8")
    (output_dir / "sample_text.tts.txt").write_text(text + "\n", encoding="utf-8")
    units = build_tts_units(text)

    selected = [item.strip().lower() for item in args.variants.split(",") if item.strip()]
    manifest_path = output_dir / "manifest.json"
    previous_results = []
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_results = previous.get("results", [])

    results_by_variant = {item["variant"]: item for item in previous_results}
    for key in selected:
        if key not in VARIANTS:
            raise ValueError(f"unknown variant: {key}")
        results_by_variant[key] = render_variant(key, VARIANTS[key], units, output_dir)

    ordered_results = [results_by_variant[key] for key in VARIANT_ORDER if key in results_by_variant]
    manifest_path.write_text(
        json.dumps({"sampleText": "sample_text.txt", "results": ordered_results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"manifest={manifest_path}", flush=True)


if __name__ == "__main__":
    main()
