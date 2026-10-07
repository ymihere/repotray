#!/bin/sh
# Install repotray for the current user on Linux, without pip.
#
#   scripts/install.sh [--autostart] [--no-start]
#
# Copies the package to ~/.local/share/repotray/lib, writes the launcher ~/.local/bin/repotray,
# installs the tray icons into the user icon theme, adds a menu entry and starts the tray.
# Re-running upgrades in place (a running tray is restarted). Never uses sudo.
# Everything written is listed in ~/.local/share/repotray/install-manifest.txt for uninstall.sh.
set -eu

autostart=0
start=1
for arg in "$@"; do
    case "$arg" in
        --autostart) autostart=1 ;;
        --no-start) start=0 ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

here=$(cd "$(dirname "$0")/.." && pwd)
src="$here/src/repotray"
[ -d "$src" ] || { echo "run this from a repotray checkout (missing $src)" >&2; exit 1; }

data_home=${XDG_DATA_HOME:-$HOME/.local/share}
share="$data_home/repotray"
lib="$share/lib"
bindir="$HOME/.local/bin"
launcher="$bindir/repotray"
apps="$data_home/applications"
desktop="$apps/repotray.desktop"
manifest="$share/install-manifest.txt"

python=$(command -v python3 || true)
[ -n "$python" ] || { echo "python3 not found; install Python 3.11 or newer" >&2; exit 1; }
if ! "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "repotray needs Python >= 3.11 (found $("$python" -V 2>&1))" >&2
    exit 1
fi

if ! "$python" - <<'EOF'
import sys
try:
    import gi
except ImportError:
    sys.exit(1)
ok = False
for name, ver in (("XApp", "1.0"), ("AyatanaAppIndicator3", "0.1"), ("AppIndicator3", "0.1")):
    try:
        gi.require_version(name, ver)
        ok = True
        break
    except ValueError:
        pass
sys.exit(0 if ok else 2)
EOF
then
    echo "repotray needs PyGObject with the XApp or AppIndicator typelib. On Debian/Ubuntu/Mint:" >&2
    echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-xapp-1.0       # Cinnamon, MATE, Xfce" >&2
    echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1   # others" >&2
    echo "(optional: gir1.2-notify-0.7 for notifications)" >&2
    exit 1
fi

# Stop a running tray before replacing its files (upgrade).
was_running=0
if [ -x "$launcher" ] && "$launcher" quit >/dev/null 2>&1; then
    was_running=1
fi

mkdir -p "$lib" "$bindir" "$apps"
rm -rf "$lib/repotray"
cp -R "$src" "$lib/repotray"
find "$lib/repotray" -name __pycache__ -type d -prune -exec rm -rf {} +

cat > "$launcher" <<EOF
#!/bin/sh
# repotray launcher written by scripts/install.sh
PYTHONPATH="$lib\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
exec /usr/bin/env python3 -m repotray "\$@"
EOF
chmod 755 "$launcher"

cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=repotray
GenericName=Git repositories tray
Comment=Shows which of your git clones have work to push or pull
Exec=$launcher tray
Icon=repotray-symbolic
Terminal=false
Categories=Development;RevisionControl;Utility;
Keywords=git;repository;push;pull;tray;
EOF

"$launcher" icons install >/dev/null

{
    echo "$lib/repotray"
    echo "$launcher"
    echo "$desktop"
} > "$manifest"

if [ "$autostart" = 1 ]; then
    "$launcher" autostart enable
fi

echo "installed repotray $("$launcher" --version) to $lib"
case ":$PATH:" in
    *":$bindir:"*) ;;
    *) echo "note: $bindir is not on your PATH; log out and back in, or add it" ;;
esac

if [ "$start" = 1 ] || [ "$was_running" = 1 ]; then
    if command -v setsid >/dev/null 2>&1; then
        setsid "$launcher" tray >/dev/null 2>&1 < /dev/null &
    else
        nohup "$launcher" tray >/dev/null 2>&1 < /dev/null &
    fi
    echo "tray started"
fi
