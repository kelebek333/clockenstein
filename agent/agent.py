#!/usr/bin/python3
import datetime
import gettext
import math
import os
import signal

import gi
from setproctitle import setproctitle

gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GSound", "1.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, GSound, Gtk, Pango
from xapp.threading import run_idle
from xapp.util import l10n
from clockenstein import (AGENT_BUS_NAME, BUS_INTERFACE, BUS_NAME, BUS_PATH,
                          DEFAULT_COLOR, SETTINGS_SCHEMA)
from clockenstein.alarms import DEFAULT_SOUND
from clockenstein.drawing import draw_centered_circle
from clockenstein.logging import Logger

_ = l10n("clockenstein")
APPLICATION_NAME = _("Calendar Event")

ALARM_SOUND = DEFAULT_SOUND


class NotificationAgent:
    def __init__(self):
        self.settings = Gio.Settings.new(SETTINGS_SCHEMA)
        self.logger = Logger(self.settings, "clockenstein-notification-agent")
        self.connection = None
        self.subscription_id = 0
        self.alarm_subscription_id = 0
        self.name_owner_id = 0
        self.windows = set()
        self.sound_loops = {}
        self.sound = GSound.Context()

    def run(self, test_reminder=None):
        GLib.set_prgname("org.x.clockenstein.Calendar")
        GLib.set_application_name(APPLICATION_NAME)
        Gtk.init(None)
        Gtk.Window.set_default_icon_name("clockenstein-calendar")
        self.logger.log("Starting")
        self.sound.init(None)
        if test_reminder:
            self._show_reminder(*test_reminder)
        else:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.name_owner_id = Gio.bus_own_name_on_connection(
                self.connection, AGENT_BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                None, None
            )
            self.subscription_id = self.connection.signal_subscribe(
                BUS_NAME,
                BUS_INTERFACE,
                "Reminder",
                BUS_PATH,
                None,
                Gio.DBusSignalFlags.NONE,
                self._reminder_received,
            )
            self.alarm_subscription_id = self.connection.signal_subscribe(
                BUS_NAME, BUS_INTERFACE, "Alarm", BUS_PATH, None,
                Gio.DBusSignalFlags.NONE, self._alarm_received,
            )
            self.logger.log("Listening for reminders")
        signal.signal(signal.SIGINT, lambda _signum, _frame: Gtk.main_quit())
        signal.signal(signal.SIGTERM, lambda _signum, _frame: Gtk.main_quit())
        Gtk.main()
        for window in list(self.windows):
            self._stop_sound_loop(window)
        if self.connection and self.subscription_id:
            self.connection.signal_unsubscribe(self.subscription_id)
        if self.connection and self.alarm_subscription_id:
            self.connection.signal_unsubscribe(self.alarm_subscription_id)
        if self.name_owner_id:
            Gio.bus_unown_name(self.name_owner_id)
        self.logger.log("Stopped")

    def _reminder_received(self, _connection, _sender, _path, _interface,
                           _signal, parameters):
        (uid, summary, location, description, calendar_name, calendar_color,
         start_timestamp, all_day) = parameters.unpack()
        self.logger.log(f"Received reminder for {uid}")
        self._show_reminder(
            uid, summary or APPLICATION_NAME, start_timestamp, location, description,
            calendar_name, calendar_color
        )

    def _alarm_received(self, _connection, _sender, _path, _interface,
                        _signal, parameters):
        alarm_id, label, trigger, sound_file, sound_interval = parameters.unpack()
        self.logger.log(f"Received alarm for {alarm_id}")
        self._show_alarm(alarm_id, label or _("Alarm"), trigger, sound_file,
                         sound_interval)

    def _new_notification_window(self, window_title, title, uid, sound_file,
                                 sound_interval, sound_limit, icon_name):
        window = Gtk.Window(title=window_title)
        window.reminder_uid = uid
        window.sound_file = sound_file
        window.sound_interval = sound_interval
        window.sound_limit = sound_limit
        window.muted = False
        window.set_default_size(420, -1)
        window.set_resizable(False)
        window.set_position(Gtk.WindowPosition.CENTER)
        window.set_urgency_hint(True)
        window.set_keep_above(True)
        window.set_icon_name(icon_name)

        header = Gtk.HeaderBar()
        header.set_show_close_button(False)
        menu_button = Gtk.MenuButton()
        menu_button.set_image(Gtk.Image.new_from_icon_name(
            "open-menu-symbolic", Gtk.IconSize.BUTTON
        ))
        menu = Gtk.Menu()
        mute = Gtk.CheckMenuItem.new_with_label(_("Mute"))
        mute.connect("toggled", self._mute_toggled, window)
        menu.append(mute)
        menu.show_all()
        menu_button.set_popup(menu)
        header.pack_start(menu_button)
        title_label = Gtk.Label(xalign=0)
        title_label.set_markup(
            f'<span size="x-large" weight="bold">{GLib.markup_escape_text(title)}</span>'
        )
        title_label.set_line_wrap(True)
        header.set_custom_title(title_label)
        window.sound_icon = Gtk.Image.new_from_icon_name(
            "audio-volume-high-symbolic", Gtk.IconSize.BUTTON
        )
        window.sound_icon.set_no_show_all(True)
        window.sound_icon.set_margin_end(12)
        header.pack_end(window.sound_icon)
        header_css = Gtk.CssProvider()
        header_css.load_from_data(b"""
            headerbar {
                background-color: @theme_bg_color;
                background-image: none;
                border: none;
                box-shadow: none;
            }
        """)
        header.get_style_context().add_provider(
            header_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        window.set_titlebar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_border_width(18)
        window.add(content)
        return window, content

    @staticmethod
    def _new_action_box():
        buttons = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        buttons.set_layout(Gtk.ButtonBoxStyle.END)
        buttons.set_halign(Gtk.Align.END)
        buttons.set_margin_top(6)
        buttons.set_spacing(6)
        return buttons

    def _new_snooze_button(self, window):
        snooze = Gtk.MenuButton()
        snooze_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        snooze_content.pack_start(Gtk.Label(label=_("Snooze")), False, False, 0)
        snooze_content.pack_start(Gtk.Image.new_from_icon_name(
            "pan-down-symbolic", Gtk.IconSize.MENU
        ), False, False, 0)
        snooze.add(snooze_content)
        snooze.get_style_context().add_class("suggested-action")
        menu = Gtk.Menu()
        for minutes in (1, 5, 10):
            item = Gtk.MenuItem.new_with_label(
                gettext.ngettext("%d minute", "%d minutes", minutes) % minutes
            )
            item.connect("activate", self._snooze, window, minutes)
            menu.append(item)
        menu.show_all()
        snooze.set_popup(menu)
        return snooze

    @run_idle
    def _show_alarm(self, alarm_id, label, trigger, sound_file, sound_interval):
        window, content = self._new_notification_window(
            _("Alarm"), label, f"alarm:{alarm_id}", sound_file, sound_interval,
            10 * 60, "clockenstein-clocks"
        )
        when = datetime.datetime.fromtimestamp(trigger).strftime("%H:%M")
        time_row, _time_label = _detail_row(
            "xsi-alarm-symbolic", when, prominent=True
        )
        content.pack_start(time_row, False, False, 0)

        accent = Gtk.DrawingArea()
        accent.set_size_request(-1, 2)
        accent.set_margin_top(4)
        accent.connect("draw", _draw_calendar_accent, _theme_accent_color(accent))
        content.pack_start(accent, False, False, 0)

        buttons = self._new_action_box()
        open_clocks_button = Gtk.Button()
        open_clocks_button.set_image(Gtk.Image.new_from_icon_name(
            "xsi-alarm-symbolic", Gtk.IconSize.BUTTON
        ))
        open_clocks_button.set_tooltip_text(_("Open Clocks"))
        open_clocks_button.connect("clicked", self._open_clocks)
        snooze = self._new_snooze_button(window)
        dismiss = Gtk.Button.new_with_label(_("Dismiss"))
        dismiss.get_style_context().add_class("destructive-action")
        dismiss.connect("clicked", self._dismiss, window)
        buttons.add(open_clocks_button)
        buttons.add(snooze)
        buttons.add(dismiss)
        content.pack_start(buttons, False, False, 0)

        window.relative_timer_id = 0
        self.windows.add(window)
        window.connect("destroy", self._window_destroyed)
        self._present_window(window)
        if sound_file:
            self._start_sound_loop(window, window.reminder_uid, sound_file,
                                   sound_interval, window.sound_limit)
        return GLib.SOURCE_REMOVE

    @run_idle
    def _show_reminder(self, uid, summary, start_timestamp, location, description,
                       calendar_name, calendar_color):
        window, content = self._new_notification_window(
            APPLICATION_NAME, summary, uid, ALARM_SOUND, 3, 2 * 60,
            "clockenstein-calendar"
        )
        accent_rgba = Gdk.RGBA()
        if not accent_rgba.parse(calendar_color):
            accent_rgba.parse(DEFAULT_COLOR)

        if calendar_name:
            content.pack_start(
                _calendar_detail_row(calendar_name, calendar_color), False, False, 0
            )
        time_row, time_label = _detail_row(
            "preferences-system-time-symbolic", _relative_start_label(start_timestamp),
            prominent=True
        )
        content.pack_start(time_row, False, False, 0)
        window.details_label = time_label
        window.time_icon = time_row.get_children()[0]
        window.start_timestamp = start_timestamp
        window.relative_timer_id = GLib.timeout_add_seconds(
            15, self._update_relative_time, window
        )
        if location:
            location_row, _label = _detail_row(
                "mark-location-symbolic", location, dim=True
            )
            content.pack_start(location_row, False, False, 0)
        if description:
            notes_row, _label = _detail_row(
                "document-edit-symbolic", description, dim=True, max_lines=3
            )
            content.pack_start(notes_row, False, False, 0)

        accent = Gtk.DrawingArea()
        accent.set_size_request(-1, 2)
        accent.set_margin_top(4)
        accent.connect("draw", _draw_calendar_accent, accent_rgba)
        content.pack_start(accent, False, False, 0)

        open_calendar_button = Gtk.Button()
        open_calendar_button.set_image(Gtk.Image.new_from_icon_name(
            "x-office-calendar-symbolic", Gtk.IconSize.BUTTON
        ))
        open_calendar_button.set_tooltip_text(_("Open Calendar"))
        open_calendar_button.connect(
            "clicked", self._open_calendar, start_timestamp, uid
        )

        buttons = self._new_action_box()
        dismiss = Gtk.Button.new_with_label(_("Dismiss"))
        dismiss.get_style_context().add_class("destructive-action")
        snooze = self._new_snooze_button(window)
        buttons.add(open_calendar_button)
        buttons.add(snooze)
        buttons.add(dismiss)
        content.pack_start(buttons, False, False, 0)

        self.windows.add(window)
        window.connect("destroy", self._window_destroyed)
        dismiss.connect("clicked", self._dismiss, window)
        self._present_window(window)
        self._update_relative_time(window)
        self._start_sound_loop(window, uid)
        self.logger.log(f"Showing reminder window for {uid}")
        return GLib.SOURCE_REMOVE

    def _window_destroyed(self, window):
        if window.relative_timer_id:
            GLib.source_remove(window.relative_timer_id)
            window.relative_timer_id = 0
        self._stop_sound_loop(window)
        self.windows.discard(window)
        self.logger.log(f"Dismissed reminder for {window.reminder_uid}")

    def _dismiss(self, _button, window):
        window.destroy()

    def _snooze(self, _item, window, minutes):
        self.logger.log(f"Snoozed reminder for {window.reminder_uid} for {minutes} minute(s)")
        self._stop_sound_loop(window)
        window.hide()
        GLib.timeout_add_seconds(minutes * 60, self._wake_snoozed, window,
                                 window.reminder_uid)

    def _wake_snoozed(self, window, uid):
        if window in self.windows:
            self.logger.log(f"Showing snoozed reminder for {uid}")
            self._present_window(window)
            self._start_sound_loop(window, uid, window.sound_file,
                                   window.sound_interval, window.sound_limit)
        return GLib.SOURCE_REMOVE

    def _present_window(self, window):
        window.show_all()
        window.present()

    def _update_relative_time(self, window):
        if window not in self.windows:
            return GLib.SOURCE_REMOVE
        relative = _relative_start_label(window.start_timestamp)
        window.details_label.set_text(relative)
        started = window.start_timestamp <= datetime.datetime.now().timestamp()
        context = window.details_label.get_style_context()
        if started:
            context.add_class("clockenstein-started")
            window.time_icon.set_from_icon_name(
                "appointment-soon-symbolic", Gtk.IconSize.BUTTON
            )
        else:
            context.remove_class("clockenstein-started")
        return GLib.SOURCE_CONTINUE

    def _open_calendar(self, _item, start_timestamp, uid):
        event_date = datetime.datetime.fromtimestamp(start_timestamp).date().isoformat()
        self.logger.log(f"Opening calendar on {event_date} for {uid}")
        try:
            Gio.Subprocess.new(
                ["clockenstein-calendar", "--date", event_date],
                Gio.SubprocessFlags.NONE,
            )
        except GLib.Error as exc:
            self.logger.error(f"Could not open calendar: {exc.message}")

    def _open_clocks(self, _button):
        try:
            Gio.Subprocess.new(["clockenstein-clocks"], Gio.SubprocessFlags.NONE)
        except GLib.Error as exc:
            self.logger.error(f"Could not open Clocks: {exc.message}")

    def _mute_toggled(self, item, window):
        window.muted = item.get_active()
        if window.muted:
            self._stop_sound_loop(window)
            self.logger.log(f"Muted reminder sound for {window.reminder_uid}")
        elif window.get_visible():
            self._start_sound_loop(
                window, window.reminder_uid, window.sound_file,
                window.sound_interval, window.sound_limit,
            )
            self.logger.log(f"Unmuted reminder sound for {window.reminder_uid}")

    def _start_sound_loop(self, window, uid, sound_file=ALARM_SOUND,
                          sound_interval=3, sound_limit=2 * 60):
        self._stop_sound_loop(window)
        if window.muted:
            return
        if not os.path.exists(sound_file):
            self.logger.warning(f"Alarm sound not found: {sound_file}")
            return
        cancellable = Gio.Cancellable()
        timeout_id = GLib.timeout_add_seconds(sound_limit, self._sound_limit, window, uid)
        self.sound_loops[window] = {
            "cancellable": cancellable,
            "limit_id": timeout_id,
            "replay_id": 0,
            "pulse_id": 0,
            "sound_file": sound_file,
            "sound_interval": sound_interval,
            "sound_limit": sound_limit,
        }
        self._play_sound_iteration(window)
        self.logger.log(f"Started alarm sound loop for {uid}")

    def _play_sound_iteration(self, window):
        state = self.sound_loops.get(window)
        if state is None:
            return
        cancellable = state["cancellable"]
        try:
            window.sound_icon.show()
            window.sound_icon.set_opacity(1.0)
            state["pulse_id"] = GLib.timeout_add(
                500, self._pulse_sound_icon, window
            )
            self.sound.play_full(
                {GSound.ATTR_MEDIA_FILENAME: state["sound_file"]},
                cancellable,
                self._sound_finished,
                window,
            )
        except GLib.Error as exc:
            self._stop_sound_icon(window)
            self.logger.error(f"Could not play alarm sound: {exc.message}")

    def _sound_finished(self, context, result, window):
        self._stop_sound_icon(window)
        try:
            context.play_full_finish(result)
        except GLib.Error as exc:
            state = self.sound_loops.get(window)
            if state is not None and not state["cancellable"].is_cancelled():
                self.logger.error(f"Could not play alarm sound: {exc.message}")
            return
        state = self.sound_loops.get(window)
        if state is not None:
            state["replay_id"] = GLib.timeout_add_seconds(
                state["sound_interval"], self._replay_sound, window
            )

    def _replay_sound(self, window):
        state = self.sound_loops.get(window)
        if state is not None:
            state["replay_id"] = 0
            self._play_sound_iteration(window)
        return GLib.SOURCE_REMOVE

    def _pulse_sound_icon(self, window):
        state = self.sound_loops.get(window)
        if state is None:
            return GLib.SOURCE_REMOVE
        opacity = 0.45 if window.sound_icon.get_opacity() > 0.7 else 1.0
        window.sound_icon.set_opacity(opacity)
        return GLib.SOURCE_CONTINUE

    def _stop_sound_icon(self, window):
        state = self.sound_loops.get(window)
        if state is not None and state["pulse_id"]:
            GLib.source_remove(state["pulse_id"])
            state["pulse_id"] = 0
        window.sound_icon.set_opacity(1.0)
        window.sound_icon.hide()

    def _stop_sound_loop(self, window):
        self._clear_sound_loop(window, remove_limit=True)

    def _clear_sound_loop(self, window, remove_limit=False):
        state = self.sound_loops.pop(window, None)
        if state is None:
            return None
        if state["pulse_id"]:
            GLib.source_remove(state["pulse_id"])
        window.sound_icon.set_opacity(1.0)
        window.sound_icon.hide()
        state["cancellable"].cancel()
        if remove_limit:
            GLib.source_remove(state["limit_id"])
        if state["replay_id"]:
            GLib.source_remove(state["replay_id"])
        return state

    def _sound_limit(self, window, uid):
        state = self._clear_sound_loop(window)
        if state is not None:
            minutes = state["sound_limit"] // 60
            self.logger.log(f"Stopped alarm sound for {uid} after {minutes} minutes")
        return GLib.SOURCE_REMOVE

def _detail_row(icon_name, text, prominent=False, dim=False, max_lines=0):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
    image.set_valign(Gtk.Align.START)
    row.pack_start(image, False, False, 0)
    label = Gtk.Label(label=text, xalign=0)
    label.set_line_wrap(True)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_max_width_chars(50)
    if prominent:
        label.get_style_context().add_class("clockenstein-time")
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .clockenstein-time { font-weight: bold; font-size: 1.1em; }
            .clockenstein-started { color: @warning_color; }
        """)
        label.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    if dim:
        image.set_opacity(0.65)
        label.get_style_context().add_class("dim-label")
    if max_lines:
        label.set_lines(max_lines)
        label.set_ellipsize(Pango.EllipsizeMode.END)
    row.pack_start(label, True, True, 0)
    return row, label


def _calendar_detail_row(name, color):
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    swatch = Gtk.DrawingArea()
    swatch.set_size_request(16, 16)
    rgba = Gdk.RGBA()
    if not rgba.parse(color):
        rgba.parse(DEFAULT_COLOR)
    swatch.connect("draw", draw_centered_circle, rgba)
    row.pack_start(swatch, False, False, 0)
    label = Gtk.Label(label=name, xalign=0)
    row.pack_start(label, True, True, 0)
    return row


def _draw_calendar_accent(widget, cr, rgba):
    allocation = widget.get_allocation()
    cr.rectangle(0, 0, allocation.width, allocation.height)
    Gdk.cairo_set_source_rgba(cr, rgba)
    cr.fill()
    return False


def _theme_accent_color(widget):
    context = widget.get_style_context()
    found, color = context.lookup_color("theme_selected_bg_color")
    if found:
        return color
    return context.get_background_color(Gtk.StateFlags.SELECTED)


def _relative_start_label(start_timestamp, now=None):
    now = now or datetime.datetime.now().astimezone()
    seconds = start_timestamp - now.timestamp()
    if seconds > 0:
        minutes = math.ceil(seconds / 60)
        return gettext.ngettext(
            "Starts in %d minute", "Starts in %d minutes", minutes
        ) % minutes
    if seconds > -60:
        return _("Starts now")
    minutes = math.floor(-seconds / 60)
    return gettext.ngettext(
        "This event started %d minute ago",
        "This event started %d minutes ago",
        minutes,
    ) % minutes


if __name__ == "__main__":
    setproctitle("clockenstein-notification-agent")
    NotificationAgent().run()
