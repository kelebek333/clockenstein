import datetime
import locale
import re

import babel.core

from xapp.util import l10n

_ = l10n("clockenstein")

WEEKDAY_NAMES = (_("MON"), _("TUE"), _("WED"), _("THU"), _("FRI"), _("SAT"), _("SUN"))


def locale_first_weekday():
    """Return the locale's first weekday using Python's Monday-based index."""
    try:
        locale_name = babel.core.default_locale(("LC_ALL", "LC_TIME", "LANG"))
        return babel.core.Locale.parse(locale_name).first_week_day
    except (babel.core.UnknownLocaleError, TypeError, ValueError):
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


def format_time(value, time_format="locale"):
    if time_format == "12-hour":
        return value.strftime("%l:%M %p").strip()
    elif time_format == "24-hour":
        return value.strftime("%H:%M")
    else:
        time_pattern = locale.nl_langinfo(locale.T_FMT)
        time_pattern = time_pattern.replace("%T", "%H:%M:%S").replace("%r", "%I:%M:%S %p")
        time_pattern = re.sub(r"([^\w%]?)%(?:E|O)?S", "", time_pattern)
        return value.strftime(re.sub(r"\s+", " ", time_pattern).strip()).strip()
