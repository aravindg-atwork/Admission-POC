#!/usr/bin/env python3
"""
Copy local Ollama models (GGUF blobs) into D:\\models as runnable .gguf files.

Names each model after its manifest (e.g. qwen2.5-coder-1.5b) and copies the
big "application/vnd.ollama.image.model" blob to D:\\models\\<name>\\<name>.gguf.
Safe to re-run: skips destination files that already exist.

Usage:  python tools/copy_ollama_models.py
"""
import json
import shutil
from pathlib import Path

OLLAMA_ROOT = Path.home() / ".ollama"
MANIFEST_ROOT = OLLAMA_ROOT / "models" / "manifests"
BLOB_ROOT = OLLAMA_ROOT / "models" / "blobs"
DEST_ROOT = Path("D:/models")

# (model display name, relative manifest path without trailing .json)
TARGETS = [
    ("qwen2.5-coder-1.5b", "registry.ollama.ai/library/qwen2.5-coder/1.5b"),
    ("qwen2.5-coder-7b",    "registry.ollama.ai/library/qwen2.5-coder/7b"),
    ("sarvam-1-gguf-Q4_K_M","hf.co/QuantFactory/sarvam-1-GGUF/Q4_K_M"),
    ("gemma2-2b",           "registry.ollama.ai/library/gemma2/2b"),
    ("llama3.1-8b",         "registry.ollama.ai/library/llama3.1/latest"),
    ("llama3.2-3b",         "registry.ollama.ai/library/llama3.2/3b"),
]

MODEL_MEDIA = "application/vnd.ollama.image.model"


def main() -> None:
    for name, rel in TARGETS:
        path = MANIFEST_ROOT / rel
        # In Ollama, a manifest is a directory containing a single JSON file
        # (or a file named <name>.json if it was a file-based manifest).
        if path.is_dir():
            files = list(path.iterdir())
            manifest = files[0] if len(files) == 1 else None
        elif path.exists():
            manifest = path
        else:
            manifest = MANIFEST_ROOT / (rel + ".json")
            if not manifest.exists():
                manifest = None
        if manifest is None:
            print(f"SKIP {name}: manifest not found ({rel})")
            continue

        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {name}: bad manifest {manifest} -> {e}")
            continue

        out_dir = DEST_ROOT / name
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"{name}.gguf"

        if dst.exists():
            print(f"EXISTS {name}: {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
            continue

        model_layers = [l for l in data.get("layers", []) if l.get("mediaType") == MODEL_MEDIA]
        if not model_layers:
            print(f"SKIP {name}: no model layer in manifest")
            continue

        digest = model_layers[0]["digest"]                    # e.g. "sha256:..."
        src = BLOB_ROOT / digest                              # blob path
        if not src.exists():
            # Ollama stores blobs as sha256-<hex> (no colon) on disk
            src = BLOB_ROOT / digest.replace(":", "-")
        if not src.exists():
            print(f"SKIP {name}: blob missing for {digest}")
            continue

        print(f"COPY {name}: {src.name} ({src.stat().st_size / 1e6:.1f} MB) -> {dst}")
        shutil.copy2(src, dst)


if __name__ == "__main__":
    main()

