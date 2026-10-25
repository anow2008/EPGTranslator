#!/bin/sh
# EPGTranslator installer for Enigma2 (Python 3 images: OpenATV, OpenPLi, OpenViX ...)
# Usage:  sh install.sh [--no-restart]
# Env:    DEST=/path/to/plugin/dir   ARCHIVE=/path/to/local.tar.gz (skip download)

REPO="anow2008/EPGTranslator"
BRANCH="main"
URL="https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"
DEST="${DEST:-/usr/lib/enigma2/python/Plugins/Extensions/EPGTranslator}"
WORK="${TMPDIR:-/tmp}/epgtranslator_install"
ARCHIVE="${ARCHIVE:-}"
NO_RESTART=0
[ "$1" = "--no-restart" ] && NO_RESTART=1

say() { echo "[EPGTranslator] $*"; }
die() { say "ERROR: $*"; rm -rf "$WORK"; exit 1; }

download() {
  # $1 = url, $2 = output file
  if command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1" 2>/dev/null && return 0
    wget -q --no-check-certificate -O "$2" "$1" 2>/dev/null && return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$2" "$1" 2>/dev/null && return 0
    curl -fsSLk -o "$2" "$1" 2>/dev/null && return 0
  fi
  return 1
}

command -v tar >/dev/null 2>&1 || die "tar is missing"
PARENT=$(dirname "$DEST")
[ -d "$PARENT" ] || mkdir -p "$PARENT" 2>/dev/null || die "cannot create $PARENT"
[ -w "$PARENT" ] || die "no write permission on $PARENT (run as root)"

rm -rf "$WORK"; mkdir -p "$WORK" || die "cannot create $WORK"

if [ -n "$ARCHIVE" ]; then
  say "Using local archive: $ARCHIVE"
  cp "$ARCHIVE" "$WORK/pkg.tar.gz" || die "cannot read $ARCHIVE"
else
  say "Downloading $URL"
  download "$URL" "$WORK/pkg.tar.gz" || die "download failed (check internet / HTTPS support)"
fi
tar -tzf "$WORK/pkg.tar.gz" >/dev/null 2>&1 || die "downloaded file is not a valid tar.gz"
tar -xzf "$WORK/pkg.tar.gz" -C "$WORK" || die "extract failed"
rm -f "$WORK/pkg.tar.gz"

SRC=$(ls -d "$WORK"/EPGTranslator-* 2>/dev/null | head -n 1)
[ -n "$SRC" ] || SRC=$(ls -d "$WORK"/*/ 2>/dev/null | head -n 1)
[ -d "$SRC" ] || die "package folder not found inside archive"

for f in plugin.py __init__.py AutoflushCache.py HTML5Entities.py Skin.py keymap.xml setup.xml; do
  [ -f "$SRC/$f" ] || die "missing file in package: $f"
done

if command -v python3 >/dev/null 2>&1; then
  for f in "$SRC"/*.py; do
    python3 -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$f" 2>/dev/null \
      || die "syntax error in $(basename "$f") - nothing was installed"
  done
else
  say "WARNING: python3 not found. This plugin needs a Python 3 image."
fi

if [ -d "$DEST" ]; then
  BASE=/home/root; [ -w "$BASE" ] || BASE=/tmp
  BK="$BASE/EPGTranslator_backup_$(date +%Y%m%d_%H%M%S)"
  cp -a "$DEST" "$BK" 2>/dev/null && say "Old version backed up to $BK" || say "WARNING: backup failed"
  rm -rf "$DEST"
fi

mkdir -p "$DEST" || die "cannot create $DEST"
cp -a "$SRC"/. "$DEST"/ || die "copy failed"
rm -rf "$DEST/README.md" "$DEST/.git" "$DEST/.github" "$DEST/.gitignore"
rm -f "$DEST"/*.pyc "$DEST"/_init_orig.*
rm -rf "$DEST/__pycache__"

chown -R root:root "$DEST" 2>/dev/null
find "$DEST" -type d -exec chmod 755 {} \;
find "$DEST" -type f -exec chmod 644 {} \;

[ -d "$DEST/pic" ] || say "WARNING: pic/ folder missing - the screen will have no images"
[ -f "$DEST/plugin.png" ] || say "WARNING: plugin.png missing - default menu icon will be used"

rm -rf "$WORK"
say "Installed to $DEST"

if [ "$NO_RESTART" = "1" ]; then
  say "Done. Restart the GUI to load the plugin."
  exit 0
fi

say "Restarting the GUI in 3 seconds..."
sleep 3
if [ -d /run/systemd/system ]; then
  systemctl restart enigma2
else
  killall -9 enigma2
fi
