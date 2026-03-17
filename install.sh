#!/bin/bash
set -Eeuo pipefail

# ============================================================================
# Codex Desktop for Linux — Installer
# Converts the official macOS Codex Desktop app to run on Linux
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${CODEX_INSTALL_DIR:-$SCRIPT_DIR/codex-app}"
ELECTRON_VERSION="40.0.0"
SEVENZIP_VERSION="26.00"
SEVENZIP_VERSION_TAG="${SEVENZIP_VERSION//./}"
MIN_SEVENZIP_MAJOR=22
WORK_DIR="$(mktemp -d)"
ARCH="$(uname -m)"
SEVENZIP_BIN=""
CC_BIN=""
CXX_BIN=""
CXXFLAGS_EXTRA=()
LDFLAGS_EXTRA=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*" >&2; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT
trap 'error "Failed at line $LINENO (exit code $?)"' ERR

# ---- Check dependencies ----
check_deps() {
    local missing=()
    for cmd in node npm npx python3 curl tar unzip; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [ ${#missing[@]} -ne 0 ]; then
        error "Missing dependencies: ${missing[*]}
Install them first:
  sudo apt install nodejs npm python3 curl tar unzip build-essential  # Debian/Ubuntu
  sudo dnf install nodejs npm python3 curl tar unzip && sudo dnf groupinstall 'Development Tools'  # Fedora
  sudo pacman -S nodejs npm python curl tar unzip base-devel  # Arch"
    fi

    NODE_MAJOR=$(node -v | cut -d. -f1 | tr -d v)
    if [ "$NODE_MAJOR" -lt 20 ]; then
        error "Node.js 20+ required (found $(node -v))"
    fi

    if ! command -v make &>/dev/null; then
        error "Build tools (make, gcc/g++ or clang/clang++) required:
  sudo apt install build-essential   # Debian/Ubuntu
  sudo dnf groupinstall 'Development Tools'  # Fedora
  sudo pacman -S base-devel          # Arch"
    fi

    if { ! command -v gcc &>/dev/null && ! command -v clang &>/dev/null; } || \
       { ! command -v g++ &>/dev/null && ! command -v clang++ &>/dev/null; }; then
        error "A C/C++ toolchain is required (gcc/g++ or clang/clang++)"
    fi

    info "All dependencies found"
}

get_sevenzip_major_version() {
    local sevenzip_bin="$1"
    local version=""

    version=$("$sevenzip_bin" i 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+' | head -1 || true)
    [ -n "$version" ] || return 1

    echo "${version%%.*}"
}

download_sevenzip() {
    local sevenzip_arch cache_dir archive_path url

    case "$ARCH" in
        x86_64)  sevenzip_arch="x64" ;;
        aarch64) sevenzip_arch="arm64" ;;
        armv7l)  sevenzip_arch="arm" ;;
        *)       error "Unsupported architecture for 7-Zip: $ARCH" ;;
    esac

    cache_dir="$SCRIPT_DIR/.cache/7zip/$SEVENZIP_VERSION/$sevenzip_arch"
    SEVENZIP_BIN="$cache_dir/7zz"

    if [ -x "$SEVENZIP_BIN" ]; then
        info "Using cached 7-Zip: $SEVENZIP_BIN"
        return
    fi

    mkdir -p "$cache_dir"
    archive_path="$WORK_DIR/7zip.tar.xz"
    url="https://www.7-zip.org/a/7z${SEVENZIP_VERSION_TAG}-linux-${sevenzip_arch}.tar.xz"

    info "Downloading official 7-Zip ${SEVENZIP_VERSION} for Linux..."

    if ! curl -L --progress-bar --max-time 300 --connect-timeout 30 \
            -o "$archive_path" "$url"; then
        error "Failed to download 7-Zip from $url"
    fi

    tar -xJf "$archive_path" -C "$cache_dir" >&2 || \
        error "Failed to unpack 7-Zip archive"

    [ -x "$SEVENZIP_BIN" ] || error "Downloaded 7-Zip archive did not contain 7zz"
}

ensure_sevenzip() {
    local candidate major

    if command -v 7zz &>/dev/null; then
        candidate="$(command -v 7zz)"
        major=$(get_sevenzip_major_version "$candidate" || echo 0)
        if [ "$major" -ge "$MIN_SEVENZIP_MAJOR" ]; then
            SEVENZIP_BIN="$candidate"
            info "Using 7-Zip binary: $SEVENZIP_BIN"
            return
        fi
        warn "Installed 7zz is too old for current Codex DMGs"
    fi

    if command -v 7z &>/dev/null; then
        candidate="$(command -v 7z)"
        major=$(get_sevenzip_major_version "$candidate" || echo 0)
        if [ "$major" -ge "$MIN_SEVENZIP_MAJOR" ]; then
            SEVENZIP_BIN="$candidate"
            info "Using 7-Zip binary: $SEVENZIP_BIN"
            return
        fi
        warn "Installed 7z ($(basename "$candidate")) is too old for current Codex DMGs; p7zip 16.x cannot extract the current Codex installer image"
    fi

    download_sevenzip
    info "Using 7-Zip binary: $SEVENZIP_BIN"
}

