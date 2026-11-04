"""Generate the subscription feed from current official schedules only."""

import argparse
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUTPUT_FILE = Path(__file__).with_name("crvena_zvezda.ics")
TZ = ZoneInfo("Europe/Belgrade")
CLUB_URL = "https://www.crvenazvezdafk.com/sr-latn/raspored-rezultati"
SUPERLIGA = "Superliga Srbije"
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\.?")


def norm(value):
    value = unicodedata.normalize("NFKD", value.lower().replace("đ", "dj"))
    return re.sub(r"[^a-z0-9]", "", value)


TEAM_NAMES = {
    norm(alias): name
    for name, aliases in {
        "Crvena zvezda": ("Crvena zvezda", "Red Star Belgrade"),
        "Radnički Niš": ("Radnički", "Radnički Niš"),
        "Radnički 1923": ("Radnički 1923",),
        "Čukarički": ("Čukarički", "Čukarički DOO"),
        "IMT": ("IMT", "IMT MrBit"),
        "Mladost": ("Mladost", "Mladost Lučani"),
        "OFK Beograd": ("OFK Beograd",),
        "Inter Eskaldes": ("Inter Eskaldes", "Inter Escaldes"),
    }.items()
    for alias in aliases
}


def team_name(value):
    value = " ".join(value.split())
    return TEAM_NAMES.get(norm(value), value.title())


def season_for(day):
    year = day.year if day.month >= 7 else day.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


def fss_url(season):
    first, last = season.split("-")
    return f"https://fss.rs/takmicenje/mozzart-bet-super-liga-srbije-{first[-2:]}-{last}/?script=lat"


@dataclass(frozen=True)
class Fixture:
    season: str
    league: str
    round: str
    home: str
    away: str
    day: date
    kickoff: time | None
    venue: str
    source: str

    @property
    def match_id(self):
        # Neither date nor kick-off participates in match identity.
        return "-".join((self.season, norm(self.league), norm(self.round),
                         norm(self.home), norm(self.away)))

    @property
    def start(self):
        if self.kickoff is None:
            return self.day
        return datetime.combine(self.day, self.kickoff, TZ)


def required_text(parent, selector):
    node = parent.select_one(selector)
    if node is None or not node.get_text(strip=True):
        raise ValueError(f"Missing schedule field: {selector}")
    return node.get_text(" ", strip=True)


def parse_day(value):
    match = DATE_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Unrecognised date: {value!r}")
    day, month, year = map(int, match.groups())
    return date(year, month, day)


def parse_time(value):
    value = value.strip()
    # Official sites use '.', blank and midnight as unpublished-time markers.
    if value in ("", ".", "-", "00:00", "00:00:00"):
        return None
    if not re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", value):
        raise ValueError(f"Unrecognised kick-off: {value!r}")
    parts = list(map(int, value.split(":")))
    return time(*parts)


def parse_club(html, season):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(".superliga-schedule-item")
    if not rows:
        raise ValueError("Club schedule is empty or its markup has changed")
    fixtures = []
    for row in rows:
        teams = row.select(".table-team-name")
        if len(teams) != 2:
            raise ValueError("Club match must have exactly two teams")
        home, away = [team_name(t.get_text(" ", strip=True)) for t in teams]
        if "Crvena zvezda" not in (home, away):
            raise ValueError("Unexpected team in club schedule")
        raw_league = required_text(row, ".liga-info .filter-text")
        league = SUPERLIGA if norm(raw_league) in ("superliga", "superligasrbije") else raw_league
        round_text = required_text(row, ".liga-info")
        round_match = re.search(r"(\d+)\s*\.\s*kolo", round_text, re.I)
        # Knockout phases keep the published label, including the leg.
        round_id = round_match[1] if round_match else round_text.replace(raw_league, "").strip(" ,")
        if not round_id:
            raise ValueError("Missing club competition round")
        day = parse_day(required_text(row, ".match-date"))
        clock = row.select_one(".match-time")
        if clock is None:
            raise ValueError("Missing club kick-off field")
        kickoff = parse_time(clock.get_text(strip=True))
        link = row.select_one("a.matches-link[href]")
        source = urljoin(CLUB_URL, link["href"]) if link else CLUB_URL
        fixtures.append(Fixture(season, league, round_id, home, away,
                                day, kickoff, required_text(row, ".stadium-text"), source))
    return fixtures


