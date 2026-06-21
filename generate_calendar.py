from datetime import datetime, timedelta
import re
import requests
from icalendar import Calendar, Event
import pytz

TEAM_ID = "133987"
API_URL = f"https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id={TEAM_ID}"
OUTPUT_FILE = "crvena_zvezda.ics"
TZ = pytz.timezone("Europe/Belgrade")


def clean(text):
    return (text or "").strip()


def parse_start(event):
    date_str = event.get("dateEvent")
    time_str = event.get("strTime")

    if not date_str:
        return None

    if time_str and time_str not in ("00:00:00", "00:00"):
        raw = f"{date_str} {time_str[:8]}"
        dt_utc = pytz.utc.localize(datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"))
        return dt_utc.astimezone(TZ)

    d = datetime.strptime(date_str, "%Y-%m-%d")
    return TZ.localize(datetime(d.year, d.month, d.day, 9, 0))


def make_uid(title, start):
    base = title + start.strftime("%Y%m%d%H%M")
    return re.sub(r"[^a-zA-Z0-9]", "", base).lower() + "@crvena-zvezda-calendar"


def build_calendar(events):
    cal = Calendar()
    cal.add("prodid", "-//Tony Ristic//Crvena Zvezda Calendar//SR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "🔴⚪ Crvena zvezda")
    cal.add("x-wr-timezone", "Europe/Belgrade")

    now = datetime.now(pytz.utc)

    for e in events:
        home = clean(e.get("strHomeTeam"))
        away = clean(e.get("strAwayTeam"))
        league = clean(e.get("strLeague"))
        venue = clean(e.get("strVenue"))
        event_url = clean(e.get("idEvent"))

        start = parse_start(e)
        if not start:
            continue

        if "Crvena" in home or "Red Star" in home:
            title = f"🔴⚪ {home} - {away}"
        else:
            title = f"⚪🔴 {home} - {away}"

        ev = Event()
        ev.add("summary", title)
        ev.add("dtstart", start)
        ev.add("dtend", start + timedelta(hours=2))
        ev.add("dtstamp", now)
        ev.add("uid", make_uid(title, start))
        ev.add("location", venue)
        ev.add(
            "description",
            f"Takmičenje: {league}\n"
            f"Izvor: TheSportsDB\n"
            f"Event ID: {event_url}"
        )

        cal.add_component(ev)

    with open(OUTPUT_FILE, "wb") as f:
        f.write(cal.to_ical())


def main():
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()

    data = response.json()
    events = data.get("events") or []

    future_events = []
    now = datetime.now(TZ)

    for e in events:
        start = parse_start(e)
        if start and start >= now:
            future_events.append(e)

    build_calendar(future_events)
    print(f"Generated {OUTPUT_FILE} with {len(future_events)} future events.")


if __name__ == "__main__":
    main()
