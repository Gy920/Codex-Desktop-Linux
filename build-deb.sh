#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR/codex-app}"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/dist}"
PACKAGE_NAME="${PACKAGE_NAME:-codex-desktop-linux}"
INSTALL_DIR="${INSTALL_DIR:-/opt/codex-desktop}"
APP_VERSION="${APP_VERSION:-}"
PACKAGE_VERSION="${PACKAGE_VERSION:-}"
MAINTAINER_NAME="${MAINTAINER_NAME:-$(git -C "$SCRIPT_DIR" config user.name 2>/dev/null || true)}"
MAINTAINER_EMAIL="${MAINTAINER_EMAIL:-$(git -C "$SCRIPT_DIR" config user.email 2>/dev/null || true)}"
STAGING_DIR="$(mktemp -d)"
ICON_SOURCE="${ICON_SOURCE:-}"

cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

error() {
    echo "Error: $*" >&2
    exit 1
}

detect_codex_app_version() {
    local meta_dir package_json

    meta_dir="$(mktemp -d "$STAGING_DIR/app-version.XXXXXX")"
    package_json="$meta_dir/package.json"

    if command -v npx >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
        (
            cd "$meta_dir"
            npx --yes asar extract-file "$APP_DIR/resources/app.asar" package.json >/dev/null 2>&1
        ) || return 1

        node -p "require('$package_json').version" 2>/dev/null || return 1
        return 0
    fi

    return 1
}

map_arch() {
    case "$1" in
        x86_64|amd64) echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        armv7l) echo "armhf" ;;
        *)
            error "Unsupported architecture: $1"
            ;;
    esac
}

detect_arch() {
    if command -v dpkg >/dev/null 2>&1; then
        dpkg --print-architecture
    else
        map_arch "$(uname -m)"
    fi
}

render_control() {
    cat <<EOF
Package: $PACKAGE_NAME
Version: $PACKAGE_VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: $MAINTAINER
Depends: bash, python3, xdg-utils, libc6, libstdc++6, libgcc-s1 | libgcc1, libasound2 | libasound2t64, libatk-bridge2.0-0, libatk1.0-0, libatspi2.0-0, libcairo2, libcups2, libdbus-1-3, libdrm2, libgbm1, libglib2.0-0, libgtk-3-0, libnspr4, libnss3, libpango-1.0-0, libwayland-client0, libx11-6, libx11-xcb1, libxcb1, libxcomposite1, libxdamage1, libxext6, libxfixes3, libxkbcommon0, libxrandr2, libxshmfence1
Description: OpenAI Codex Desktop for Linux
 Locally repackaged Codex Desktop bundle installed under $INSTALL_DIR.
 .
 This package adds a desktop launcher and a thin wrapper script for the
 Electron app bundle prepared in this repository.
 .
 The Codex CLI still needs to be installed separately so the app can launch:
  npm i -g @openai/codex
EOF
}

[ -d "$APP_DIR" ] || error "App directory not found: $APP_DIR"
[ -x "$APP_DIR/start.sh" ] || error "App launcher is missing or not executable: $APP_DIR/start.sh"
[ -s "$APP_DIR/electron" ] || error "Electron binary not found: $APP_DIR/electron"
[ -r "$APP_DIR/version" ] || error "App version file not found: $APP_DIR/version"
[ -r "$APP_DIR/resources/app.asar" ] || error "App ASAR not found: $APP_DIR/resources/app.asar"
command -v dpkg-deb >/dev/null 2>&1 || error "dpkg-deb is required"
command -v install >/dev/null 2>&1 || error "install is required"

if [ -z "$ICON_SOURCE" ]; then
    ICON_SOURCE="$(find "$APP_DIR/content/webview/assets" -maxdepth 1 -type f -name 'app-*.png' | head -1 || true)"
fi

if [ -z "$ICON_SOURCE" ] || [ ! -r "$ICON_SOURCE" ]; then
    error "Could not find Codex icon PNG under $APP_DIR/content/webview/assets"
fi

if [ -z "${APP_VERSION:-}" ]; then
    APP_VERSION="$(detect_codex_app_version || true)"
fi

APP_VERSION="${APP_VERSION:-$(tr -d '\n' < "$APP_DIR/version")}"
PACKAGE_VERSION="${PACKAGE_VERSION:-${APP_VERSION}-1}"
ARCH="${ARCH:-$(detect_arch)}"
MAINTAINER_NAME="${MAINTAINER_NAME:-Codex Desktop Linux Maintainers}"
MAINTAINER_EMAIL="${MAINTAINER_EMAIL:-noreply@example.com}"
MAINTAINER="$MAINTAINER_NAME <$MAINTAINER_EMAIL>"

PACKAGE_ROOT="$STAGING_DIR/${PACKAGE_NAME}_${PACKAGE_VERSION}_${ARCH}"
mkdir -p "$PACKAGE_ROOT/DEBIAN"
mkdir -p "$PACKAGE_ROOT$INSTALL_DIR"
mkdir -p "$OUTPUT_DIR"

cp -a "$APP_DIR/." "$PACKAGE_ROOT$INSTALL_DIR/"

install -Dm755 "$SCRIPT_DIR/packaging/deb/usr/bin/codex-desktop" \
    "$PACKAGE_ROOT/usr/bin/codex-desktop"
install -Dm644 "$SCRIPT_DIR/packaging/deb/usr/share/applications/codex-desktop.desktop" \
    "$PACKAGE_ROOT/usr/share/applications/codex-desktop.desktop"
install -Dm644 "$SCRIPT_DIR/packaging/deb/usr/share/doc/codex-desktop-linux/README.Debian" \
    "$PACKAGE_ROOT/usr/share/doc/$PACKAGE_NAME/README.Debian"
install -Dm644 "$SCRIPT_DIR/LICENSE" \
    "$PACKAGE_ROOT/usr/share/doc/$PACKAGE_NAME/copyright"
install -Dm644 "$ICON_SOURCE" \
    "$PACKAGE_ROOT/usr/share/pixmaps/codex-desktop.png"
install -Dm644 "$ICON_SOURCE" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/512x512/apps/codex-desktop.png"

render_control > "$PACKAGE_ROOT/DEBIAN/control"

OUTPUT_PATH="$OUTPUT_DIR/${PACKAGE_NAME}_${PACKAGE_VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$PACKAGE_ROOT" "$OUTPUT_PATH" >/dev/null

echo "Built: $OUTPUT_PATH"