compiler_supports_cxx20() {
    local cxx_bin="$1"
    shift
    local test_dir="$WORK_DIR/compiler-check"

    mkdir -p "$test_dir"
    cat > "$test_dir/test.cpp" << 'EOF'
#include <compare>
#include <source_location>
int main() {
    auto order = (1 <=> 2);
    auto loc = std::source_location::current();
    return (order < 0 && loc.line() > 0) ? 0 : 1;
}
EOF
    "$cxx_bin" -std=c++20 "$@" "$test_dir/test.cpp" -o "$test_dir/test-bin" >/dev/null 2>&1
}

select_toolchain() {
    local suffix cc_candidate cxx_candidate

    for suffix in 14 13 12 11 10 ""; do
        if [ -n "$suffix" ]; then
            cc_candidate="$(command -v "gcc-$suffix" 2>/dev/null || true)"
            cxx_candidate="$(command -v "g++-$suffix" 2>/dev/null || true)"
        else
            cc_candidate="$(command -v gcc 2>/dev/null || true)"
            cxx_candidate="$(command -v g++ 2>/dev/null || true)"
        fi

        if [ -n "$cc_candidate" ] && [ -n "$cxx_candidate" ] && \
           compiler_supports_cxx20 "$cxx_candidate"; then
            CC_BIN="$cc_candidate"
            CXX_BIN="$cxx_candidate"
            CXXFLAGS_EXTRA=()
            LDFLAGS_EXTRA=()
            info "Using toolchain: $(basename "$CC_BIN") / $(basename "$CXX_BIN")"
            return
        fi
    done

    for suffix in 18 17 16 15 14 13 12 11 10 ""; do
        if [ -n "$suffix" ]; then
            cc_candidate="$(command -v "clang-$suffix" 2>/dev/null || true)"
            cxx_candidate="$(command -v "clang++-$suffix" 2>/dev/null || true)"
        else
            cc_candidate="$(command -v clang 2>/dev/null || true)"
            cxx_candidate="$(command -v clang++ 2>/dev/null || true)"
        fi

        if [ -n "$cc_candidate" ] && [ -n "$cxx_candidate" ] && \
           compiler_supports_cxx20 "$cxx_candidate"; then
            CC_BIN="$cc_candidate"
            CXX_BIN="$cxx_candidate"
            CXXFLAGS_EXTRA=()
            LDFLAGS_EXTRA=()
            info "Using toolchain: $(basename "$CC_BIN") / $(basename "$CXX_BIN")"
            return
        fi

        if [ -n "$cc_candidate" ] && [ -n "$cxx_candidate" ] && \
           compiler_supports_cxx20 "$cxx_candidate" -stdlib=libc++; then
            CC_BIN="$cc_candidate"
            CXX_BIN="$cxx_candidate"
            CXXFLAGS_EXTRA=(-stdlib=libc++)
            LDFLAGS_EXTRA=(-stdlib=libc++)
            info "Using toolchain: $(basename "$CC_BIN") / $(basename "$CXX_BIN") with libc++"
            return
        fi
    done

    error "A compiler with working C++20 standard library support is required. Install GCC 10+ (recommended) or Clang with libc++/libstdc++ that provides <compare>."
}

resolve_runtime_lib() {
    local lib_name="$1"
    local compiler_path=""
    local resolved_path=""

    if [ -n "${CC_BIN:-}" ]; then
        compiler_path="$("$CC_BIN" -print-file-name="$lib_name" 2>/dev/null || true)"
        if [ -n "$compiler_path" ] && [ "$compiler_path" != "$lib_name" ] && [ -e "$compiler_path" ]; then
            readlink -f "$compiler_path"
            return 0
        fi
    fi

    resolved_path="$(ldconfig -p 2>/dev/null | awk -v lib="$lib_name" '$1==lib {print $NF; exit}')"
    if [ -n "$resolved_path" ] && [ -e "$resolved_path" ]; then
        readlink -f "$resolved_path"
        return 0
    fi

    return 1
}

