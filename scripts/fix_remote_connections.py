#!/usr/bin/env python3
import argparse
import json
import os
import pwd
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from patch_deb_webview_remote_ui import main as patch_deb_webview_main


REMOTE_FIX_SCRIPT = r'''
from pathlib import Path
import json
import os
import shutil
import subprocess

HOME = Path.home()
BASHRC = HOME / '.bashrc'
BACKUP = HOME / '.bashrc.codex_remote_backup'
MARKER_START = '# >>> codex remote noninteractive >>>'
MARKER_END = '# <<< codex remote noninteractive >>>'

node_bins = sorted((HOME / '.nvm' / 'versions' / 'node').glob('*/bin'))
latest_node_bin = str(node_bins[-1]) if node_bins else None
prepend_paths = [str(HOME / '.local' / 'bin'), str(HOME / '.npm-global' / 'bin')]
if latest_node_bin:
    prepend_paths.append(latest_node_bin)

block_lines = [MARKER_START]
if latest_node_bin:
    block_lines.extend([
        f'export PATH="{prepend_paths[0]}:{prepend_paths[1]}:{latest_node_bin}:$PATH"',
    ])
else:
    block_lines.extend([
        f'export PATH="{prepend_paths[0]}:{prepend_paths[1]}:$PATH"',
    ])
block_lines.append(MARKER_END)
block = '\n'.join(block_lines) + '\n'

original = BASHRC.read_text(errors='ignore') if BASHRC.exists() else ''
updated = original
changed = False
if MARKER_START in updated and MARKER_END in updated:
    start = updated.index(MARKER_START)
    end = updated.index(MARKER_END) + len(MARKER_END)
    while end < len(updated) and updated[end] == '\n':
        end += 1
    replacement = block
    if end < len(updated):
        replacement += '\n'
    updated = updated[:start] + replacement + updated[end:]
else:
    guard = '# If not running interactively, don\'t do anything\n'
    idx = updated.find(guard)
    if idx == -1:
        idx = updated.find('case $- in\n')
    if idx == -1:
        idx = 0
    prefix = updated[:idx]
    suffix = updated[idx:]
    if prefix and not prefix.endswith('\n'):
        prefix += '\n'
    updated = prefix + block + ('\n' if suffix and not suffix.startswith('\n') else '') + suffix
if updated != original:
    changed = True
    BACKUP.write_text(original)
    BASHRC.write_text(updated)

env = os.environ.copy()
current_path_parts = [part for part in env.get('PATH', '').split(':') if part]
merged = []
for part in prepend_paths + current_path_parts:
    if part and part not in merged:
        merged.append(part)
env['PATH'] = ':'.join(merged)

node_path = shutil.which('node', path=env['PATH'])
npm_path = shutil.which('npm', path=env['PATH'])
codex_path = shutil.which('codex', path=env['PATH'])
installed_codex = False
install_error = None
if codex_path is None and npm_path is not None:
    install = subprocess.run(
        ['npm', 'install', '-g', '--prefix', str(HOME / '.local'), '@openai/codex'],
        env=env,
        text=True,
        capture_output=True,
    )
    if install.returncode == 0:
        installed_codex = True
        codex_path = shutil.which('codex', path=env['PATH'])
    else:
        install_error = (install.stderr or install.stdout or '').strip()

def run_value(command):
    proc = subprocess.run(command, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        return None
    return (proc.stdout or '').strip() or None

result = {
    'bashrc_changed': changed,
    'bashrc_backup': str(BACKUP),
    'latest_node_bin': latest_node_bin,
    'node_path_with_fixed_env': node_path,
    'npm_path_with_fixed_env': npm_path,
    'codex_path_with_fixed_env': codex_path,
    'codex_installed': installed_codex,
    'install_error': install_error,
    'node_version_with_fixed_env': run_value(['node', '-v']) if node_path else None,
    'npm_version_with_fixed_env': run_value(['npm', '-v']) if npm_path else None,
    'codex_version_with_fixed_env': run_value(['codex', '--version']) if codex_path else None,
}
print(json.dumps(result, ensure_ascii=True))
'''


