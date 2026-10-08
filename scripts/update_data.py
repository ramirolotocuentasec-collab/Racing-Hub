from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "current.json"
YEAR = datetime.now(timezone.utc).year

USER_AGENT = "RacingHubAR/1.0 (+https://github.com/) Python urllib"

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
MOTOGP_BASE = "https://api.motogp.pulselive.com/motogp/v1"

NEWS_FEEDS = {
    "f1": "https://espanol.motorsport.com/rss/f1/news/",
    "moto": "https://espanol.motorsport.com/rss/category/moto/news/",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_existing() -> dict:
    if not DATA_FILE.exists():
        return {
            "updatedAt": now_iso(),
            "year": YEAR,
            "f1": {"races": [], "drivers": [], "teams": []},
            "moto": {"races": [], "drivers": [], "teams": []},
            "news": {"f1": [], "moto": []},
            "errors": [],
        }

    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("current.json no contiene un objeto JSON")
        return data
    except Exception as exc:
        print(f"[WARN] No se pudo leer current.json: {exc}")
        return {
            "updatedAt": now_iso(),
            "year": YEAR,
            "f1": {"races": [], "drivers": [], "teams": []},
            "moto": {"races": [], "drivers": [], "teams": []},
            "news": {"f1": [], "moto": []},
            "errors": [],
        }


def save_data(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(DATA_FILE)


def fetch_bytes(url: str, retries: int = 3, timeout: int = 20) -> bytes:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": (
                        "application/json, application/xml, "
                        "text/xml, text/html;q=0.9, */*;q=0.8"
                    ),
                },
            )

            with urlopen(request, timeout=timeout) as response:
                return response.read()

        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc

            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"No se pudo descargar {url}: {last_error}")


def fetch_json(url: str, retries: int = 3, timeout: int = 20):
    raw = fetch_bytes(url, retries=retries, timeout=timeout)
    return json.loads(raw.decode("utf-8-sig"))


def fetch_text(url: str, retries: int = 3, timeout: int = 20) -> str:
    raw = fetch_bytes(url, retries=retries, timeout=timeout)
    return raw.decode("utf-8-sig", errors="replace")


def parse_iso(value):
    if not value:
        return None

    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def to_utc_iso(value) -> str:
    if not value:
        return ""

    dt = parse_iso(value)

    if dt is None:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def first_nonempty(*values):
    for value in values:
        if value is not None and str(value).strip():
            return value
    return ""


def slugify(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_-]+", "-", value)
    return value.strip("-")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def clean_html_text(value: str) -> str:
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url: str, base: str = "") -> str:
    if not url:
        return ""

    url = html.unescape(str(url).strip())

    if url.startswith("//"):
        return "https:" + url

    if base:
        return urljoin(base, url)

    return url


def parse_date_any(value):
    if not value:
        return ""

    value = str(value).strip()

    parsed = parse_iso(value)

    if parsed:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    try:
        parsed = parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    except (TypeError, ValueError, OverflowError):
        return ""


def unique_by_id(items):
    seen = set()
    result = []

    for item in items:
        key = item.get("id") or item.get("url") or item.get("name")

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


# ============================================================
# F1 - JOLPICA
# ============================================================

def f1_datetime(date_value, time_value):
    if not date_value:
        return ""

    if time_value:
        return f"{date_value}T{time_value}"

    return f"{date_value}T00:00:00Z"


