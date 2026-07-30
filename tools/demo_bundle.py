"""Pack/unpack the demo-critical state that git deliberately doesn't carry.

`git pull` moves the code. It does not move any of the state that actually makes
a demo work, because .gitignore (correctly) excludes secrets, uploaded PDFs,
embeddings and caches. Rebuilding that by hand on another machine means
re-entering the API keys, re-uploading the prospectus, waiting on a full
re-embed, and then asking every demo question once to warm the cache - roughly
half an hour, most of it on the critical path the morning of a demo.

This packs the whole lot into one ~6 MB zip instead:

    python tools/demo_bundle.py pack                  # -> demo-bundle.zip
    python tools/demo_bundle.py unpack demo-bundle.zip

Pure standard library and no OS-specific paths, because the machine on the other
end is the Windows host (see backend/config.py) where an Application Control
policy blocks freshly built native binaries - so this has to run on nothing but
a stock Python.

THE BUNDLE CONTAINS SECRETS: .env holds SARVAM_API_KEY and ADMIN_TOKEN, and the
api-keys files hold live API keys. Move it like a password (USB, or a private
channel), delete it afterwards, and don't commit it - .gitignore already excludes
demo-bundle*.zip.

Deliberately NOT included: data/projects/default/stats.json. It's per-machine
dashboard metrics, and carrying this laptop's test traffic over would put a
misleading question count and latency history in front of the audience.
"""

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Everything git leaves behind that the demo genuinely needs, and why.
FILES = [
    (".env", "API keys + SARVAM_MODEL. Without this the backend has no Sarvam key."),
    ("data/projects.json", "Project registry - the 'default' project's settings."),
    ("data/api-keys.json", "Backend API keys; the chat widget authenticates with one."),
    ("services/embedding-service/api_keys.json", "Embedding-service keys, matched by EMBEDDING_API_KEY in .env."),
    ("data/projects/default/prospectus.pdf", "The source PDF itself."),
    ("data/projects/default/vector-store.json", "200 embedded chunks - avoids a full re-ingest."),
    ("data/projects/default/manifest.json", "Ingest hash; matching it is what lets re-ingest be skipped."),
    ("data/projects/default/faq-cache.json", "Curated seeds + warmed answers - what makes demo questions instant."),
]
MANIFEST_NAME = "BUNDLE_MANIFEST.json"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def pack(out_path):
    missing, entries = [], []
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, why in FILES:
            src = BASE_DIR / rel
            if not src.exists():
                missing.append(rel)
                continue
            z.write(src, rel)
            entries.append({"path": rel, "bytes": src.stat().st_size,
                            "sha256_16": _digest(src), "why": why})
        z.writestr(MANIFEST_NAME, json.dumps({
            "created": datetime.now(timezone.utc).isoformat(),
            "files": entries,
        }, indent=2))

    total = sum(e["bytes"] for e in entries)
    print(f"packed {len(entries)} files ({total / 1e6:.1f} MB) -> {out_path}")
    for e in entries:
        print(f"  {e['bytes']:>9,}  {e['path']}")
    if missing:
        # Not fatal: a machine that never ran the admin console has no
        # api-keys.json yet, and the backend recreates it on first use.
        print("\nnot present on this machine, skipped:")
        for rel in missing:
            print(f"  - {rel}")
    print("\nThis zip contains live secrets. Move it privately and delete it after.")
    return 0


def unpack(zip_path, force=False):
    if not Path(zip_path).exists():
        print(f"no such bundle: {zip_path}")
        return 1
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n != MANIFEST_NAME]
        existing = [n for n in names if (BASE_DIR / n).exists()]
        if existing and not force:
            print("These already exist here and would be overwritten:")
            for n in existing:
                print(f"  {n}")
            print("\nRe-run with --force to replace them.")
            return 1
        for n in names:
            dest = BASE_DIR / n
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(n))
            print(f"  restored {n}")
    print("\nRestored. Now: start the embedding service, then the backend, then")
    print("verify with the pre-flight block in docs/DEMO_SCRIPT.md.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="write a bundle from this machine")
    p.add_argument("out", nargs="?", default=str(BASE_DIR / "demo-bundle.zip"))
    u = sub.add_parser("unpack", help="restore a bundle onto this machine")
    u.add_argument("zip")
    u.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()
    return pack(args.out) if args.cmd == "pack" else unpack(args.zip, args.force)


if __name__ == "__main__":
    sys.exit(main())
