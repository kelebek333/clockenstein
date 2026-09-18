from gi.repository import Gio, GLib

from clockenstein import BUS_INTERFACE, BUS_NAME, BUS_PATH


def notify_changed():
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        connection.call(
            BUS_NAME,
            BUS_PATH,
            BUS_INTERFACE,
            "NotifyChanged",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            None,
        )
    except GLib.Error:
        pass
