from datetime import datetime, timedelta
import re
import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
import pytz

OUTPUT_FILE = "crvena_zvezda.ics"
TZ = pytz.timezone("Europe/Belgrade")

ZVEZDA_URL = "https://www.crvenazvezdafk.com/sr-latn/vesti/zvezdin-raspored-u-superligi-za-sezonu-2026-27"
TEAM_ID = "133987"
API_URL = f"https://www.thesportsdb.com/api/v1/json/3/eventsnext.php?id={TEAM_ID}"

MONTHS = {
    "januar": 1, "februar": 2, "mart": 3, "april": 4,
    "maj": 5, "jun": 6, "jul": 7, "avgust": 8,
    "septembar": 9, "oktobar": 10, "novembar": 11, "decembar": 12,
}

def norm(s):
    s = (s or "").lower()
    return re.sub(r"[^a-z0-9čćžšđ]", "", s)

def make_start(day, month_name, year):
    return TZ.localize(datetime(int(year), MONTHS[month_name.lower()], int(day), 9, 0))

def add_event(cal, home, away, start, league, venue="", source=""):
    title = f"🔴⚪ {home} - {away}" if norm(home) == norm("Crvena zvezda") else f"⚪🔴 {home} - {away}"

    ev = Event()
    ev.add("summary", title)
    ev.add("dtstart", start)
    ev.add("dtend", start + timedelta(hours=2))
    ev.add("dtstamp", datetime.now(pytz.utc))
    ev.add("location", venue)
    ev.add("description", f"Takmičenje: {league}\nIzvor: {source}")
    ev.add("uid", f"{norm(home)}-{norm(away)}-{start.strftime('%Y%m%d%H%M')}@cz-calendar")
    cal.add_component(ev)

def fetch_official_superliga():
    html = requests.get(ZVEZDA_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)

    pattern = re.compile(
        r"(\d+)\s*\.\s*kolo\s*-\s*(\d{1,2})\.\s*([a-zčćžšđ]+)\s*(2026|2027)\.\s*\n+\s*([^\n]+?)\s*-\s*([^\n]+)",
        re.IGNORECASE
    )

    fixtures = []
    for _, day, month, year, home, away in pattern.findall(text):
        start = make_start(day, month, year)
        fixtures.append({
            "home": home.strip(),
            "away": away.strip(),
            "start": start,
            "league": "Superliga Srbije",
            "venue": "Stadion Rajko Mitić, Beograd" if norm(home) == norm("Crvena zvezda") else "",
            "source": ZVEZDA_URL,
        })
    return fixtures

def api_start(e):
    date_str = e.get("dateEvent")
    time_str = e.get("strTime")
    if not date_str:
        return None

    if time_str and time_str not in ("00:00:00", "00:00"):
        raw = f"{date_str} {time_str[:8]}"
        return pytz.utc.localize(datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")).astimezone(TZ)

    d = datetime.strptime(date_str, "%Y-%m-%d")
    return TZ.localize(datetime(d.year, d.month, d.day, 9, 0))

def fetch_thesportsdb():
    fixtures = []
    try:
        data = requests.get(API_URL, timeout=30).json()
        for e in data.get("events") or []:
            start = api_start(e)
            if not start:
                continue
            fixtures.append({
                "home": e.get("strHomeTeam") or "",
                "away": e.get("strAwayTeam") or "",
                "start": start,
                "league": e.get("strLeague") or "Nepoznato takmičenje",
                "venue": e.get("strVenue") or "",
                "source": "TheSportsDB",
            })
    except Exception as ex:
        print(f"TheSportsDB preskočen: {ex}")
    return fixtures

def main():
    cal = Calendar()
    cal.add("prodid", "-//Tony Ristic//Crvena Zvezda Calendar//SR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "🔴⚪ Crvena zvezda")
    cal.add("x-wr-timezone", "Europe/Belgrade")

    fixtures = fetch_official_superliga() + fetch_thesportsdb()
    now = datetime.now(TZ)
    seen = set()
    count = 0

    for f in fixtures:
        if f["start"] < now:
            continue

        key = (f["start"].strftime("%Y-%m-%d"), norm(f["home"]), norm(f["away"]))
        if key in seen:
            continue
        seen.add(key)

        add_event(cal, f["home"], f["away"], f["start"], f["league"], f["venue"], f["source"])
        count += 1

    with open(OUTPUT_FILE, "wb") as file:
        file.write(cal.to_ical())

    print(f"Generated {OUTPUT_FILE} with {count} future events.")

if __name__ == "__main__":
    main()
