#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path


APPLY_RULES = [
    {
        "glob": "statsig-*.js",
        "name": "force-remote-gate",
        "find": "function De(e){return Le(),(0,Ce.useGateValue)(e)}",
        "replace": "function De(e){let t=(Le(),(0,Ce.useGateValue)(e));return e===`4114442250`?!0:t}",
    },
    {
        "glob": "index-*.js",
        "name": "show-connections-settings-entry",
        "find": "case`skills-settings`:return r===`extension`;case`connections`:return r===`electron`&&a;case`usage`:return o;",
        "replace": "case`skills-settings`:return r===`extension`;case`connections`:return!0;case`usage`:return o;",
    },
    {
        "glob": "index-*.js",
        "name": "inject-connections-into-visible-settings-sections",
        "find": "t[7]=a,t[8]=o,t[9]=r,t[10]=e):e=t[10],l=ql.filter(e);let i;",
        "replace": "t[7]=a,t[8]=o,t[9]=r,t[10]=e):e=t[10],l=ql.filter(e),l.some(e=>e.slug===`connections`)||l.push({slug:`connections`});let i;",
    },
    {
        "glob": "index-*.js",
        "name": "mcp-settings-entry-opens-connections",
        "find": "window.open(e.externalUrl,`_blank`,`noopener,noreferrer`);return}t||i(e.slug)",
        "replace": "window.open(e.externalUrl,`_blank`,`noopener,noreferrer`);return}t||i(e.slug===`mcp-settings`?`connections`:e.slug)",
    },
    {
        "glob": "index-*.js",
        "name": "connections-page-renders-remote-connections",
        "find": "\"mcp-settings\":(0,Z.lazy)(()=>v(()=>import(`./mcp-settings-DrgCUGND.js`).then(e=>({default:e.McpSettings})),__vite__mapDeps([100,2,6,7,4,3,8,9,20,18,19,21,22,23,24,25,13,26,27,53,101,67,29,88,69,86,102,31,94,74,95,96,38,39]),import.meta.url)),",
        "replace": "\"mcp-settings\":(0,Z.lazy)(()=>v(()=>import(`./remote-connections-settings-BY9N7Qjx.js`).then(e=>({default:e.RemoteConnectionsSettings})),__vite__mapDeps([103,2,6,7,4,3,8,9,20,18,19,21,24,25,13,26,27,104,68,29,31,96,105,38]),import.meta.url)),",
    },
]


CLEANUP_RULES = [
    {
        "glob": "general-settings-*.js",
        "name": "remove-general-remote-connections-row",
        "find": "children:[o,s,c,l,u,(0,Z.jsx)(q,{label:`Remote Connections`,description:`Manage SSH hosts and remote project mappings`,control:(0,Z.jsx)(`a`,{href:`/settings/mcp-settings`,className:`text-sm text-token-link underline`,children:`Open`})}),d,h,f,p,m]",
        "replace": "children:[o,s,c,l,u,d,h,f,p,m]",
    },
]


def find_target(base_dir: Path, rule: dict) -> Path:
    matches = sorted(base_dir.glob(rule["glob"]))
    if not matches:
        raise SystemExit(f"Missing target file for {rule['name']}: {base_dir / rule['glob']}")

    for path in matches:
        text = path.read_text(encoding="utf-8")
        if rule["find"] in text or rule["replace"] in text:
            return path

    raise SystemExit(f"Pattern not found for {rule['name']} in {base_dir / rule['glob']}")


def replace_once(base_dir: Path, rule: dict) -> None:
    path = find_target(base_dir, rule)
    text = path.read_text(encoding="utf-8")
    if rule["replace"] in text:
        return
    if rule["find"] not in text:
        raise SystemExit(f"Pattern not found for {rule['name']} in {path}")

    updated = text.replace(rule["find"], rule["replace"], 1)
    path.write_text(updated, encoding="utf-8")


def backup_targets(base_dir: Path, backup_dir: Path) -> None:
    seen = set()
    for rule in APPLY_RULES + CLEANUP_RULES:
        for src in sorted(base_dir.glob(rule["glob"])):
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

    if args.backup_dir:
        backup_dir = Path(args.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_targets(assets_dir, backup_dir)

    for rule in CLEANUP_RULES:
        replace_once(assets_dir, rule)

    for rule in APPLY_RULES:
        replace_once(assets_dir, rule)


if __name__ == "__main__":
    main()