def update_f1(data: dict, errors: list) -> None:
    previous = data.get("f1") or {}

    try:
        schedule = fetch_json(
            f"{JOLPICA_BASE}/{YEAR}.json?limit=100"
        )

        driver_standings = fetch_json(
            f"{JOLPICA_BASE}/{YEAR}/driverstandings.json?limit=100"
        )

        constructor_standings = fetch_json(
            f"{JOLPICA_BASE}/{YEAR}/constructorstandings.json?limit=100"
        )

        races = []

        race_list = (
            schedule
            .get("MRData", {})
            .get("RaceTable", {})
            .get("Races", [])
        )

        for race in race_list:
            sessions = []

            for key, label in (
                ("FirstPractice", "Práctica libre 1"),
                ("SecondPractice", "Práctica libre 2"),
                ("ThirdPractice", "Práctica libre 3"),
                ("Sprint", "Sprint"),
                ("SprintShootout", "Sprint Shootout"),
                ("Qualifying", "Clasificación"),
                ("Race", "Carrera"),
            ):
                session = race.get(key)

                if not isinstance(session, dict):
                    continue

                date_value = session.get("date")
                time_value = session.get("time")

                if date_value:
                    sessions.append({
                        "name": label,
                        "date": f1_datetime(date_value, time_value),
                    })

            race_date = ""

            for session in sessions:
                if session["name"] == "Carrera":
                    race_date = session["date"]
                    break

            if not race_date:
                race_date = f1_datetime(
                    race.get("date"),
                    race.get("time"),
                )

            races.append({
                "id": (
                    "f1-"
                    + str(race.get("round", ""))
                    + "-"
                    + slugify(
                        race.get(
                            "raceName",
                            race.get("Circuit", {}).get("circuitName", ""),
                        )
                    )
                ),
                "round": str(race.get("round", "")),
                "name": race.get("raceName", ""),
                "circuit": race.get("Circuit", {}).get("circuitName", ""),
                "country": (
                    race.get("Circuit", {})
                    .get("Location", {})
                    .get("country", "")
                ),
                "race": to_utc_iso(race_date),
                "sessions": [
                    {
                        "name": item["name"],
                        "date": to_utc_iso(item["date"]),
                    }
                    for item in sessions
                ],
            })

        drivers = []

        standings_lists = (
            driver_standings
            .get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )

        if standings_lists:
            for item in standings_lists[0].get("DriverStandings", []):
                driver = item.get("Driver") or {}
                constructors = item.get("Constructors") or []

                team = (
                    constructors[0].get("name", "")
                    if constructors
                    else ""
                )

                name = " ".join(
                    part
                    for part in (
                        driver.get("givenName", ""),
                        driver.get("familyName", ""),
                    )
                    if part
                ).strip()

                drivers.append({
                    "position": int(item.get("position", 0) or 0),
                    "name": name,
                    "driver": driver.get("driverId", ""),
                    "team": team,
                    "points": float(item.get("points", 0) or 0),
                })

        teams = []

        constructor_lists = (
            constructor_standings
            .get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )

        if constructor_lists:
            for item in constructor_lists[0].get(
                "ConstructorStandings",
                [],
            ):
                constructor = item.get("Constructor") or {}

                teams.append({
                    "position": int(item.get("position", 0) or 0),
                    "name": constructor.get("name", ""),
                    "team": constructor.get("constructorId", ""),
                    "points": float(item.get("points", 0) or 0),
                })

        data["f1"] = {
            "races": races,
            "drivers": drivers,
            "teams": teams,
        }

        print(
            f"[OK] F1: {len(races)} carreras, "
            f"{len(drivers)} pilotos, "
            f"{len(teams)} equipos"
        )

    except Exception as exc:
        errors.append(f"F1: {exc}")
        data["f1"] = previous
        print(f"[ERROR] F1: {exc}")


# ============================================================
# MOTOGP - PULSELIVE
# ============================================================

def get_motogp_season():
    seasons = fetch_json(
        f"{MOTOGP_BASE}/results/seasons"
    )

    for season in seasons:
        if int(season.get("year", 0) or 0) == YEAR:
            return season

    raise RuntimeError(
        f"No se encontró la temporada MotoGP {YEAR}"
    )


def get_motogp_category(season_id):
    categories = fetch_json(
        f"{MOTOGP_BASE}/results/categories"
        f"?seasonUuid={quote_plus(str(season_id))}"
    )

    for category in categories:
        name = str(
            category.get("name", "")
        ).lower()

        if "motogp" in name:
            return category

    raise RuntimeError(
        "No se encontró la categoría MotoGP"
    )


