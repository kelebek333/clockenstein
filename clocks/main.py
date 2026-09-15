#!/usr/bin/python3
import datetime
import os
import sys

import gi
from setproctitle import setproctitle

gi.require_version("Gdk", "3.0")
gi.require_version("GSound", "1.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, GSound, Gtk
import xapp.SettingsWidgets as Xs
from xapp.util import l10n

try:
    from formatting import format_time
except ModuleNotFoundError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "calendar"))
    from formatting import format_time
try:
    from alarms import AlarmStore, DEFAULT_SOUND
except ModuleNotFoundError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "daemon"))
    from alarms import AlarmStore, DEFAULT_SOUND

_ = l10n("clockenstein")

BUS_NAME = "org.x.clockenstein.Calendar.Service"
BUS_PATH = "/org/x/clockenstein/Calendar/Service"
BUS_INTERFACE = "org.x.clockenstein.Calendar.Service"


def _locale_weekday_initials():
    monday = datetime.date(2024, 1, 1)
    return tuple(
        (monday + datetime.timedelta(days=offset)).strftime("%A")[:1].upper()
        for offset in range(7)
    )


def _locale_weekday_abbreviations():
    monday = datetime.date(2024, 1, 1)
    return tuple(
        (monday + datetime.timedelta(days=offset)).strftime("%a")
        for offset in range(7)
    )


def _next_alarm_time(alarm, now):
    if not alarm.get("enabled", True):
        return None
    time = datetime.time.fromisoformat(alarm["time"])
    if alarm.get("date"):
        trigger = datetime.datetime.combine(
            datetime.date.fromisoformat(alarm["date"]), time
        )
        return trigger if trigger > now else None
    if alarm.get("repeat"):
        for offset in range(7):
            date = now.date() + datetime.timedelta(days=offset)
            if date.weekday() not in alarm["repeat"]:
                continue
            trigger = datetime.datetime.combine(date, time)
            if trigger > now:
                return trigger
        return None
    trigger = datetime.datetime.combine(now.date(), time)
    return trigger if trigger > now else trigger + datetime.timedelta(days=1)


