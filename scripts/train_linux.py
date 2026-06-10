#!/usr/bin/env python3
"""
QLoRA SFT + DPO Training für Bitwig AI Agent auf Linux GPU.

Verwendung:
    python scripts/train_linux.py --mode sft
    python scripts/train_linux.py --mode dpo
    python scripts/train_linux.py --mode sft --iters 200 --base-model Qwen/Qwen3-14B

Nach dem Training vLLM mit LoRA starten:
    vllm serve Qwen/Qwen3-14B \
        --enable-lora \
        --lora-modules agent=./adapters/bitwig-agent \
        --max-model-len 4096 \
        --port 8100 \
        --served-model-name agent
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Config-Defaults (überschreibbar via Env-Vars oder CLI) ───────────────────
DEFAULTS = {
    "base_model":   os.getenv("TRAIN_BASE_MODEL",   "Qwen/Qwen3-14B"),
    "data_dir":     os.getenv("TRAIN_DATA_DIR",     str(ROOT / "training_data")),
    "adapter_dir":  os.getenv("TRAIN_ADAPTER_DIR",  str(ROOT / "adapters" / "bitwig-agent")),
    "max_seq_len":  int(os.getenv("TRAIN_MAX_SEQ",  "2048")),
    "lora_r":       int(os.getenv("TRAIN_LORA_R",   "16")),
    "lora_alpha":   int(os.getenv("TRAIN_LORA_ALPHA","32")),
    "batch_size":   int(os.getenv("TRAIN_BATCH",    "1")),
    "grad_accum":   int(os.getenv("TRAIN_GRAD_ACC", "8")),
    "lr":           float(os.getenv("TRAIN_LR",     "2e-4")),
    "iters":        int(os.getenv("TRAIN_ITERS",    "300")),
    "warmup":       int(os.getenv("TRAIN_WARMUP",   "30")),
}

LORA_TARGETS = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]


def _load_jsonl(path: str) -> list[dict]:
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _try_unsloth(base_model: str, max_seq_len: int, lora_r: int, lora_alpha: int):
    """Versucht Unsloth zu laden (2× schneller als Standard-QLoRA)."""
    try:
        from unsloth import FastLanguageModel
        print("✓ Unsloth verfügbar — schnelles QLoRA-Training")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=base_model,
            max_seq_length=max_seq_len,
            load_in_4bit=True,
            dtype=None,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=lora_r,
            lora_alpha=lora_alpha,
            target_modules=LORA_TARGETS,
            lora_dropout=0.05,
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=42,
        )
        return model, tokenizer, "unsloth"
    except ImportError:
        print("ℹ Unsloth nicht installiert — Standard-QLoRA (BitsAndBytes)")
        return None, None, None


def _load_standard_qlora(base_model: str, max_seq_len: int, lora_r: int, lora_alpha: int):
    """Standard QLoRA via transformers + peft + bitsandbytes."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    print(f"Lade Basismodell: {base_model}")
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if not tokenizer.pad_token:
        tokenizer.pad_token = tokenizer.eos_token

    model = prepare_model_for_kbit_training(model)
    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        target_modules=LORA_TARGETS,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    return model, tokenizer, "standard"


def _format_chat(example: dict, tokenizer) -> str:
    """Formatiert messages-Array mit dem Modell-Chat-Template."""
    messages = example.get("messages", [])
    if not messages:
        return ""
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)