def motogp_session_label(session):
    session_type = str(
        session.get("type")
        or session.get("short_name")
        or session.get("shortName")
        or ""
    ).upper()

    mapping = {
        "FP": "Práctica libre",
        "P": "Práctica",
        "P1": "Práctica libre 1",
        "P2": "Práctica libre 2",
        "P3": "Práctica libre 3",
        "PR": "Práctica",
        "Q1": "Clasificación Q1",
        "Q2": "Clasificación Q2",
        "Q": "Clasificación",
        "SPR": "Sprint",
        "SPRINT": "Sprint",
        "RAC": "Carrera",
        "RACE": "Carrera",
        "WUP": "Warm Up",
    }

    if session_type in mapping:
        return mapping[session_type]

    return str(
        session.get("name")
        or session.get("session_name")
        or session.get("type")
        or "Sesión"
    )


def normalize_motogp_event(event, category_id):
    event_id = event.get("id")

    circuit = event.get("circuit") or {}
    country = event.get("country") or {}

    name = first_nonempty(
        event.get("name"),
        event.get("sponsored_name"),
        event.get("short_name"),
        circuit.get("name"),
    )

    sessions = []

    if event_id:
        try:
            sessions = fetch_json(
                f"{MOTOGP_BASE}/results/sessions"
                f"?eventUuid={quote_plus(str(event_id))}"
                f"&categoryUuid={quote_plus(str(category_id))}"
            )

            if not isinstance(sessions, list):
                sessions = []

        except Exception as exc:
            print(
                f"[WARN] No se pudieron cargar sesiones "
                f"de MotoGP {name}: {exc}"
            )
            sessions = []

    normalized_sessions = []

    for session in sessions:
        date_value = session.get("date")

        if not date_value:
            continue

        normalized_sessions.append({
            "name": motogp_session_label(session),
            "date": to_utc_iso(date_value),
            "type": str(
                session.get("type")
                or session.get("short_name")
                or ""
            ),
        })

    normalized_sessions.sort(
        key=lambda item: item.get("date", "")
    )

    race_date = ""

    for session in normalized_sessions:
        raw_type = str(
            session.get("type", "")
        ).upper()

        if raw_type in {"RAC", "RACE"}:
            race_date = session["date"]
            break

    if not race_date:
        for session in normalized_sessions:
            if session["name"].lower() == "carrera":
                race_date = session["date"]
                break

    if not race_date:
        race_date = to_utc_iso(
            first_nonempty(
                event.get("date_start"),
                event.get("date_end"),
            )
        )

    return {
        "id": (
            f"moto-{event_id or slugify(name)}"
        ),
        "round": str(
            event.get("sequence") or ""
        ),
        "name": name,
        "circuit": first_nonempty(
            circuit.get("name"),
            circuit.get("place"),
        ),
        "country": first_nonempty(
            country.get("name"),
            circuit.get("nation"),
        ),
        "race": race_date,
        "sessions": [
            {
                "name": item["name"],
                "date": item["date"],
            }
            for item in normalized_sessions
        ],
    }


