#!/usr/bin/env bash
# Builds a fully self-contained BiomViewer.app: no pip install, no venv, no
# PATH resolution needed by the end user. Just drag it to /Applications.
#
# Structure:
#   BiomViewer.app                        <- outer shell, double-click target
#     Contents/MacOS/applet               <- AppleScript droplet (osacompile),
#                                             the only piece that needs to
#                                             handle macOS's "open document"
#                                             Apple Event (argv doesn't work
#                                             for this — see comment below)
#     Contents/Resources/BiomViewerEngine.app  <- PyInstaller build: Python +
#                                             biom-format + pywebview + scipy/
#                                             numpy/h5py/pandas, all bundled
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".build-venv"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet -e . pyinstaller
fi

rm -rf build dist BiomViewer.spec
"$VENV/bin/pyinstaller" --windowed --name BiomViewer \
  --icon scripts/icon.icns \
  --noconfirm \
  biom_viewer/app.py

ENGINE="build_output/BiomViewerEngine.app"
rm -rf build_output && mkdir -p build_output
mv dist/BiomViewer.app "$ENGINE"

# macOS delivers "double-click a document" as an Apple Event, not argv — a
# raw PyInstaller (or any non-Cocoa-delegate) executable just sees an empty
# argv, confirmed by testing. An AppleScript "on open" handler is the
# reliable way to receive it, so that's the executable macOS actually
# launches; it re-execs the bundled engine with the POSIX path as argv[1].
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/launcher.applescript" <<'EOF'
on open theFiles
	set f to POSIX path of (item 1 of theFiles)
	set enginePath to (path to me as text) & "Contents:Resources:BiomViewerEngine.app:Contents:MacOS:BiomViewer"
	do shell script "'" & POSIX path of enginePath & "' " & quoted form of f & " >> /tmp/biom-viewer.log 2>&1 &"
end open
EOF

APPLET_DIR="$TMP/applet"
mkdir -p "$APPLET_DIR"
osacompile -o "$APPLET_DIR/BiomViewer.app" "$TMP/launcher.applescript"
cp -R "$ENGINE" "$APPLET_DIR/BiomViewer.app/Contents/Resources/"

OUT="dist/BiomViewer.app"
rm -rf "$OUT"
mv "$APPLET_DIR/BiomViewer.app" "$OUT"

PLIST="$OUT/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName BiomViewer" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 biom" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string 'BIOM File'" "$PLIST" 2>/dev/null || true

cp scripts/icon.icns "$OUT/Contents/Resources/droplet.icns"
# osacompile also bakes its default icon into a compiled asset catalog,
# which macOS's icon resolver prefers over the loose .icns above.
rm -f "$OUT/Contents/Resources/Assets.car"
touch "$OUT"

echo ""
echo "Built self-contained $OUT ($(du -sh "$OUT" | cut -f1))"
echo "Drag it to /Applications, then double-click any .biom file."
