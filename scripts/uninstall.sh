#!/bin/sh
# Remove what scripts/install.sh installed.
#
#   scripts/uninstall.sh [--purge]
#
# Stops the tray, disables autostart, removes the icons it copied and every file listed in
# ~/.local/share/repotray/install-manifest.txt. Your config is kept unless --purge is given
# (which also removes the log and cache directories).
set -eu

purge=0
for arg in "$@"; do
    case "$arg" in
        --purge) purge=1 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

data_home=${XDG_DATA_HOME:-$HOME/.local/share}
share="$data_home/repotray"
manifest="$share/install-manifest.txt"
launcher="$HOME/.local/bin/repotray"

if [ -x "$launcher" ]; then
    "$launcher" quit >/dev/null 2>&1 || true
    "$launcher" autostart disable >/dev/null 2>&1 || true
    "$launcher" icons uninstall >/dev/null 2>&1 || true
fi

if [ -f "$manifest" ]; then
    while IFS= read -r path; do
        case "$path" in
            "$HOME"/*) rm -rf -- "$path" ;;
            *) echo "skipping $path (outside \$HOME)" >&2 ;;
        esac
    done < "$manifest"
    rm -f -- "$manifest"
fi
rmdir "$share/lib" "$share" 2>/dev/null || true

if [ "$purge" = 1 ]; then
    rm -rf -- "${XDG_CONFIG_HOME:-$HOME/.config}/repotray" \
        "${XDG_STATE_HOME:-$HOME/.local/state}/repotray" \
        "${XDG_CACHE_HOME:-$HOME/.cache}/repotray"
fi

# Remove directories the install may have created, but only if they are now empty.
for d in \
    "$data_home/icons/hicolor/scalable/status" "$data_home/icons/hicolor/scalable" \
    "$data_home/icons/hicolor" "$data_home/icons" "$data_home/applications" \
    "${XDG_CONFIG_HOME:-$HOME/.config}/autostart" "${XDG_CONFIG_HOME:-$HOME/.config}" \
    "${XDG_STATE_HOME:-$HOME/.local/state}" "${XDG_CACHE_HOME:-$HOME/.cache}" \
    "$HOME/.local/bin" "$data_home" "$HOME/.local"; do
    case "$d" in
        "$HOME"/?*) rmdir -- "$d" 2>/dev/null || true ;;
    esac
done

if [ "$purge" = 1 ]; then
    echo "repotray removed, including config, logs and cache"
else
    echo "repotray removed (config kept in ${XDG_CONFIG_HOME:-$HOME/.config}/repotray; --purge removes it)"
fi