def update_motogp(data: dict, errors: list) -> None:
    previous = data.get("moto") or {}

    try:
        season = get_motogp_season()
        season_id = season["id"]

        category = get_motogp_category(
            season_id
        )
        category_id = category["id"]

        events = fetch_json(
            f"{MOTOGP_BASE}/results/events"
            f"?seasonUuid={quote_plus(str(season_id))}"
        )

        if not isinstance(events, list):
            raise RuntimeError(
                "La API MotoGP no devolvió una lista de eventos"
            )

        events = unique_by_id(events)

        races = []

        for event in events:
            if event.get("test") is True:
                continue

            race = normalize_motogp_event(
                event,
                category_id,
            )

            races.append(race)

        races.sort(
            key=lambda item: item.get("race") or "9999"
        )

        # -------------------------
        # Clasificación de pilotos
        # -------------------------

        standings = fetch_json(
            f"{MOTOGP_BASE}/results/standings"
            f"?seasonUuid={quote_plus(str(season_id))}"
            f"&categoryUuid={quote_plus(str(category_id))}"
        )

        classification = (
            standings.get("classification", [])
            if isinstance(standings, dict)
            else []
        )

        drivers = []

        for item in classification:
            rider = item.get("rider") or {}
            team = item.get("team") or {}
            constructor = item.get("constructor") or {}

            drivers.append({
                "position": int(
                    item.get("position", 0) or 0
                ),
                "name": rider.get(
                    "full_name",
                    "",
                ),
                "driver": str(
                    rider.get("legacy_id")
                    or rider.get("id")
                    or ""
                ),
                "number": rider.get("number"),
                "team": team.get(
                    "name",
                    "",
                ),
                "constructor": constructor.get(
                    "name",
                    "",
                ),
                "points": float(
                    item.get("points", 0) or 0
                ),
                "country": (
                    rider.get("country") or {}
                ).get("name", ""),
                "countryIso": (
                    rider.get("country") or {}
                ).get("iso", ""),
            })

        # -------------------------
        # Equipos + imágenes
        # -------------------------

        teams_url = (
            f"{MOTOGP_BASE}/teams"
            f"?categoryUuid={quote_plus(str(category_id))}"
            f"&seasonYear={YEAR}"
        )

        team_payload = fetch_json(
            teams_url
        )

        if not isinstance(team_payload, list):
            team_payload = []

        team_map = {}
        rider_image_map = {}

        for team in team_payload:
            team_name = team.get(
                "name",
                "",
            )

            team_picture = team.get(
                "picture",
                "",
            )

            if team_name:
                team_map[team_name] = {
                    "picture": team_picture,
                    "constructor": (
                        team.get("constructor") or {}
                    ).get("name", ""),
                }

            for rider in team.get(
                "riders",
                [],
            ) or []:

                current_step = (
                    rider.get(
                        "current_career_step"
                    ) or {}
                )

                step_category = (
                    current_step.get(
                        "category"
                    ) or {}
                )

                step_season = current_step.get(
                    "season"
                )

                if (
                    step_category.get("id")
                    and step_category.get("id")
                    != category_id
                ):
                    continue

                if step_season is not None:
                    try:
                        if int(step_season) != YEAR:
                            continue
                    except (TypeError, ValueError):
                        continue

                pictures = (
                    current_step.get(
                        "pictures"
                    ) or {}
                )

                rider_key = str(
                    rider.get("legacy_id")
                    or rider.get("id")
                    or ""
                )

                rider_image_map[rider_key] = {
                    "riderImage": (
                        pictures.get("profile") or {}
                    ).get("main", ""),
                    "bikeImage": (
                        pictures.get("bike") or {}
                    ).get("main", ""),
                    "helmetImage": (
                        pictures.get("helmet") or {}
                    ).get("main", ""),
                    "teamImage": team_picture,
                }

        for driver in drivers:
            image_info = rider_image_map.get(
                str(driver.get("driver", "")),
                {},
            )

            driver.update({
                "riderImage": image_info.get(
                    "riderImage",
                    "",
                ),
                "bikeImage": image_info.get(
                    "bikeImage",
                    "",
                ),
                "helmetImage": image_info.get(
                    "helmetImage",
                    "",
                ),
                "teamImage": image_info.get(
                    "teamImage",
                    "",
                ),
            })

        # -------------------------
        # Campeonato de equipos
        # -------------------------

        team_points = {}

        for driver in drivers:
            team_name = (
                driver.get("team")
                or "Equipo desconocido"
            )

            team_points.setdefault(
                team_name,
                {
                    "name": team_name,
                    "team": team_name,
                    "points": 0.0,
                    "image": "",
                    "constructor": driver.get(
                        "constructor",
                        "",
                    ),
                },
            )

            team_points[team_name]["points"] += float(
                driver.get("points", 0) or 0
            )

            info = team_map.get(
                team_name
            )

            if info and info.get("picture"):
                team_points[team_name][
                    "image"
                ] = info["picture"]

        teams = sorted(
            team_points.values(),
            key=lambda item: item["points"],
            reverse=True,
        )

        for position, team in enumerate(
            teams,
            start=1,
        ):
            team["position"] = position

        data["moto"] = {
            "races": races,
            "drivers": drivers,
            "teams": teams,
        }

        print(
            f"[OK] MotoGP: {len(races)} eventos, "
            f"{len(drivers)} pilotos, "
            f"{len(teams)} equipos"
        )

    except Exception as exc:
        errors.append(
            f"MotoGP: {exc}"
        )

        data["moto"] = previous

        print(
            f"[ERROR] MotoGP: {exc}"
        )


# ============================================================
# IMÁGENES DE CIRCUITO
# ============================================================

