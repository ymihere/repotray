#!/bin/sh
# Simulate a click on repotray's tray icon through the XApp status applet's D-Bus interface.
#   scripts/dev/click-tray.sh BUTTON [X Y POSITION]
# BUTTON 1 = left (panel), 2 = middle (fetch all), 3 = right (control menu).
# X/Y default to the right end of the primary monitor's bottom panel; POSITION is a
# Gtk.PositionType (3 = bottom). Run it from a separate process, never from the tray itself.
set -eu
button=${1:?usage: click-tray.sh BUTTON [X Y POSITION]}
name=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.ListNames | tr -d "[]()'," | tr ' ' '\n' \
    | grep '^org\.x\.StatusIcon\..*repotray' | head -n1)
if [ -z "$name" ]; then
    echo "no repotray status icon on the session bus" >&2
    exit 1
fi
if [ $# -ge 4 ]; then
    x=$2 y=$3 pos=$4
else
    geom=$(python3 - <<'PY'
import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk
d = Gdk.Display.get_default()
m = d.get_primary_monitor() or d.get_monitor(0)
g, w = m.get_geometry(), m.get_workarea()
print(g.x + g.width - 400, w.y + w.height, 3)
PY
)
    set -- "$button" $geom
    x=$2 y=$3 pos=$4
fi
t=$(date +%s)
gdbus call --session --dest "$name" --object-path /org/x/StatusIcon/Icon \
    --method org.x.StatusIcon.ButtonPress "$x" "$y" "$button" "$t" "$pos" >/dev/null
gdbus call --session --dest "$name" --object-path /org/x/StatusIcon/Icon \
    --method org.x.StatusIcon.ButtonRelease "$x" "$y" "$button" "$t" "$pos" >/dev/null
echo "clicked $button on $name at $x,$y (position $pos)"
