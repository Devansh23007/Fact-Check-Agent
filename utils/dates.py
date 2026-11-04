from datetime import date, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


def published_date(value: str, tz: ZoneInfo) -> date | None:
    """Parse ISO-8601 or RFC-2822 timestamps and return the calendar date in `tz`."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(tz)
    return parsed.date()


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None