def find_wikimedia_image(query: str) -> str:
    url = (
        "https://commons.wikimedia.org/w/api.php"
        "?action=query"
        "&generator=search"
        "&gsrnamespace=6"
        "&gsrlimit=10"
        "&prop=imageinfo"
        "&iiprop=url"
        "&iiurlwidth=1800"
        "&format=json"
        "&origin=*"
        "&gsrsearch="
        + quote_plus(query)
    )

    payload = fetch_json(url)

    pages = list(
        (payload.get("query") or {})
        .get("pages", {})
        .values()
    )

    if not pages:
        return ""

    keywords = [
        word.lower()
        for word in re.findall(
            r"[A-Za-zÀ-ÿ0-9]+",
            query,
        )
        if len(word) >= 4
    ]

    def score(page):
        title = str(
            page.get(
                "title",
                "",
            )
        ).lower()

        value = 0

        for word in keywords:
            if word in title:
                value += 1

        if "circuit" in title:
            value += 2

        if "race" in title:
            value += 1

        if "grand prix" in title:
            value += 1

        return value

    pages.sort(
        key=score,
        reverse=True,
    )

    for page in pages:
        imageinfo = page.get(
            "imageinfo"
        ) or []

        if not imageinfo:
            continue

        info = imageinfo[0]

        image = first_nonempty(
            info.get("thumburl"),
            info.get("url"),
        )

        if image:
            return normalize_url(
                image
            )

    return ""


def add_next_circuit_image(
    data: dict,
    sport: str,
) -> None:

    sport_data = data.get(
        sport
    ) or {}

    races = (
        sport_data.get("races")
        or sport_data.get("events")
        or []
    )

    if not races:
        return

    now = datetime.now(
        timezone.utc
    )

    candidates = []

    for race in races:
        race_date = parse_iso(
            race.get("race", "")
        )

        if race_date is None:
            candidates.append(
                (
                    datetime.max.replace(
                        tzinfo=timezone.utc
                    ),
                    race,
                )
            )
            continue

        if race_date.tzinfo is None:
            race_date = race_date.replace(
                tzinfo=timezone.utc
            )

        if race_date >= now:
            candidates.append(
                (
                    race_date,
                    race,
                )
            )

    if not candidates:
        candidates = [
            (
                parse_iso(
                    race.get(
                        "race",
                        "",
                    )
                )
                or datetime.max.replace(
                    tzinfo=timezone.utc
                ),
                race,
            )
            for race in races
        ]

    candidates.sort(
        key=lambda item: item[0]
    )

    race = candidates[0][1]

    existing_image = first_nonempty(
        race.get("circuitImage"),
        race.get("circuit_image"),
        race.get("image"),
    )

    if existing_image:
        race["circuitImage"] = (
            existing_image
        )
        return

    circuit = first_nonempty(
        race.get("circuit"),
        race.get("circuitName"),
    )

    name = first_nonempty(
        race.get("name"),
        race.get("grandPrix"),
    )

    country = race.get(
        "country",
        "",
    )

    if not circuit and not name:
        return

    query = (
        f"{circuit} {name} {country} "
        f"{'MotoGP' if sport == 'moto' else 'Formula 1'} "
        f"circuit"
    )

    try:
        image = find_wikimedia_image(
            query
        )

        if image:
            race["circuitImage"] = image

            print(
                f"[OK] Imagen circuito {sport}: "
                f"{circuit or name}"
            )
        else:
            print(
                f"[WARN] No se encontró imagen para "
                f"{circuit or name}"
            )

    except Exception as exc:
        print(
            f"[WARN] Imagen de circuito {sport}: "
            f"{exc}"
        )


# ============================================================
# RSS - MOTORSPORT.COM EN ESPAÑOL
# ============================================================

