"""
scripts/generate_manifest_checksums.py
=======================================
Downloads each shard listed in a Shattering manifest from HuggingFace,
computes SHA-256 for each file, and patches the manifest JSON in-place.

Usage:
    python scripts/generate_manifest_checksums.py \
        --manifest shattering/manifests/cognia_desktop.json \
        --hf-token hf_...

Run once per manifest when publishing weights to HuggingFace.
Leave sha256 as "" in manifests until weights are published.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path


def sha256_of_url(url: str, token: str) -> str:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    h = hashlib.sha256()
    with urllib.request.urlopen(req) as resp:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute SHA-256 checksums for manifest shards and patch in-place"
    )
    parser.add_argument("--manifest", required=True, help="Path to a Shattering manifest JSON")
    parser.add_argument("--hf-token", default="", help="HuggingFace token for private repos")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with manifest_path.open() as f:
        manifest = json.load(f)

    fragments = manifest.get("fragments", [])
    if not fragments:
        print("No fragments found in manifest.")
        return

    changed = 0
    for frag in fragments:
        url = frag.get("download_url", "")
        if not url or "${" in url:
            print(f"  skip {frag.get('name', '?')} -- placeholder URL")
            continue

        existing = frag.get("sha256", "")
        print(f"  {frag['name']}  {url[:60]}...")
        try:
            digest = sha256_of_url(url, args.hf_token)
        except Exception as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            continue

        if existing and existing == digest:
            print(f"    unchanged: {digest}")
        else:
            frag["sha256"] = digest
            print(f"    patched:   {digest}")
            changed += 1

    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print(f"\nDone. {changed} shard(s) updated in {manifest_path}")


if __name__ == "__main__":
    main()