def parse_fss(html, season):
    soup = BeautifulSoup(html, "html.parser")
    fixtures = []
    for card in soup.select(".card"):
        rows = card.select(".fss-rezultati__one")
        if not rows:
            continue
        heading = re.search(r"(\d+)\s*\.\s*kolo", card.get_text(" ", strip=True), re.I)
        if not heading:
            raise ValueError("FSS round heading is missing")
        for row in rows:
            teams = row.select(".fss-rezultati__teams .col-6")
            if len(teams) != 2:
                raise ValueError("FSS match must have exactly two teams")
            home, away = [team_name(t.get_text(" ", strip=True)) for t in teams]
            if "Crvena zvezda" not in (home, away):
                continue
            raw = required_text(row, ".fss-rezultati__one-date")
            match = DATE_RE.match(raw)
            if not match:
                raise ValueError(f"Unrecognised FSS date: {raw!r}")
            day = parse_day(match[0])
            kickoff = parse_time(raw[match.end():])
            city = required_text(row, ".fss-rezultati__one-city")
            fixtures.append(Fixture(season, SUPERLIGA, heading[1], home, away,
                                    day, kickoff, city, fss_url(season)))
    if not fixtures:
        raise ValueError("FSS schedule is empty or its markup has changed")
    return fixtures


def unique(fixtures):
    result = {}
    for fixture in fixtures:
        previous = result.get(fixture.match_id)
        if previous and previous != fixture:
            raise ValueError(f"Conflicting duplicate: {fixture.match_id}")
        result[fixture.match_id] = fixture
    return result


def merge_schedules(club, fss):
    result = unique(club)
    for key, official in unique(fss).items():
        club_match = result.get(key)
        if club_match:
            # FSS owns domestic dates/times. Use a club time only on the SAME
            # published date when FSS has not yet provided one.
            kickoff = official.kickoff
            if kickoff is None and official.day == club_match.day:
                kickoff = club_match.kickoff
            official = replace(official, kickoff=kickoff, venue=club_match.venue,
                               source=f"{official.source}\n{club_match.source}")
        result[key] = official
    return list(result.values())


