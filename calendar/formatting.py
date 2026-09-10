import datetime
import locale
import re
import subprocess

from xapp.util import l10n

_ = l10n("clockenstein")

WEEKDAY_NAMES = (_("MON"), _("TUE"), _("WED"), _("THU"), _("FRI"), _("SAT"), _("SUN"))


def locale_first_weekday():
    """Return the locale's first weekday using Python's Monday-based index."""
    try:
        output = subprocess.check_output(
            ["locale", "-k", "first_weekday", "week-1stday"],
            text=True, stderr=subprocess.DEVNULL,
        )
        values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        first_weekday = int(values["first_weekday"].strip('"'))
        week_origin = datetime.datetime.strptime(
            values["week-1stday"].strip('"'), "%Y%m%d"
        ).date()
        return (week_origin.weekday() + first_weekday - 1) % 7
    except (KeyError, OSError, subprocess.SubprocessError, ValueError):
        return 0


def resolve_first_weekday(value):
    if value == "locale":
        return locale_first_weekday()
    if value == "sunday":
        return 6
    return 0


def ordered_weekday_names(first_weekday):
    return WEEKDAY_NAMES[first_weekday:] + WEEKDAY_NAMES[:first_weekday]


def start_of_week(date, first_weekday):
    return date - datetime.timedelta(days=(date.weekday() - first_weekday) % 7)


def capitalize_first(value):
    return value[:1].upper() + value[1:]


def format_time(value):
    pattern = locale.nl_langinfo(locale.T_FMT)
    if "%I" in pattern or "%r" in pattern:
        return value.strftime("%l:%M%P").strip()

    pattern = pattern.replace("%T", "%H:%M:%S")
    pattern = re.sub(r"([:.])?%S", "", pattern)
    return value.strftime(pattern).strip()
