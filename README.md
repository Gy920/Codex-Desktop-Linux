# Codex Desktop for Linux

Run [OpenAI Codex Desktop](https://openai.com/codex/) on Linux by converting the official macOS app bundle into a Linux-ready Electron app.

This repo now has three clear layers:

1. `install.sh` converts `Codex.dmg` into a runnable `codex-app/`
2. your private local helper can reapply custom patches to `app.asar`
3. `build-deb.sh` packages the finished app into a Debian package

## Quick start

If you only want to use a prebuilt Debian package, you do not need the compiler toolchains from the build instructions.

### Install a prebuilt `.deb` on Debian or Ubuntu

Install the minimum prerequisites:

```bash
sudo apt update
sudo apt install -y nodejs npm
```

Install the package, then let `apt` resolve any missing runtime libraries:

```bash
sudo dpkg -i ./codex-desktop-linux_40.0.0-1_amd64.deb
sudo apt -f install -y
```

Install the Codex CLI required by the desktop launcher:

```bash
npm i -g @openai/codex
```

Then launch `Codex Desktop` from the app menu, or run:

```bash
codex-desktop
```

## Repository layout

Tracked source files:

- `install.sh` - convert the official DMG into `codex-app/`
- `build-deb.sh` - package `codex-app/` into `dist/*.deb`
- `packaging/deb/` - launcher, desktop file, and Debian metadata assets
- `patches/codex-desktop/` - reusable patch bundle assets committed to git
- `README.md` - end-to-end workflow and maintenance notes

Generated or local-only paths:

- `codex-app/` - generated Linux app bundle
- `dist/` - generated Debian packages
- `.cache/` - downloaded helper tools such as modern `7-Zip`
- `patch-work/` - temporary extraction and repack workdirs
- `local/` - private helper scripts, intentionally gitignored
- `Codex.dmg` - optional local copy of the upstream macOS installer

## Requirements

For a prebuilt `.deb`, you only need:

- `Node.js`
- `npm`
- the `codex` CLI (`npm i -g @openai/codex`)

For building the Linux app from the macOS DMG, you also need:

```bash
npm i -g @openai/codex
```

- `Node.js 20+`
- `npm`
- `Python 3`
- `curl`
- `tar`
- `unzip`
- build tools with working C++20 support

The installer prefers a recent `7-Zip` (`7zz`/`7z`, version 22+). If your distro only ships old `p7zip` 16.x, `install.sh` downloads the official Linux `7-Zip` binary into `.cache/` automatically.

### Debian/Ubuntu

```bash
sudo apt install nodejs npm python3 curl tar unzip build-essential
sudo apt install gcc-12 g++-12
sudo apt install clang-18 libc++-18-dev libc++abi-18-dev
```

### Fedora

```bash
sudo dnf install nodejs npm python3 curl tar unzip
sudo dnf groupinstall 'Development Tools'
```

### Arch

```bash
sudo pacman -S nodejs npm python curl tar unzip base-devel
```

## End-to-end workflow

### 1. Convert the official DMG into a Linux app

Auto-download the current DMG:

```bash
./install.sh
```

Or use a DMG you already downloaded:

```bash
./install.sh /path/to/Codex.dmg
```

This produces:

```text
./codex-app/
```

### 2. Reapply local custom patches

If you maintain a private helper in `local/`, run it after every new `install.sh` output so the generated `codex-app/resources/app.asar` picks up your local fixes again.

Typical local command:

```bash
./local/apply_codex_patch.py ./codex-app/resources/app.asar
```

In this workspace, the committed patch bundle under `patches/codex-desktop/` is designed for:

- bundled `Ubuntu` / `Ubuntu Mono` fonts
- Linux project picker fixes
- the recommended-skills clone workaround

If OpenAI changes the bundle layout in a future release, adjust `patches/codex-desktop/manifest.json` and rerun your local helper.

### 3. Run the unpacked app

```bash
./codex-app/start.sh
```

Optional custom install directory while converting:

```bash
CODEX_INSTALL_DIR=/opt/codex ./install.sh
```

### 4. Build a Debian package

Once `codex-app/` is in the exact state you want, package it:

```bash
./build-deb.sh
```

This writes a package to:

```text
./dist/codex-desktop-linux_<version>_<arch>.deb
```

Useful overrides:

```bash
MAINTAINER_NAME="Your Name" \
MAINTAINER_EMAIL="you@example.com" \
PACKAGE_NAME="codex-desktop-linux" \
./build-deb.sh
```

### 5. Install the Debian package

```bash
sudo dpkg -i ./dist/codex-desktop-linux_<version>_<arch>.deb
sudo apt -f install
```

Then make sure the Codex CLI exists for the launcher:

```bash
npm i -g @openai/codex
```

## GitHub Actions release automation

The workflow [`release-deb.yml`](.github/workflows/release-deb.yml) runs on `ubuntu-20.04` and can be triggered manually or on the daily schedule.

It performs the full pipeline:

1. downloads the latest upstream `Codex.dmg`
2. runs `install.sh`
3. reapplies the committed patch bundle from `patches/codex-desktop/`
4. runs `build-deb.sh`
5. publishes `dist/*.deb` to a GitHub Release tagged as `codex-desktop-linux-v<app-version>`

The workflow uses the repository `GITHUB_TOKEN` with `contents: write` so it can create or update the release for a given upstream app version.

## Updating to a new Codex release

When a new upstream `Codex.dmg` appears, redo the build in this order:

```bash
./install.sh /path/to/new/Codex.dmg
./local/apply_codex_patch.py ./codex-app/resources/app.asar   # if you keep the local helper
./build-deb.sh                                                # optional
```

Important detail: `build-deb.sh` packages the current contents of `codex-app/` exactly as they are. If you want your fonts or JS fixes inside the `.deb`, apply your local patch before running `build-deb.sh`.

## How it works

The macOS Codex app is an Electron app. The platform-independent JavaScript lives in `app.asar`, but the original bundle also includes:

- native modules compiled for macOS
- a macOS Electron runtime
- macOS-only updater pieces such as `sparkle`

`install.sh` extracts the DMG, swaps in a Linux Electron runtime, rebuilds native modules such as `node-pty` and `better-sqlite3`, removes macOS-only pieces, and creates a Linux launcher.

`build-deb.sh` does not rebuild the app; it simply packages the current `codex-app/` tree together with the desktop launcher assets from `packaging/deb/`.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Error: write EPIPE` | Run `start.sh` directly; do not pipe its output |
| `Open ERROR: Can not open the file as [Dmg] archive` | Your `7z` is too old; rerun `install.sh` and let it fetch a newer 7-Zip, or install `7zz` 22+ |
| `g++: error: unrecognized command line option '-std=c++20'` or `fatal error: 'compare' file not found` | Install GCC 10+ or Clang with a working C++20 standard library |
| Blank window | Check whether port `5175` is already in use: `lsof -i :5175` |
| `Codex CLI not found` | Install it with `npm i -g @openai/codex`, or set `CODEX_CLI_PATH` manually |
| App menu icon is correct but taskbar icon is wrong | Reinstall the latest `.deb`, remove any old pinned icon, then re-pin the running app |
| GPU/rendering issues | Try `./codex-app/start.sh --disable-gpu` |
| Sandbox errors | The launcher already adds `--no-sandbox` |

## Disclaimer

This is an unofficial community project. Codex Desktop is a product of OpenAI.

Make sure you understand the redistribution implications before publicly sharing repackaged application bundles.

## License

MIT
