"""GTK 3 user interface shared by the Linux backends. Imports gi; never import from core."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
