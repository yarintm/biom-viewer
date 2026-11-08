#!/usr/bin/env bash
# Stamp the bundle identity that makes BiomViewer selectable as the default
# .biom handler. Sourced by build_macos_app.sh and install_macos_app.sh.
#
# Both scripts build the outer app with `osacompile`, which produces a bundle
# with NO CFBundleIdentifier and no declared file type. Two consequences, both
# of which look to the user like "macOS won't let me change the default app":
#
#   1. Launch Services keys the default-handler preference on the bundle id.
#      With none, picking BiomViewer in Get Info > Open with appears to work
#      and then silently reverts -- there is nothing to store the choice
#      against.
#   2. CFBundleTypeExtensions alone (the Carbon-era key) does not declare a
#      type. `.biom` then resolves to a *dynamic* UTI (dyn.age80e4ptry), and
#      LSSetDefaultRoleHandlerForContentType refuses those with -50.
#
# So: give the bundle an id, export a real UTI for .biom, and bind the
# document type to it as Owner.
#
#   stamp_bundle_identity <path to .app>

BUNDLE_ID="dev.yarintamam.biomviewer"
BIOM_UTI="dev.yarintamam.biom"

stamp_bundle_identity() {
  local app="$1"
  local plist="$app/Contents/Info.plist"
  local pb=/usr/libexec/PlistBuddy

  # Launch Services stores the default-handler choice against this.
  $pb -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$plist" 2>/dev/null \
    || $pb -c "Set :CFBundleIdentifier $BUNDLE_ID" "$plist"

  # A real exported UTI, so .biom stops resolving to a dynamic one.
  $pb -c "Delete :UTExportedTypeDeclarations" "$plist" 2>/dev/null || true
  $pb -c "Add :UTExportedTypeDeclarations array" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0 dict" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeIdentifier string $BIOM_UTI" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeDescription string BIOM Table" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo array" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo:0 string public.data" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo:1 string public.content" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification dict" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification:public.filename-extension array" "$plist"
  $pb -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification:public.filename-extension:0 string biom" "$plist"

  # Bind the document type to that UTI and claim it.
  $pb -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes array" "$plist" 2>/dev/null || true
  $pb -c "Delete :CFBundleDocumentTypes:0:LSItemContentTypes:0" "$plist" 2>/dev/null || true
  $pb -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string $BIOM_UTI" "$plist"
  $pb -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Owner" "$plist" 2>/dev/null \
    || $pb -c "Set :CFBundleDocumentTypes:0:LSHandlerRank Owner" "$plist"

  # Editing Info.plist invalidates any existing signature; the bundle ships
  # ad-hoc signed, so re-sign in place.
  codesign --force --deep --sign - "$app" >/dev/null 2>&1 || true
}

# Point Launch Services at this copy and make it the default for .biom.
# Called after the app is in its final location -- registering a build
# artifact leaves a stale entry in the Open With menu forever.
register_as_default() {
  local app="$1"
  local lsr=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
  [ -x "$lsr" ] || return 0
  "$lsr" -f "$app" || true
  # No shell tool sets a default handler, so call the API directly.
  /usr/bin/swift - "$BIOM_UTI" "$BUNDLE_ID" >/dev/null 2>&1 <<'SWIFT' || true
import Foundation
import CoreServices
let a = CommandLine.arguments
LSSetDefaultRoleHandlerForContentType(a[1] as CFString, .all, a[2] as CFString)
SWIFT
}
