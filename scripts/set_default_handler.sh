#!/usr/bin/env bash
# Make an installed BiomViewer.app the default app for .biom files.
#
# Run this once after dragging the app to /Applications. build_macos_app.sh
# cannot do it itself: registering the app from dist/ would point Launch
# Services at a build artifact, which then lingers in the Open With menu
# after the directory is rebuilt or deleted.
#
#   scripts/set_default_handler.sh [path to BiomViewer.app]
set -euo pipefail

APP="${1:-/Applications/BiomViewer.app}"
if [ ! -d "$APP" ]; then
  echo "error: $APP not found. Drag the built app to /Applications first," >&2
  echo "       or pass its path: $0 /path/to/BiomViewer.app" >&2
  exit 1
fi

source "$(dirname "$0")/_bundle_identity.sh"

if ! /usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP/Contents/Info.plist" >/dev/null 2>&1; then
  echo "note: $APP predates the bundle-id fix; stamping it now."
  stamp_bundle_identity "$APP"
fi

register_as_default "$APP"

HANDLER=$(/usr/bin/swift - "$BIOM_UTI" 2>/dev/null <<'SWIFT' || true
import Foundation
import CoreServices
if let h = LSCopyDefaultRoleHandlerForContentType(CommandLine.arguments[1] as CFString, .all)?
             .takeRetainedValue() { print(h) }
SWIFT
)

if [ "$HANDLER" = "$BUNDLE_ID" ]; then
  echo "Done — .biom files now open with $APP"
else
  echo "warning: default handler is '${HANDLER:-<none>}', expected '$BUNDLE_ID'." >&2
  echo "         Another app may be claiming .biom as Owner." >&2
  exit 1
fi