# ---- Download or find Codex DMG ----
get_dmg() {
    local dmg_dest="$SCRIPT_DIR/Codex.dmg"

    # Reuse existing DMG
    if [ -s "$dmg_dest" ]; then
        info "Using cached DMG: $dmg_dest ($(du -h "$dmg_dest" | cut -f1))"
        echo "$dmg_dest"
        return
    fi

    info "Downloading Codex Desktop DMG..."
    local dmg_url="https://persistent.oaistatic.com/codex-app-prod/Codex.dmg"
    info "URL: $dmg_url"

    if ! curl -L --progress-bar --max-time 600 --connect-timeout 30 \
            -o "$dmg_dest" "$dmg_url"; then
        rm -f "$dmg_dest"
        error "Download failed. Download manually and place as: $dmg_dest"
    fi

    if [ ! -s "$dmg_dest" ]; then
        rm -f "$dmg_dest"
        error "Download produced empty file. Download manually and place as: $dmg_dest"
    fi

    info "Saved: $dmg_dest ($(du -h "$dmg_dest" | cut -f1))"
    echo "$dmg_dest"
}

# ---- Extract app from DMG ----
extract_dmg() {
    local dmg_path="$1"
    info "Extracting DMG with $(basename "$SEVENZIP_BIN")..."

    "$SEVENZIP_BIN" x -y "$dmg_path" -o"$WORK_DIR/dmg-extract" >&2 || \
        error "Failed to extract DMG with $SEVENZIP_BIN"

    local app_dir
    app_dir=$(find "$WORK_DIR/dmg-extract" -maxdepth 3 -name "*.app" -type d | head -1)
    [ -n "$app_dir" ] || error "Could not find .app bundle in DMG"

    info "Found: $(basename "$app_dir")"
    echo "$app_dir"
}

# ---- Build native modules in a clean directory ----
build_native_modules() {
    local app_extracted="$1"

    # Read versions from extracted app
    local bs3_ver npty_ver
    bs3_ver=$(node -p "require('$app_extracted/node_modules/better-sqlite3/package.json').version" 2>/dev/null || echo "")
    npty_ver=$(node -p "require('$app_extracted/node_modules/node-pty/package.json').version" 2>/dev/null || echo "")

    [ -n "$bs3_ver" ] || error "Could not detect better-sqlite3 version"
    [ -n "$npty_ver" ] || error "Could not detect node-pty version"

    info "Native modules: better-sqlite3@$bs3_ver, node-pty@$npty_ver"

    # Build in a CLEAN directory (asar doesn't have full source)
    local build_dir="$WORK_DIR/native-build"
    mkdir -p "$build_dir"
    cd "$build_dir"

    echo '{"private":true}' > package.json

    info "Installing fresh sources from npm..."
    CC="$CC_BIN" CXX="$CXX_BIN" CXXFLAGS="${CXXFLAGS_EXTRA[*]:-}" LDFLAGS="${LDFLAGS_EXTRA[*]:-}" npm install "electron@$ELECTRON_VERSION" --save-dev --ignore-scripts 2>&1 >&2
    CC="$CC_BIN" CXX="$CXX_BIN" CXXFLAGS="${CXXFLAGS_EXTRA[*]:-}" LDFLAGS="${LDFLAGS_EXTRA[*]:-}" npm install "better-sqlite3@$bs3_ver" "node-pty@$npty_ver" --ignore-scripts 2>&1 >&2

    info "Compiling for Electron v$ELECTRON_VERSION (this takes ~1 min)..."
    CC="$CC_BIN" CXX="$CXX_BIN" CXXFLAGS="${CXXFLAGS_EXTRA[*]:-}" LDFLAGS="${LDFLAGS_EXTRA[*]:-}" npx --yes @electron/rebuild -v "$ELECTRON_VERSION" --force 2>&1 >&2

    info "Native modules built successfully"

    # Copy compiled modules back into extracted app
    rm -rf "$app_extracted/node_modules/better-sqlite3"
    rm -rf "$app_extracted/node_modules/node-pty"
    cp -r "$build_dir/node_modules/better-sqlite3" "$app_extracted/node_modules/"
    cp -r "$build_dir/node_modules/node-pty" "$app_extracted/node_modules/"
}

# ---- Extract and patch app.asar ----
patch_asar() {
    local app_dir="$1"
    local resources_dir="$app_dir/Contents/Resources"

    [ -f "$resources_dir/app.asar" ] || error "app.asar not found in $resources_dir"

    info "Extracting app.asar..."
    cd "$WORK_DIR"
    npx --yes asar extract "$resources_dir/app.asar" app-extracted

    # Copy unpacked native modules if they exist
    if [ -d "$resources_dir/app.asar.unpacked" ]; then
        cp -r "$resources_dir/app.asar.unpacked/"* app-extracted/ 2>/dev/null || true
    fi

    # Remove macOS-only modules
    rm -rf "$WORK_DIR/app-extracted/node_modules/sparkle-darwin" 2>/dev/null || true
    find "$WORK_DIR/app-extracted" -name "sparkle.node" -delete 2>/dev/null || true

    # Build native modules in clean environment and copy back
    build_native_modules "$WORK_DIR/app-extracted"

    # Repack
    info "Repacking app.asar..."
    cd "$WORK_DIR"
    npx asar pack app-extracted app.asar --unpack "{*.node,*.so,*.dylib}" 2>/dev/null

    info "app.asar patched"
}

