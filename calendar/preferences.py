import datetime

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
from xapp.util import l10n

_ = l10n("clockenstein")

from formatting import capitalize_first


class PreferencesDialog(Gtk.Dialog):
    def __init__(self, parent, settings):
        super().__init__(title=_("Preferences"), transient_for=parent, modal=True)
        self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self.set_default_size(420, -1)

        box = self.get_content_area()
        box.set_border_width(12)
        box.set_spacing(12)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label=_("First day of the week"), xalign=0)
        label.set_hexpand(True)
        row.pack_start(label, True, True, 0)

        combo = Gtk.ComboBoxText()
        combo.append("locale", _("Use locale default"))
        monday = datetime.date(2024, 1, 1)
        combo.append("monday", capitalize_first(monday.strftime("%A")))
        sunday = monday + datetime.timedelta(days=6)
        combo.append("sunday", capitalize_first(sunday.strftime("%A")))
        combo.set_active_id(settings.get_string("first-day-of-week"))
        combo.connect("changed", self._first_day_changed, settings)
        row.pack_end(combo, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.show_all()

    @staticmethod
    def _first_day_changed(combo, settings):
        settings.set_string("first-day-of-week", combo.get_active_id())
