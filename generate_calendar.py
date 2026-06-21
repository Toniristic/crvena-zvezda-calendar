from datetime import datetime, timedelta
import re
import requests
from icalendar import Calendar, Event
import pytz

TEAM_ID = "133987"
API_URL = f"https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id={TEAM_ID}"
OUTPUT_FILE = "crvena_zvezda.ics"
TZ = pytz.timezone("Europe/Belgrade")

MANUAL_FIXTURES = [
    ("2026-07-18", "Crvena zvezda", "Mačva", "Superliga Srbije"),
    ("2026-07-25", "Crvena zvezda", "Vojvodina", "Superliga Srbije"),
    ("2026-08-01", "Radnik", "Crvena zvezda", "Superliga Srbije"),
    ("2026-08-08", "Crvena zvezda", "Novi Pazar", "Superliga Srbije"),
    ("2026-08-15", "Železničar", "Crvena zvezda", "Superliga Srbije"),
    ("2026-08-22", "Crvena zvezda", "Čukarički", "Superliga Srbije"),
    ("2026-08-29", "Zemun", "Crvena zvezda", "Superliga Srbije"),
    ("2026-09-05", "Crvena zvezda", "Partizan", "Superliga Srbije"),
    ("2026-09-12", "IMT", "Crvena zvezda", "Superliga Srbije"),
    ("2026-09-19", "Crvena zvezda", "Radnički Niš", "Superliga Srbije"),
    ("2026-10-10", "Radnički 1923", "Crvena zvezda", "Superliga Srbije"),
    ("2026-10-17", "Crvena zvezda", "Mladost", "Superliga Srbije"),
    ("2026-10-24", "OFK Beograd", "Crvena zvezda", "Superliga Srbije"),
    ("2026-11-01", "Mačva", "Crvena zvezda", "Superliga Srbije"),
    ("2026-11-07", "Vojvodina", "Crvena zvezda", "Superliga Srbije"),
    ("2026-11-21", "Crvena zvezda", "Radnik", "Superliga Srbije"),
    ("2026-11-28", "Novi Pazar", "Crvena zvezda", "Superliga Srbije"),
    ("2026-12-06", "Crvena zvezda", "Železničar", "Superliga Srbije"),
    ("2027-02-06", "Čukarički", "Crvena zvezda", "Superliga Srbije"),
    ("2027-02-13", "Crvena zvezda", "Zemun", "Superliga Srbije"),
    ("2027-02-20", "Partizan", "Crvena zvezda", "Superliga Srbije"),
    ("2027-02-27", "Crvena zvezda", "IMT", "Superliga Srbije"),
    ("2027-03-07", "Radnički Niš", "Crvena zvezda", "Superliga Srbije"),
    ("2027-03-13", "Crvena zvezda", "Radnički 1923", "Superliga Srbije"),
    ("2027-03-20", "Mladost", "Crvena zvezda", "Superliga Srbije"),
    ("2027-04-03", "Crvena zvezda", "OFK Beograd", "Superliga Srbije"),
]

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def start_at_9(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return TZ.localize(datetime(d.year, d.month, d.day, 9, 0))

def add_event(cal, home, away, start, league, venue="", source="Manual"):
    title = f"🔴⚪ {home} - {away}" if "Crvena" in home else f"⚪🔴 {home} - {away}"
    ev = Event()
    ev.add("summary", title)
    ev.add("dtstart", start)
    ev.add("dtend", start + timedelta(hours=2))
    ev.add("dtstamp", datetime.now(pytz.utc))
    ev.add("location", venue)
    ev.add("description", f"Takmičenje: {league}\nIzvor: {source}")
    ev.add("uid", f"{norm(home)}-{norm(away)}-{start.strftime('%Y%m%d%H%M')}@cz-calendar")
    cal.add_component(ev)

def parse_api_start(e):
    date_str = e.get("dateEvent")
    time_str = e.get("strTime")
    if not date_str:
        return None
    if time_str and time_str not in ("00:00:00", "00:00"):
        raw = f"{date_str} {time_str[:8]}"
        return pytz.utc.localize(datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")).astimezone(TZ)
    return start_at_9(date_str)

def main():
    cal = Calendar()
    cal.add("prodid", "-//Tony Ristic//Crvena Zvezda Calendar//SR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "🔴⚪ Crvena zvezda")
    cal.add("x-wr-timezone", "Europe/Belgrade")

    seen = set()

    for date_str, home, away, league in MANUAL_FIXTURES:
        start = start_at_9(date_str)
        key = (date_str, norm(home), norm(away))
        seen.add(key)
        venue = "Stadion Rajko Mitić, Beograd" if "Crvena" in home else ""
        add_event(cal, home, away, start, league, venue, "FK Crvena zvezda / ručno uneto")

    try:
        data = requests.get(API_URL, timeout=30).json()
        for e in data.get("events") or []:
            home = e.get("strHomeTeam") or ""
            away = e.get("strAwayTeam") or ""
            start = parse_api_start(e)
            if not start:
                continue
            key = (start.strftime("%Y-%m-%d"), norm(home), norm(away))
            if key in seen:
                continue
            add_event(
                cal, home, away, start,
                e.get("strLeague") or "Nepoznato takmičenje",
                e.get("strVenue") or "",
                "TheSportsDB"
            )
    except Exception as ex:
        print(f"TheSportsDB preskočen: {ex}")

    with open(OUTPUT_FILE, "wb") as f:
        f.write(cal.to_ical())

    print(f"Generated {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