def run_sft(args: argparse.Namespace) -> None:
    """Supervised Fine-Tuning auf train.jsonl."""
    from datasets import Dataset
    from trl import SFTTrainer, SFTConfig

    # Modell laden
    model, tokenizer, backend = _try_unsloth(
        args.base_model, args.max_seq_len, args.lora_r, args.lora_alpha)
    if model is None:
        model, tokenizer, backend = _load_standard_qlora(
            args.base_model, args.max_seq_len, args.lora_r, args.lora_alpha)

    # Daten laden
    data_path = Path(args.data_dir) / "train.jsonl"
    valid_path = Path(args.data_dir) / "valid.jsonl"
    print(f"Lade Trainingsdaten: {data_path}")
    train_data = _load_jsonl(str(data_path))
    valid_data = _load_jsonl(str(valid_path)) if valid_path.exists() else []
    print(f"  Train: {len(train_data)} | Valid: {len(valid_data)}")

    # Chat-Template anwenden
    def _fmt(ex):
        return {"text": _format_chat(ex, tokenizer)}

    train_ds = Dataset.from_list(train_data).map(_fmt, remove_columns=["messages"])
    valid_ds = Dataset.from_list(valid_data).map(_fmt, remove_columns=["messages"]) if valid_data else None

    # Adapter-Verzeichnis anlegen
    Path(args.adapter_dir).mkdir(parents=True, exist_ok=True)

    # Trainings-Config
    steps_per_epoch = max(1, len(train_data) // (args.batch_size * args.grad_accum))
    total_steps = args.iters
    save_steps = max(50, total_steps // 4)
    eval_steps = save_steps if valid_ds else None

    training_args = SFTConfig(
        output_dir=args.adapter_dir,
        max_steps=total_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        warmup_steps=args.warmup,
        lr_scheduler_type="cosine",
        optim="adamw_8bit" if backend == "standard" else "adamw_torch_fused",
        fp16=False,
        bf16=True,
        logging_steps=10,
        save_steps=save_steps,
        eval_steps=eval_steps,
        save_total_limit=3,
        load_best_model_at_end=bool(valid_ds),
        metric_for_best_model="eval_loss" if valid_ds else None,
        greater_is_better=False,
        max_seq_length=args.max_seq_len,
        dataset_text_field="text",
        packing=True,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=valid_ds,
    )

    print(f"\n{'='*60}")
    print(f"SFT Training: {total_steps} Steps | LR={args.lr} | LoRA r={args.lora_r}")
    print(f"Backend: {backend} | Effective Batch: {args.batch_size * args.grad_accum}")
    print(f"Output: {args.adapter_dir}")
    print(f"{'='*60}\n")

    trainer.train()
    trainer.save_model(args.adapter_dir)
    tokenizer.save_pretrained(args.adapter_dir)
    print(f"\n✅ SFT abgeschlossen — Adapter gespeichert: {args.adapter_dir}")
    _print_vllm_start(args)


def run_dpo(args: argparse.Namespace) -> None:
    """DPO Fine-Tuning auf dpo_train.jsonl."""
    from datasets import Dataset
    from trl import DPOTrainer, DPOConfig
    from peft import PeftModel
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dpo_path = Path(args.data_dir) / "dpo_train.jsonl"
    if not dpo_path.exists():
        print(f"❌ {dpo_path} nicht gefunden")
        sys.exit(1)

    dpo_data = _load_jsonl(str(dpo_path))
    print(f"DPO-Paare: {len(dpo_data)}")
    if len(dpo_data) < 5:
        print("⚠ Weniger als 5 DPO-Paare — zuerst generate_dpo_pairs.py ausführen")
        sys.exit(1)

    # Adapter-Basis (nach SFT)
    adapter_exists = (Path(args.adapter_dir) / "adapter_config.json").exists()
    if not adapter_exists:
        print(f"⚠ Kein SFT-Adapter in {args.adapter_dir} — zuerst --mode sft ausführen")
        sys.exit(1)

    tokenizer = AutoTokenizer.from_pretrained(args.adapter_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(model, args.adapter_dir)

    # Format: {prompt, chosen, rejected}
    dpo_ds = Dataset.from_list(dpo_data)

    dpo_config = DPOConfig(
        output_dir=args.adapter_dir + "-dpo",
        max_steps=min(args.iters // 3, len(dpo_data) * 5),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=args.lr / 5,
        bf16=True,
        logging_steps=5,
        save_steps=50,
        beta=0.1,
        report_to="none",
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=dpo_config,
        train_dataset=dpo_ds,
        tokenizer=tokenizer,
    )

    print(f"\n{'='*60}")
    print(f"DPO Training: {dpo_config.max_steps} Steps | Beta=0.1")
    print(f"{'='*60}\n")

    trainer.train()
    trainer.save_model(dpo_config.output_dir)
    print(f"\n✅ DPO abgeschlossen — Adapter: {dpo_config.output_dir}")
    _print_vllm_start(args, suffix="-dpo")


def _print_vllm_start(args: argparse.Namespace, suffix: str = "") -> None:
    adapter_path = args.adapter_dir + suffix
    print(f"""
vLLM mit LoRA-Adapter starten:

    vllm serve {args.base_model} \\
        --enable-lora \\
        --lora-modules agent={adapter_path} \\
        --max-model-len 4096 \\
        --gpu-memory-utilization 0.90 \\
        --port 8100
""")


def main() -> None:
    p = argparse.ArgumentParser(description="Bitwig AI Agent — Linux QLoRA Training")
    p.add_argument("--mode",        choices=["sft", "dpo", "both"], default="sft")
    p.add_argument("--base-model",  default=DEFAULTS["base_model"])
    p.add_argument("--data-dir",    default=DEFAULTS["data_dir"])
    p.add_argument("--adapter-dir", default=DEFAULTS["adapter_dir"])
    p.add_argument("--max-seq-len", type=int, default=DEFAULTS["max_seq_len"])
    p.add_argument("--lora-r",      type=int, default=DEFAULTS["lora_r"])
    p.add_argument("--lora-alpha",  type=int, default=DEFAULTS["lora_alpha"])
    p.add_argument("--batch-size",  type=int, default=DEFAULTS["batch_size"])
    p.add_argument("--grad-accum",  type=int, default=DEFAULTS["grad_accum"])
    p.add_argument("--lr",          type=float, default=DEFAULTS["lr"])
    p.add_argument("--iters",       type=int, default=DEFAULTS["iters"])
    p.add_argument("--warmup",      type=int, default=DEFAULTS["warmup"])
    args = p.parse_args()

    print(f"Bitwig AI Agent — Linux QLoRA Training")
    print(f"Modell: {args.base_model}")
    print(f"Daten:  {args.data_dir}")
    print(f"Modus:  {args.mode}")

    if args.mode in ("sft", "both"):
        run_sft(args)
    if args.mode in ("dpo", "both"):
        run_dpo(args)


if __name__ == "__main__":
    main()
