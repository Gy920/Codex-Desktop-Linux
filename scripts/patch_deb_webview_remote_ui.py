#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def patch_bundle_dir() -> Path:
    return repo_root() / "patches" / "codex-desktop"


def apply_patch_bundle(content_dir: Path) -> None:
    script = repo_root() / "scripts" / "apply_patch_bundle.py"
    cmd = [
        sys.executable,
        str(script),
        "--bundle-dir",
        str(patch_bundle_dir()),
        "--target-dir",
        str(content_dir),
        "--glob-prefix",
        "webview/assets/",
        "--ignore-count",
    ]
    subprocess.run(cmd, check=True)


def backup_targets(content_dir: Path, backup_dir: Path) -> None:
    bundle_dir = patch_bundle_dir()
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rules = [
        rule
        for rule in manifest.get("replacements", [])
        if rule.get("glob", "").startswith("webview/assets/")
    ]

    seen = set()
    for rule in rules:
        for src in sorted(content_dir.glob(rule["glob"])):
            if src in seen:
                continue
            seen.add(src)
            dst = backup_dir / src.name
            shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch Codex Desktop deb webview assets for remote UI access")
    parser.add_argument("--assets-dir", default="/opt/codex-desktop/content/webview/assets")
    parser.add_argument("--backup-dir", default=None)
    args = parser.parse_args()

    assets_dir = Path(args.assets_dir)
    if not assets_dir.exists():
        raise SystemExit(f"Assets dir not found: {assets_dir}")

    content_dir = assets_dir.parents[2]
    if args.backup_dir:
        backup_dir = Path(args.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_targets(content_dir, backup_dir)

    apply_patch_bundle(content_dir)


if __name__ == "__main__":
    main()
