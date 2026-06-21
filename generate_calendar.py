from datetime import datetime, timedelta
import re
import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
import pytz

TEAM_URL = "https://www.fotmob.com/teams/8687/overview/fk-crvena-zvezda"
OUTPUT_FILE = "crvena_zvezda.ics"

BELGRADE = pytz.timezone("Europe/Belgrade")


def parse_fixtures_from_text(text):
    fixtures = []

    pattern = re.compile(
        r"([A-Z][a-z]+ \d{1,2}, 2026):\s*(.*?)\s*-\s*(vs|at)\s*(.*?)(?=;|$)"
    )

    for match in pattern.finditer(text):
        date_str, competition, home_away, opponent = match.groups()

        date_obj = datetime.strptime(date_str, "%B %d, %Y")
        start = BELGRADE.localize(
            datetime(date_obj.year, date_obj.month, date_obj.day, 9, 0)
        )

        if home_away == "vs":
            title = f"🔴⚪ Crvena zvezda - {opponent.strip()}"
            location = "Stadion Rajko Mitić, Beograd"
        else:
            title = f"⚪🔴 {opponent.strip()} - Crvena zvezda"
            location = ""

        fixtures.append(
            {
                "title": title,
                "start": start,
                "end": start + timedelta(hours=2),
                "competition": competition.strip(),
                "location": location,
                "source": TEAM_URL,
            }
        )

    return fixtures


def build_calendar(fixtures):
    cal = Calendar()
    cal.add("prodid", "-//Tony Ristic//Crvena Zvezda Calendar//SR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "🔴⚪ Crvena zvezda")
    cal.add("x-wr-timezone", "Europe/Belgrade")

    now = datetime.now(pytz.utc)

    for fixture in fixtures:
        event = Event()
        event.add("summary", fixture["title"])
        event.add("dtstart", fixture["start"])
        event.add("dtend", fixture["end"])
        event.add("dtstamp", now)
        event.add("location", fixture["location"])
        event.add(
            "description",
            f"Takmičenje: {fixture['competition']}\n"
            f"Automatski generisan kalendar.\n"
            f"Izvor: {fixture['source']}"
        )

        uid_base = (
            fixture["title"]
            + fixture["start"].strftime("%Y%m%d%H%M")
        )
        uid = re.sub(r"[^a-zA-Z0-9]", "", uid_base).lower()
        event.add("uid", f"{uid}@crvena-zvezda-calendar")

        cal.add_component(event)

    with open(OUTPUT_FILE, "wb") as f:
        f.write(cal.to_ical())


def main():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(TEAM_URL, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    fixtures = parse_fixtures_from_text(text)

    if not fixtures:
        raise RuntimeError("Nisu pronađene buduće utakmice.")

    build_calendar(fixtures)
    print(f"Generated {OUTPUT_FILE} with {len(fixtures)} fixtures.")


if __name__ == "__main__":
    main()