# ---- Download Linux Electron ----
download_electron() {
    info "Downloading Electron v${ELECTRON_VERSION} for Linux..."

    local electron_arch
    case "$ARCH" in
        x86_64)  electron_arch="x64" ;;
        aarch64) electron_arch="arm64" ;;
        armv7l)  electron_arch="armv7l" ;;
        *)       error "Unsupported architecture: $ARCH" ;;
    esac

    local url="https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/electron-v${ELECTRON_VERSION}-linux-${electron_arch}.zip"

    curl -L --progress-bar -o "$WORK_DIR/electron.zip" "$url"
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    unzip -qo "$WORK_DIR/electron.zip"

    info "Electron ready"
}

# ---- Extract webview files ----
extract_webview() {
    local app_dir="$1"
    mkdir -p "$INSTALL_DIR/content/webview"

    # Webview files are inside the extracted asar at webview/
    local asar_extracted="$WORK_DIR/app-extracted"
    if [ -d "$asar_extracted/webview" ]; then
        cp -r "$asar_extracted/webview/"* "$INSTALL_DIR/content/webview/"
        info "Webview files copied"
    else
        warn "Webview directory not found in asar — app may not work"
    fi
}

# ---- Install app.asar ----
install_app() {
    cp "$WORK_DIR/app.asar" "$INSTALL_DIR/resources/"
    if [ -d "$WORK_DIR/app.asar.unpacked" ]; then
        cp -r "$WORK_DIR/app.asar.unpacked" "$INSTALL_DIR/resources/"
    fi
    info "app.asar installed"
}

bundle_runtime_libs() {
    local compat_dir="$INSTALL_DIR/lib"
    local libs=(
        "libstdc++.so.6"
        "libgcc_s.so.1"
    )
    local lib src

    mkdir -p "$compat_dir"
    for lib in "${libs[@]}"; do
        src="$(resolve_runtime_lib "$lib" || true)"
        [ -n "$src" ] || error "Could not locate runtime library: $lib"
        cp -L "$src" "$compat_dir/$lib"
        info "Bundled runtime library: $lib"
    done
}

# ---- Create start script ----
create_start_script() {
    cat > "$INSTALL_DIR/start.sh" << 'SCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEBVIEW_DIR="$SCRIPT_DIR/content/webview"

pkill -f "http.server 5175" 2>/dev/null
sleep 0.3

if [ -d "$WEBVIEW_DIR" ] && [ "$(ls -A "$WEBVIEW_DIR" 2>/dev/null)" ]; then
    cd "$WEBVIEW_DIR"
    python3 -m http.server 5175 &> /dev/null &
    HTTP_PID=$!
    trap "kill $HTTP_PID 2>/dev/null" EXIT
fi

export CODEX_CLI_PATH="${CODEX_CLI_PATH:-$(which codex 2>/dev/null)}"
COMPAT_LIB_DIR="$SCRIPT_DIR/lib"

if [ -d "$COMPAT_LIB_DIR" ]; then
    export LD_LIBRARY_PATH="$COMPAT_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

if [ -z "$CODEX_CLI_PATH" ]; then
    echo "Error: Codex CLI not found. Install with: npm i -g @openai/codex"
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/electron" --no-sandbox "$@"
SCRIPT

    chmod +x "$INSTALL_DIR/start.sh"
    info "Start script created"
}

# ---- Main ----
main() {
    echo "============================================" >&2
    echo "  Codex Desktop for Linux — Installer"       >&2
    echo "============================================" >&2
    echo ""                                             >&2

    check_deps
    ensure_sevenzip
    select_toolchain

    local dmg_path=""
    if [ $# -ge 1 ] && [ -f "$1" ]; then
        dmg_path="$(realpath "$1")"
        info "Using provided DMG: $dmg_path"
    else
        dmg_path=$(get_dmg)
    fi

    local app_dir
    app_dir=$(extract_dmg "$dmg_path")

    patch_asar "$app_dir"
    download_electron
    extract_webview "$app_dir"
    install_app
    bundle_runtime_libs
    create_start_script

    if ! command -v codex &>/dev/null; then
        warn "Codex CLI not found. Install it: npm i -g @openai/codex"
    fi

    echo ""                                             >&2
    echo "============================================" >&2
    info "Installation complete!"
    echo "  Run:  $INSTALL_DIR/start.sh"                >&2
    echo "============================================" >&2
}

main "$@"
