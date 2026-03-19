#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def apply_rule(rule: dict, extract_dir: Path, *, ignore_count: bool = False) -> None:
    matched_files = sorted(extract_dir.glob(rule["glob"]))
    if not matched_files:
        raise SystemExit(f"No files matched {rule['glob']} for {rule['name']}")

    total_replacements = 0
    already_present = False
    find_regex = rule.get("find_regex")
    already_contains_regex = rule.get("already_contains_regex")

    for path in matched_files:
        text = path.read_text(encoding="utf-8")

        if find_regex is not None:
            new_text, replacements = re.subn(find_regex, rule["replace"], text)
            if replacements:
                total_replacements += replacements
                path.write_text(new_text, encoding="utf-8")
                continue
        elif rule["find"] in text:
            total_replacements += text.count(rule["find"])
            text = text.replace(rule["find"], rule["replace"])
            path.write_text(text, encoding="utf-8")
            continue

        if rule.get("already_contains") and rule["already_contains"] in text:
            already_present = True
        elif already_contains_regex and re.search(already_contains_regex, text):
            already_present = True

    expected = rule.get("count")
    if total_replacements == 0:
        if already_present:
            return
        raise SystemExit(f"Rule did not match: {rule['name']}")
    if not ignore_count and expected is not None and total_replacements != expected:
        raise SystemExit(
            f"Rule {rule['name']} replaced {total_replacements} occurrences, expected {expected}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a committed patch bundle to an Electron app.asar or asset directory"
    )
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--asar")
    parser.add_argument("--work-root")
    parser.add_argument("--target-dir")
    parser.add_argument("--glob-prefix")
    parser.add_argument("--ignore-count", action="store_true")
    parser.add_argument("--skip-copy-tree", action="store_true")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    selected_rules = manifest.get("replacements", [])
    if args.glob_prefix:
        selected_rules = [
            rule for rule in selected_rules if rule["glob"].startswith(args.glob_prefix)
        ]

    if args.target_dir:
        if args.asar or args.work_root:
            raise SystemExit("--target-dir cannot be combined with --asar/--work-root")

        target_dir = Path(args.target_dir)
        if not args.skip_copy_tree:
            for item in manifest.get("copy_tree", []):
                copy_tree(bundle_dir / item["from"], target_dir / item["to"])

        for rule in selected_rules:
            apply_rule(rule, target_dir, ignore_count=args.ignore_count)
        return

    if not args.asar or not args.work_root:
        raise SystemExit("Either --target-dir or both --asar and --work-root are required")

    asar_path = Path(args.asar)
    unpacked_dir = asar_path.with_name(f"{asar_path.name}.unpacked")
    work_root = Path(args.work_root)
    extract_dir = work_root / "extract"
    packed_dir = work_root / "packed"
    packed_asar = packed_dir / asar_path.name
    packed_unpacked = packed_dir / f"{asar_path.name}.unpacked"

    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["npx", "--yes", "asar", "extract", str(asar_path), str(extract_dir)],
        check=True,
    )

    if not args.skip_copy_tree:
        for item in manifest.get("copy_tree", []):
            copy_tree(bundle_dir / item["from"], extract_dir / item["to"])

    for rule in selected_rules:
        apply_rule(rule, extract_dir, ignore_count=args.ignore_count)

    packed_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "npx",
            "--yes",
            "asar",
            "pack",
            str(extract_dir),
            str(packed_asar),
            "--unpack",
            "*.node",
        ],
        check=True,
    )

    shutil.copy2(packed_asar, asar_path)
    if unpacked_dir.exists():
        shutil.rmtree(unpacked_dir)
    if packed_unpacked.exists():
        shutil.copytree(packed_unpacked, unpacked_dir)


if __name__ == "__main__":
    main()
