#!/bin/sh
# Downloads vendored JS assets from the npm registry and verifies SHA-256 integrity.
#
# All three packages are extracted directly from their npm tarballs so no CDN
# trust is required.  Versions and expected hashes are pinned below; update
# them together whenever a dependency is bumped.
#
# Usage:
#   ./scripts/download-vendor.sh               — writes to static/vendor/ (local dev)
#   ./scripts/download-vendor.sh /some/path    — writes to that directory (Docker build)
#
# Requirements: curl, sha256sum
set -e

VENDOR="${1:-$(dirname "$0")/../static/vendor}"
mkdir -p "$VENDOR"

# ── Pinned versions ────────────────────────────────────────────────────────────
ALPINE_PKG="alpinejs@3.14.9"
ALPINE_FILE="dist/cdn.min.js"
ALPINE_SHA256="3ed1eed252488921df65e363d6715deb04d7f92aaedb9e52199fdf73cb1e0ad3"

CHART_PKG="chart.js@4.4.7"
CHART_FILE="dist/chart.umd.js"
CHART_SHA256="2812cb8825fdc57469eb2f7bb055e9429244e599920511ee477e828499b632cb"

TAILWIND_PKG="@tailwindcss/browser@4.0.15"
TAILWIND_FILE="dist/index.global.js"
TAILWIND_SHA256="bbf2410ee78b88fe2753fe56d2ef268f3bca9bb4e08f3173be9cbfda8aa6ab38"
# ──────────────────────────────────────────────────────────────────────────────

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

verify() {
    local file="$1" expected="$2" label="$3"
    actual=$(sha256sum "$file" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        echo "INTEGRITY FAILURE: $label" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        exit 1
    fi
    echo "  verified: $label"
}

fetch_npm_file() {
    local pkg="$1" inner_path="$2" dest="$3" expected_hash="$4" label="$5"
    echo "Fetching $label from npm ($pkg)..."
    # Build the registry tarball URL from the package spec (name@version).
    # Handles both plain packages (foo@1.2.3) and scoped packages (@scope/foo@1.2.3).
    local version="${pkg##*@}"
    local name="${pkg%@*}"
    # For scoped packages the leading '@' was stripped by the %@* above, so restore it.
    case "$pkg" in
        @*) name="@${name#@}" ;;
    esac
    local basename="${name##*/}"  # strip scope prefix for the filename part
    local url="https://registry.npmjs.org/${name}/-/${basename}-${version}.tgz"
    local tarball="$TMPDIR/${basename}-${version}.tgz"
    curl -fsSL "$url" -o "$tarball"
    tar xzf "$tarball" -C "$TMPDIR" "package/$inner_path"
    verify "$TMPDIR/package/$inner_path" "$expected_hash" "$label"
    cp "$TMPDIR/package/$inner_path" "$dest"
    rm -rf "$TMPDIR/package" "$tarball"
}

fetch_npm_file "$ALPINE_PKG"   "$ALPINE_FILE"   "$VENDOR/alpine.min.js"   "$ALPINE_SHA256"   "Alpine.js 3.14.9"
fetch_npm_file "$CHART_PKG"    "$CHART_FILE"    "$VENDOR/chart.min.js"    "$CHART_SHA256"    "Chart.js 4.4.7"
fetch_npm_file "$TAILWIND_PKG" "$TAILWIND_FILE" "$VENDOR/tailwind.cdn.js" "$TAILWIND_SHA256" "@tailwindcss/browser 4.0.15"

echo "Vendor assets ready in $VENDOR"