def fetch_html(url):
    retry = Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        response = session.get(url, headers={"User-Agent": "CrvenaZvezdaCalendar/2.0"}, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text


def event_day(event):
    value = event.decoded("dtstart")
    return value.astimezone(TZ).date() if isinstance(value, datetime) else value


def legacy_match(event, fixtures):
    """Reuse published v1 UIDs once; existing subscribers get an update."""
    summary = str(event.get("summary", "")).removeprefix("🔴⚪ ").removeprefix("⚪🔴 ")
    teams = summary.split(" - ")
    if len(teams) != 2:
        return None
    home, away = map(team_name, teams)
    season = season_for(event_day(event))
    description = str(event.get("description", ""))
    candidates = [f for f in fixtures if f.home == home and f.away == away
                  and f.season == season and f"Takmičenje: {f.league}\n" in description + "\n"]
    return candidates[0].match_id if len(candidates) == 1 else None


def is_future(start, now):
    return start >= now if isinstance(start, datetime) else start >= now.astimezone(TZ).date()


def event_content(event):
    ignored = {"DTSTAMP", "LAST-MODIFIED", "SEQUENCE"}
    return {str(k): v.to_ical() for k, v in event.items() if k not in ignored}


def build_calendar(fixtures, previous=None, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    fixtures = list(unique(fixtures).values())
    known_ids = {f.match_id for f in fixtures}
    old_by_id = {}
    for event in previous.walk("VEVENT") if previous is not None else []:
        key = str(event.get("x-match-id", "")) or legacy_match(event, fixtures)
        if is_future(event.decoded("dtstart"), now) and key not in known_ids:
            raise ValueError(f"Previously published future match disappeared: {event['uid']}")
        if key:
            if key in old_by_id:
                raise ValueError(f"Duplicate existing match identity: {key}")
            old_by_id[key] = event

    cal = Calendar()
    cal.add("prodid", "-//Tony Ristic//Crvena Zvezda Calendar//SR")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "🔴⚪ Crvena zvezda")
    cal.add("x-wr-timezone", "Europe/Belgrade")
    for f in sorted(fixtures, key=lambda f: (f.day, f.kickoff or time.min, f.match_id)):
        if not is_future(f.start, now):
            continue
        old = old_by_id.get(f.match_id)
        event = Event()
        title = f"{'🔴⚪' if f.home == 'Crvena zvezda' else '⚪🔴'} {f.home} - {f.away}"
        if f.kickoff is None:
            title += " (satnica nije potvrđena)"
        event.add("summary", title)
        event.add("uid", str(old["uid"]) if old is not None else f"{f.match_id}@cz-calendar")
        event.add("x-match-id", f.match_id)
        # UTC avoids depending on clients' interpretation of VTIMEZONE.
        start = f.start.astimezone(timezone.utc) if f.kickoff is not None else f.day
        event.add("dtstart", start)
        event.add("dtend", start + (timedelta(hours=2) if f.kickoff else timedelta(days=1)))
        event.add("status", "CONFIRMED" if f.kickoff else "TENTATIVE")
        event.add("transp", "TRANSPARENT")
        event.add("location", f.venue)
        note = ("Početak: potvrđena satnica (Europe/Belgrade). Trajanje od 2 sata je procena."
                if f.kickoff else "Vreme početka nije potvrđeno. Prikazan je objavljeni datum; termin je podložan promeni.")
        event.add("description", f"Takmičenje: {f.league}\nKolo/faza: {f.round}\n{note}\nIzvor: {f.source}")
        changed = old is None or event_content(event) != event_content(old)
        event.add("sequence", int(old.get("sequence", 0)) + int(changed) if old is not None else 0)
        stamp = now if changed else old.decoded("dtstamp")
        event.add("dtstamp", stamp)
        event.add("last-modified", stamp)
        cal.add_component(event)
    return cal


def validate_calendar(payload):
    cal = Calendar.from_ical(payload)
    seen = set()
    for event in cal.walk("VEVENT"):
        if event.errors:
            raise ValueError(f"Invalid event: {event.errors}")
        uid = str(event["uid"])
        if uid in seen:
            raise ValueError(f"Duplicate UID: {uid}")
        seen.add(uid)
        start, end = event.decoded("dtstart"), event.decoded("dtend")
        if type(start) is not type(end) or end <= start:
            raise ValueError(f"Invalid event interval: {uid}")
        if isinstance(start, datetime) and start.tzinfo is None:
            raise ValueError(f"Floating kick-off: {uid}")
        if not isinstance(start, datetime) and str(event["status"]) != "TENTATIVE":
            raise ValueError(f"Unpublished kick-off must be tentative: {uid}")
    return cal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=season_for(datetime.now(TZ).date()))
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()
    if not re.fullmatch(r"20\d{2}-\d{2}", args.season):
        parser.error("Season must look like 2026-27")
    # Both sources must succeed. Never replace the feed with incomplete data.
    club = parse_club(fetch_html(CLUB_URL), args.season)
    fss = parse_fss(fetch_html(fss_url(args.season)), args.season)
    fixtures = merge_schedules(club, fss)
    previous = Calendar.from_ical(args.output.read_bytes()) if args.output.exists() else None
    payload = build_calendar(fixtures, previous).to_ical()
    cal = validate_calendar(payload)
    temporary = args.output.with_suffix(".ics.tmp")
    temporary.write_bytes(payload)
    temporary.replace(args.output)
    print(f"Generated {args.output.name} with {len(cal.walk('VEVENT'))} future events from official sources.")


if __name__ == "__main__":
    main()
