#!/usr/bin/env bash
# Builds a double-clickable BiomViewer.app that opens .biom files with
# whatever `biom-viewer` is currently on PATH. Run this after installing
# the package (`pip install biom-viewer` or `pip install -e .`).
set -euo pipefail

BIN="$(command -v biom-viewer || true)"
if [ -z "$BIN" ]; then
  echo "error: 'biom-viewer' not found on PATH. Install it first (pip install biom-viewer)." >&2
  exit 1
fi

APP_DIR="${1:-$HOME/Applications}"
mkdir -p "$APP_DIR"
APP="$APP_DIR/BiomViewer.app"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/launcher.applescript" <<EOF
on open theFiles
	set f to POSIX path of (item 1 of theFiles)
	do shell script "$BIN " & quoted form of f & " >> /tmp/biom-viewer.log 2>&1 &"
end open
EOF

rm -rf "$APP"
osacompile -o "$APP" "$TMP/launcher.applescript"

PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName BiomViewer" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 biom" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string 'BIOM File'" "$PLIST" 2>/dev/null || true

ICON="$(dirname "$0")/icon.icns"
if [ -f "$ICON" ]; then
  cp "$ICON" "$APP/Contents/Resources/droplet.icns"
  touch "$APP"
fi

echo "Installed $APP (launches: $BIN)"
echo "To make it the default handler: right-click a .biom file -> Get Info -> Open with -> BiomViewer -> Change All..."