REMOTE_VALIDATE_SCRIPT = r'''
from pathlib import Path
import json
import os
import shutil
import subprocess


def run_value(command):
    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.returncode != 0:
        return None
    return (proc.stdout or '').strip() or None

result = {
    'path': os.environ.get('PATH'),
    'node_path': shutil.which('node'),
    'node_version': run_value(['node', '-v']) if shutil.which('node') else None,
    'npm_path': shutil.which('npm'),
    'npm_version': run_value(['npm', '-v']) if shutil.which('npm') else None,
    'codex_path': shutil.which('codex'),
    'codex_version': run_value(['codex', '--version']) if shutil.which('codex') else None,
    'auth_json_exists': (Path.home() / '.codex' / 'auth.json').exists(),
}
print(json.dumps(result, ensure_ascii=True))
'''


def get_invoking_user() -> Optional[str]:
    if os.geteuid() == 0 and os.environ.get('SUDO_USER'):
        return os.environ['SUDO_USER']
    return None


def get_invoking_home() -> Path:
    invoking_user = get_invoking_user()
    if invoking_user is None:
        return Path.home()
    return Path(pwd.getpwnam(invoking_user).pw_dir)


def run_command(cmd, *, input_text=None, as_invoking_user=False):
    if as_invoking_user and get_invoking_user() is not None:
        cmd = ['sudo', '-u', get_invoking_user(), '-H', *cmd]
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True)


def run_remote_python(host: str, script: str):
    proc = run_command(
        ['ssh', '-o', 'BatchMode=yes', host, 'python3', '-'],
        input_text=script,
        as_invoking_user=True,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip()
        stdout = (proc.stdout or '').strip()
        message = stderr or stdout or f'ssh to {host} failed'
        raise SystemExit(message)
    output = (proc.stdout or '').strip()
    if not output:
        raise SystemExit(f'No output returned from remote host {host}')
    return json.loads(output)


def build_default_backup_dir() -> Path:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return get_invoking_home() / '.cache' / 'codex-desktop-backups' / f'remote-connections-{stamp}'


def patch_local_assets(assets_dir: str, backup_dir: Path) -> None:
    argv = [
        'patch_deb_webview_remote_ui.py',
        '--assets-dir',
        assets_dir,
        '--backup-dir',
        str(backup_dir),
    ]
    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        patch_deb_webview_main()
    except PermissionError:
        raise SystemExit(
            f'Permission denied while patching {assets_dir}. '
            'Run this script with sudo so it can write /opt/codex-desktop.'
        )
    finally:
        sys.argv = old_argv


def print_local_summary(assets_dir: str, backup_dir: Path) -> None:
    print('[local] deb webview patched')
    print(f'  assets: {assets_dir}')
    print(f'  backup: {backup_dir}')
    print('  result: Connections settings entry enabled')


def print_remote_summary(host: str, fixed: dict, validated: dict) -> None:
    print(f'[remote:{host}] repair complete')
    print(f"  bashrc changed: {'yes' if fixed['bashrc_changed'] else 'no'}")
    print(f"  bashrc backup: {fixed['bashrc_backup']}")
    print(f"  latest nvm node: {fixed['latest_node_bin'] or 'not found'}")
    print(f"  node: {validated['node_path'] or 'missing'} {validated['node_version'] or ''}".rstrip())
    print(f"  npm: {validated['npm_path'] or 'missing'} {validated['npm_version'] or ''}".rstrip())
    print(f"  codex: {validated['codex_path'] or 'missing'} {validated['codex_version'] or ''}".rstrip())
    print(f"  auth.json: {'present' if validated['auth_json_exists'] else 'missing'}")
    if fixed['codex_installed']:
        print('  codex install: installed automatically')
    elif fixed['install_error']:
        print(f"  codex install error: {fixed['install_error']}")
    print(f"  path: {validated['path']}")


def main() -> None:
    parser = argparse.ArgumentParser(description='One-click repair for Codex Desktop remote connections on deb installs')
    parser.add_argument('--assets-dir', default='/opt/codex-desktop/content/webview/assets')
    parser.add_argument('--backup-dir', default=None)
    parser.add_argument('--remote-host', action='append', default=[])
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir) if args.backup_dir else build_default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    patch_local_assets(args.assets_dir, backup_dir)
    print_local_summary(args.assets_dir, backup_dir)

    if not args.remote_host:
        print('[remote] skipped (no --remote-host provided)')
        return

    for host in args.remote_host:
        fixed = run_remote_python(host, REMOTE_FIX_SCRIPT)
        validated = run_remote_python(host, REMOTE_VALIDATE_SCRIPT)
        print_remote_summary(host, fixed, validated)


if __name__ == '__main__':
    main()