def rss_image_from_item(item) -> str:
    candidates = []

    for element in item.iter():
        name = local_name(
            element.tag
        )

        if name in {
            "content",
            "thumbnail",
            "enclosure",
            "image",
        }:
            for attr in (
                "url",
                "href",
                "src",
                "resource",
            ):
                value = element.attrib.get(
                    attr
                )

                if value:
                    candidates.append(
                        value
                    )

    html_fields = []

    for element in item.iter():
        name = local_name(
            element.tag
        )

        if name in {
            "description",
            "encoded",
            "summary",
        }:
            if element.text:
                html_fields.append(
                    element.text
                )

    combined_html = "\n".join(
        html_fields
    )

    for match in re.finditer(
        r'<img[^>]+(?:src|data-src|data-original)=["\']([^"\']+)["\']',
        combined_html,
        flags=re.IGNORECASE,
    ):
        candidates.append(
            match.group(1)
        )

    for candidate in candidates:
        candidate = normalize_url(
            candidate
        )

        if not candidate:
            continue

        lowered = candidate.lower()

        if any(
            extension in lowered
            for extension in (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".avif",
            )
        ):
            return candidate

        if (
            "image" in lowered
            or "img" in lowered
        ):
            return candidate

    return ""


def rss_child_text(
    item,
    names,
):
    names = {
        name.lower()
        for name in names
    }

    for child in item:
        if local_name(
            child.tag
        ) in names:

            return clean_html_text(
                "".join(
                    child.itertext()
                )
            )

    return ""


def rss_link(item) -> str:
    for child in item:
        if local_name(
            child.tag
        ) != "link":
            continue

        href = child.attrib.get(
            "href"
        )

        if href:
            return normalize_url(
                href
            )

        if child.text:
            return normalize_url(
                child.text
            )

    return ""


def parse_rss_feed(
    xml_text: str,
    sport: str,
):
    root = ET.fromstring(
        xml_text
    )

    items = []

    for element in root.iter():

        if local_name(
            element.tag
        ) not in {
            "item",
            "entry",
        }:
            continue

        title = rss_child_text(
            element,
            {"title"},
        )

        if not title:
            continue

        link = rss_link(
            element
        )

        if not link:
            for child in element:
                if (
                    local_name(
                        child.tag
                    ) == "guid"
                    and child.text
                ):
                    link = normalize_url(
                        child.text
                    )
                    break

        published_raw = rss_child_text(
            element,
            {
                "pubdate",
                "published",
                "updated",
                "date",
            },
        )

        source = rss_child_text(
            element,
            {"source"},
        ) or "Motorsport.com"

        image = rss_image_from_item(
            element
        )

        items.append({
            "title": title,
            "url": link,
            "published": parse_date_any(
                published_raw
            ),
            "source": source,
            "image": image,
            "sport": sport,
            "language": "es",
        })

    result = []
    seen = set()

    for item in items:
        key = (
            item["url"]
            or item["title"]
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(
            item
        )

    result.sort(
        key=lambda item:
            item.get("published")
            or "",
        reverse=True,
    )

    return result[:15]


def update_news(
    data: dict,
    errors: list,
) -> None:

    previous = data.get(
        "news"
    ) or {
        "f1": [],
        "moto": [],
    }

    news = {
        "f1": previous.get(
            "f1",
            [],
        ),
        "moto": previous.get(
            "moto",
            [],
        ),
    }

    for sport, feed_url in NEWS_FEEDS.items():

        try:
            xml_text = fetch_text(
                feed_url
            )

            parsed = parse_rss_feed(
                xml_text,
                sport,
            )

            if parsed:
                news[sport] = parsed

            print(
                f"[OK] Noticias {sport}: "
                f"{len(parsed)}"
            )

        except Exception as exc:
            errors.append(
                f"Noticias {sport}: {exc}"
            )

            print(
                f"[ERROR] Noticias {sport}: "
                f"{exc}"
            )

    data["news"] = news


# ============================================================
# MAIN
# ============================================================

def main():
    data = load_existing()

    errors = []

    data["year"] = YEAR

    update_f1(
        data,
        errors,
    )

    update_motogp(
        data,
        errors,
    )

    # Sólo buscamos la imagen del próximo GP de cada categoría.
    add_next_circuit_image(
        data,
        "f1",
    )

    add_next_circuit_image(
        data,
        "moto",
    )

    update_news(
        data,
        errors,
    )

    data["updatedAt"] = now_iso()
    data["errors"] = errors

    save_data(data)

    print(
        f"[OK] current.json actualizado: "
        f"{DATA_FILE}"
    )

    if errors:
        print(
            "[WARN] Errores detectados:"
        )

        for error in errors:
            print(
                " -",
                error,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