def _next_alarm_label(alarms):
    now = datetime.datetime.now()
    triggers = [trigger for alarm in alarms
                if (trigger := _next_alarm_time(alarm, now)) is not None]
    if not triggers:
        return None
    next_trigger = min(triggers)
    if next_trigger - now > datetime.timedelta(days=1):
        return None
    minutes = max(1, int((next_trigger - now).total_seconds() + 59) // 60)
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return _("Alarm in %(minutes)d minutes") % {"minutes": minutes}
    if not minutes:
        return _("Alarm in %(hours)d hours") % {"hours": hours}
    return _("Alarm in %(hours)d hours %(minutes)d minutes") % {
        "hours": hours, "minutes": minutes,
    }


class ClocksWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title=_("Clocks"))
        self.set_default_size(540, 420)
        self.set_icon_name("clockenstein-clock")
        self.settings = Gio.Settings.new("org.x.clockenstein.calendar")
        self.settings.connect("changed::time-format", lambda *_args: self.refresh())
        self.alarms = AlarmStore()
        self.sound = GSound.Context()
        self.sound.init(None)
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.subscription = self.connection.signal_subscribe(
            BUS_NAME, BUS_INTERFACE, "AlarmsChanged", BUS_PATH, None,
            Gio.DBusSignalFlags.NONE, self._alarms_changed,
        )
        self.connect("destroy", self._destroyed)

        header = Gtk.HeaderBar(title=_("Alarms"), show_close_button=True)
        add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add.set_tooltip_text(_("Add Alarm"))
        add.connect("clicked", self._edit_alarm, None)
        header.pack_end(add)
        self.set_titlebar(header)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.set_activate_on_single_click(False)
        self.list_box.connect("row-activated", self._alarm_row_activated)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list_box)
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.next_alarm_label = Gtk.Label(xalign=0.5)
        self.next_alarm_label.get_style_context().add_class("clockenstein-next-alarm")
        self.next_alarm_label.set_no_show_all(True)
        self.next_alarm_label.set_margin_top(20)
        self.next_alarm_label.set_margin_bottom(12)
        layout.pack_start(self.next_alarm_label, False, False, 0)
        layout.pack_start(scroll, True, True, 0)
        self.add(layout)
        self.order_refresh_source = 0
        self.refresh()
        self._schedule_order_refresh()

    def _destroyed(self, _window):
        if self.subscription:
            self.connection.signal_unsubscribe(self.subscription)
            self.subscription = 0
        if self.order_refresh_source:
            GLib.source_remove(self.order_refresh_source)
            self.order_refresh_source = 0

    def _schedule_order_refresh(self):
        now = datetime.datetime.now()
        delay = int((60 - now.second - now.microsecond / 1_000_000) * 1000) + 1
        self.order_refresh_source = GLib.timeout_add(delay, self._refresh_alarm_order)

    def _refresh_alarm_order(self):
        self.order_refresh_source = 0
        self.refresh()
        self._schedule_order_refresh()
        return GLib.SOURCE_REMOVE

    def _alarms_changed(self, *_args):
        self.refresh()

    def _notify_alarms_changed(self):
        try:
            self.connection.call(
                BUS_NAME, BUS_PATH, BUS_INTERFACE, "NotifyAlarmsChanged", None,
                None, Gio.DBusCallFlags.NONE, -1, None, None,
            )
        except GLib.Error:
            pass

    def refresh(self):
        for row in self.list_box.get_children():
            self.list_box.remove(row)
        try:
            alarms = self.alarms.list()
        except OSError as exc:
            self.next_alarm_label.hide()
            label = Gtk.Label(label=_('Could not load alarms: %s') % exc, xalign=0.5)
            label.set_margin_top(24)
            self.list_box.add(label)
            self.show_all()
            return
        next_alarm = _next_alarm_label(alarms)
        if next_alarm:
            self.next_alarm_label.set_text(next_alarm)
            self.next_alarm_label.show()
        else:
            self.next_alarm_label.hide()
        now = datetime.datetime.now().time()

        def next_time_key(alarm):
            time = datetime.time.fromisoformat(alarm["time"])
            return time <= now, time

        for alarm in sorted(alarms, key=next_time_key):
            self.list_box.add(self._alarm_row(alarm))
        if not alarms:
            empty = Gtk.Label(label=_("No alarms yet"), xalign=0.5)
            empty.get_style_context().add_class("dim-label")
            empty.set_margin_top(36)
            self.list_box.add(empty)
        self.show_all()

    def _alarm_row(self, alarm):
        row = Gtk.ListBoxRow()
        row.alarm = alarm
        row.get_style_context().add_class("clockenstein-alarm-row")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.set_border_width(12)
        row.add(content)
        time_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        time = Gtk.Label(
            label=format_time(datetime.time.fromisoformat(alarm["time"]),
                              self.settings.get_string("time-format")), xalign=0
        )
        time.get_style_context().add_class("clockenstein-alarm-time")
        time_column.pack_start(time, False, False, 0)
        time_column.pack_start(_alarm_time_info(alarm), False, False, 0)
        content.pack_start(time_column, False, False, 0)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        details.set_valign(Gtk.Align.CENTER)
        label = Gtk.Label(label=alarm.get("label") or _("Alarm"), xalign=0)
        label.get_style_context().add_class("heading")
        label.get_style_context().add_class("clockenstein-alarm-name")
        details.pack_start(label, False, False, 0)
        sound_path = alarm.get("sound", DEFAULT_SOUND)
        if alarm.get("sound_enabled", True) and sound_path:
            sound = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            sound.get_style_context().add_class("clockenstein-alarm-sound")
            sound_icon = Gtk.Image.new_from_icon_name(
                "xsi-audio-x-generic-symbolic", Gtk.IconSize.MENU
            )
            sound_icon.set_pixel_size(12)
            sound.pack_start(sound_icon, False, False, 0)
            sound_name = os.path.splitext(os.path.basename(sound_path))[0]
            sound.pack_start(Gtk.Label(label=sound_name, xalign=0),
                             False, False, 0)
            details.pack_start(sound, False, False, 0)
        content.pack_start(details, True, True, 0)
        edit = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        edit.set_relief(Gtk.ReliefStyle.NONE)
        edit.set_tooltip_text(_("Edit Alarm"))
        edit.connect("clicked", self._edit_alarm, alarm)
        content.pack_start(edit, False, False, 0)
        enabled = Gtk.Switch()
        enabled.set_active(alarm.get("enabled", True))
        enabled.set_valign(Gtk.Align.CENTER)
        enabled.connect("notify::active", self._set_enabled, alarm["id"])
        content.pack_start(enabled, False, False, 0)
        return row

    def _set_enabled(self, switch, _property, alarm_id):
        try:
            self.alarms.set_enabled(alarm_id, switch.get_active())
            self._notify_alarms_changed()
        except (KeyError, OSError):
            self.refresh()

    def _alarm_row_activated(self, _list_box, row):
        alarm = getattr(row, "alarm", None)
        if alarm is not None:
            self._edit_alarm(None, alarm)

    def _preview_sound(self, _button, sound_path):
        path = sound_path[0]
        if path:
            self.sound.play_full(
                {GSound.ATTR_MEDIA_FILENAME: path}, None,
                self._sound_preview_finished, None,
            )

    @staticmethod
    def _sound_preview_finished(context, result, _data):
        try:
            context.play_full_finish(result)
        except GLib.Error:
            pass

    def _edit_alarm(self, _button, alarm):
        dialog = Gtk.Dialog(
            title=_("Edit Alarm") if alarm else _("Add Alarm"),
            transient_for=self, modal=True,
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        if alarm:
            delete = dialog.add_button(_("Delete"), Gtk.ResponseType.REJECT)
            delete.get_style_context().add_class("destructive-action")
        save = dialog.add_button(_("Save"), Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")
        dialog.set_default_size(360, -1)
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_border_width(12)
        editor = Xs.SettingsPage()
        editor.set_spacing(20)
        editor.set_margin_left(15)
        editor.set_margin_right(15)
        editor.set_margin_top(0)
        editor.set_margin_bottom(0)
        content.pack_start(editor, True, True, 0)

        settings_section = editor.add_section()
        entry = Gtk.Entry()
        entry.set_placeholder_text(_("Alarm name"))
        entry.set_text(alarm.get("label", "") if alarm else "")
        name_row = Xs.SettingsWidget()
        name_label = Gtk.Label(label=_("Name"), xalign=0)
        name_label.get_style_context().add_class("dim-label")
        name_row.pack_start(name_label, False, False, 0)
        name_row.pack_end(entry, True, True, 0)
        settings_section.add_row(name_row)
        hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        minute = Gtk.SpinButton.new_with_range(0, 59, 1)
        hour.set_numeric(True)
        minute.set_numeric(True)
        current_time = (datetime.time.fromisoformat(alarm["time"])
                        if alarm else datetime.datetime.now().time())
        hour.set_value(current_time.hour)
        minute.set_value(current_time.minute)
        time_row = Xs.SettingsWidget()
        time_label = Gtk.Label(label=_("Time"), xalign=0)
        time_label.get_style_context().add_class("dim-label")
        time_row.pack_start(time_label, False, False, 0)
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.pack_start(hour, True, True, 0)
        time_box.pack_start(Gtk.Label(label=":"), False, False, 0)
        time_box.pack_start(minute, True, True, 0)
        time_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        time_info = Gtk.Label(xalign=0)
        time_info.get_style_context().add_class("clockenstein-editor-time-info")
        time_info.set_margin_top(6)
        time_info.set_margin_bottom(6)
        time_controls.pack_start(time_info, False, False, 0)
        time_controls.pack_start(time_box, False, False, 0)
        time_row.pack_end(time_controls, True, True, 0)

        days = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        days.set_homogeneous(True)
        repeat = set(alarm.get("repeat", []) if alarm else [])
        buttons = []
        for index, day in enumerate(_locale_weekday_initials()):
            button = Gtk.ToggleButton(label=day)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_tooltip_text(
                _("Every %s") % (datetime.date(2024, 1, 1) +
                                  datetime.timedelta(days=index)).strftime("%A")
            )
            button.set_active(index in repeat)
            days.pack_start(button, True, True, 0)
            buttons.append(button)
        time_controls.pack_start(days, False, False, 0)

        selected_date = (datetime.date.fromisoformat(alarm["date"])
                         if alarm and alarm.get("date") else None)
        date_button = Gtk.MenuButton()
        date_button.set_tooltip_text(_("Choose a date"))
        date_button.add(Gtk.Image.new_from_icon_name(
            "x-office-calendar-symbolic", Gtk.IconSize.BUTTON
        ))
        popover = Gtk.Popover.new(date_button)
        popover_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        popover_content.set_border_width(6)
        calendar = Gtk.Calendar()
        if selected_date:
            calendar.select_month(selected_date.month - 1, selected_date.year)
            calendar.select_day(selected_date.day)
        clear_date = Gtk.Button.new_with_label(_("Clear date"))
        popover_content.pack_start(calendar, False, False, 0)
        popover_content.pack_start(clear_date, False, False, 0)
        popover.add(popover_content)
        popover_content.show_all()
        date_button.set_popover(popover)
        time_box.pack_start(date_button, False, False, 0)
        control_width = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        control_width.add_widget(time_box)
        control_width.add_widget(days)
        dialog.control_width = control_width
        settings_section.add_row(time_row)
        sound_enabled = Gtk.Switch()
        sound_enabled.set_active(alarm.get("sound_enabled", True) if alarm else True)

        sound_path = alarm.get("sound", DEFAULT_SOUND) if alarm else DEFAULT_SOUND
        selected_sound = [sound_path]
        audio_filter = Gtk.FileFilter()
        audio_filter.set_name(_("Audio files"))
        for pattern in ("*.oga", "*.ogg", "*.mp3", "*.wav", "*.flac"):
            audio_filter.add_pattern(pattern)
        sound_button = Gtk.Button(label=os.path.basename(sound_path))
        sound_button.set_hexpand(True)

        def choose_sound(_button):
            chooser = Gtk.FileChooserDialog(
                title=_("Choose a sound"), transient_for=dialog, modal=True,
                action=Gtk.FileChooserAction.OPEN,
            )
            chooser.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
            chooser.add_button(_("Select"), Gtk.ResponseType.OK)
            chooser.set_current_folder(os.path.dirname(DEFAULT_SOUND))
            chooser.add_filter(audio_filter)
            if chooser.run() == Gtk.ResponseType.OK:
                selected_sound[0] = chooser.get_filename()
                sound_button.set_label(os.path.basename(selected_sound[0]))
            chooser.destroy()

        sound_button.connect("clicked", choose_sound)
        sound_picker = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sound_picker.pack_start(sound_button, True, True, 0)
        play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        play.set_tooltip_text(_("Play selected sound"))
        play.connect("clicked", self._preview_sound, selected_sound)
        sound_picker.pack_start(play, False, False, 0)
        sound_picker.pack_start(sound_enabled, False, False, 0)
        sound_interval = Gtk.SpinButton.new_with_range(1, 60, 1)
        sound_interval.set_value(alarm.get("sound_interval", 3) if alarm else 3)
        sound_interval.set_tooltip_text(_("Seconds between sounds"))
        seconds = Gtk.Label(label=_("seconds"))
        interval_picker = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        interval_picker.pack_start(sound_interval, True, True, 0)
        interval_picker.pack_start(seconds, False, False, 0)
        sound_button.set_sensitive(sound_enabled.get_active())
        play.set_sensitive(sound_enabled.get_active())
        sound_interval.set_sensitive(sound_enabled.get_active())
        seconds.set_sensitive(sound_enabled.get_active())
        sound_enabled.connect(
            "notify::active",
            lambda switch, _property: (
                sound_button.set_sensitive(switch.get_active()),
                play.set_sensitive(switch.get_active()),
                sound_interval.set_sensitive(switch.get_active()),
                seconds.set_sensitive(switch.get_active()),
            ),
        )
        sound_row = Xs.SettingsWidget()
        sound_label = Gtk.Label(label=_("Sound"), xalign=0)
        sound_label.get_style_context().add_class("dim-label")
        sound_row.pack_start(sound_label, False, False, 0)
        sound_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sound_controls.pack_start(sound_picker, False, False, 0)
        sound_controls.pack_start(interval_picker, False, False, 0)
        sound_row.pack_end(sound_controls, True, True, 0)
        settings_section.add_row(sound_row)
        label_width = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for label in (name_label, time_label, sound_label):
            label_width.add_widget(label)
        dialog.label_width = label_width

        updating_schedule = False

        def update_time_info(*_args):
            selected_days = [index for index, button in enumerate(buttons)
                             if button.get_active()]
            if len(selected_days) == 7:
                text = _("Every day")
            elif selected_days:
                text = _("Every %s") % ", ".join(
                    _locale_weekday_abbreviations()[index] for index in selected_days
                )
            else:
                date = selected_date
                if date is None:
                    now = datetime.datetime.now()
                    time = datetime.time(hour.get_value_as_int(), minute.get_value_as_int())
                    date = now.date() + datetime.timedelta(
                        days=int(datetime.datetime.combine(now.date(), time) <= now)
                    )
                text = _alarm_date_label(date)
            time_info.set_text(text)

        def day_toggled(_button):
            nonlocal selected_date, updating_schedule
            if updating_schedule:
                return
            if any(button.get_active() for button in buttons):
                selected_date = None
            update_time_info()

        def date_selected(_calendar):
            nonlocal selected_date, updating_schedule
            year, month, day = calendar.get_date()
            selected_date = datetime.date(year, month + 1, day)
            updating_schedule = True
            for button in buttons:
                button.set_active(False)
            updating_schedule = False
            popover.popdown()
            update_time_info()

        def date_cleared(_button):
            nonlocal selected_date
            selected_date = None
            popover.popdown()
            update_time_info()

        for button in buttons:
            button.connect("toggled", day_toggled)
        calendar.connect("day-selected", date_selected)
        clear_date.connect("clicked", date_cleared)
        hour.connect("value-changed", update_time_info)
        minute.connect("value-changed", update_time_info)
        update_time_info()
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.REJECT:
            try:
                self.alarms.delete(alarm["id"])
                self._notify_alarms_changed()
            except (KeyError, OSError):
                pass
        elif response == Gtk.ResponseType.OK:
            selected_days = [index for index, button in enumerate(buttons)
                             if button.get_active()]
            date = selected_date
            if not selected_days and date is None:
                now = datetime.datetime.now()
                time = datetime.time(hour.get_value_as_int(), minute.get_value_as_int())
                date = now.date() + datetime.timedelta(
                    days=int(datetime.datetime.combine(now.date(), time) <= now)
                )
            values = {
                "time": f"{hour.get_value_as_int():02d}:{minute.get_value_as_int():02d}",
                "label": entry.get_text(),
                "date": date.isoformat() if date else None,
                "repeat": selected_days,
                "enabled": alarm.get("enabled", True) if alarm else True,
                "sound_enabled": sound_enabled.get_active(),
                "sound": selected_sound[0],
                "sound_interval": sound_interval.get_value_as_int(),
            }
            try:
                if alarm:
                    self.alarms.update(alarm["id"], values)
                else:
                    self.alarms.create(values)
                self._notify_alarms_changed()
            except (KeyError, ValueError, OSError):
                pass
        dialog.destroy()


def _alarm_time_info(alarm):
    repeat = set(alarm.get("repeat", []))
    if repeat == set(range(7)):
        return _alarm_info_label(_("Every day"))
    if repeat:
        days = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        days.get_style_context().add_class("clockenstein-alarm-days")
        for index, initial in enumerate(_locale_weekday_initials()):
            day = Gtk.Label(xalign=0.5)
            if index in repeat:
                day.set_text(f"•\n{initial}")
                day.get_style_context().add_class("clockenstein-alarm-day-active")
            else:
                day.set_text(f" \n{initial}")
                day.get_style_context().add_class("clockenstein-alarm-day-inactive")
            days.pack_start(day, False, False, 1)
        return days
    if alarm.get("date"):
        date = datetime.date.fromisoformat(alarm["date"])
    else:
        now = datetime.datetime.now()
        time = datetime.time.fromisoformat(alarm["time"])
        date = now.date() + datetime.timedelta(
            days=int(datetime.datetime.combine(now.date(), time) <= now)
        )
    return _alarm_info_label(_alarm_date_label(date))


def _alarm_date_label(date):
    if date == datetime.date.today():
        return _("Today")
    if date == datetime.date.today() + datetime.timedelta(days=1):
        return _("Tomorrow")
    return date.strftime("%A, %-d %B")


def _alarm_info_label(text):
    label = Gtk.Label(label=text, xalign=0)
    label.get_style_context().add_class("clockenstein-alarm-info")
    return label


def _activate(application):
    windows = application.get_windows()
    if windows:
        windows[0].present()
    else:
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(__file__), "style.css"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        ClocksWindow(application).show_all()


def main():
    setproctitle("clockenstein-clocks")
    GLib.set_prgname("org.x.clockenstein.Clocks")
    GLib.set_application_name(_("Clocks"))
    application = Gtk.Application(application_id="org.x.clockenstein.Clocks")
    application.connect("activate", _activate)
    return application.run(sys.argv)


if __name__ == "__main__":
    main()
