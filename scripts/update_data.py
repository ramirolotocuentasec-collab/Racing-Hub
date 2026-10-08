import json
import re
import time
import html
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from xml.etree import ElementTree as ET


# =========================================================
# CONFIGURACIÓN
# =========================================================

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_FILE = DATA_DIR / "current.json"

YEAR = datetime.now(timezone.utc).year

USER_AGENT = (
    "Mozilla/5.0 (compatible; RacingHubAR/1.0; "
    "+https://github.com/)"
)

TIMEOUT = 25
RETRIES = 3


# =========================================================
# URLS
# =========================================================

F1_BASE = "https://api.jolpi.ca/ergast/f1"

MOTOGP_BASE = (
    "https://api.motogp.pulselive.com/motogp/v1"
)

MOTOGP_SEASONS_URL = (
    MOTOGP_BASE + "/results/seasons"
)

MOTOGP_CATEGORIES_URL = (
    MOTOGP_BASE + "/results/categories"
)

MOTOGP_EVENTS_URL = (
    MOTOGP_BASE + "/events"
)

MOTOGP_RESULTS_EVENTS_URL = (
    MOTOGP_BASE + "/results/events"
)

MOTOGP_STANDINGS_URL = (
    MOTOGP_BASE + "/results/standings"
)


# =========================================================
# NOTICIAS EN ESPAÑOL
# =========================================================

NEWS_FEEDS = {
    "f1": [
        (
            "https://espanol.motorsport.com/"
            "rss/f1/news/"
        )
    ],

    "moto": [
        (
            "https://espanol.motorsport.com/"
            "rss/category/moto/news/"
        )
    ]
}


# =========================================================
# HTTP
# =========================================================

def http_get(
    url,
    headers=None,
    timeout=TIMEOUT,
    retries=RETRIES
):
    last_error = None

    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.5",
    }

    if headers:
        request_headers.update(headers)

    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers=request_headers
            )

            with urlopen(
                request,
                timeout=timeout
            ) as response:

                return response.read()

        except Exception as exc:
            last_error = exc

            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))

    raise last_error


def get_json(
    url,
    headers=None
):
    raw = http_get(
        url,
        headers=headers
    )

    return json.loads(
        raw.decode(
            "utf-8",
            errors="replace"
        )
    )


# =========================================================
# UTILIDADES GENERALES
# =========================================================

def first_value(obj, *keys):
    if not isinstance(obj, dict):
        return None

    for key in keys:
        value = obj.get(key)

        if value not in (
            None,
            "",
            [],
            {}
        ):
            return value

    return None


def as_float(value):
    try:
        return float(value)
    except Exception:
        return 0


def as_int(value):
    try:
        return int(float(value))
    except Exception:
        return 0


def text_value(value):
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, dict):
        for key in (
            "name",
            "displayName",
            "fullName",
            "value",
            "text"
        ):
            if value.get(key):
                return text_value(
                    value.get(key)
                )

    return ""


def nested_name(obj, *paths):
    if not isinstance(obj, dict):
        return ""

    for path in paths:
        current = obj

        for key in path:
            if not isinstance(current, dict):
                current = None
                break

            current = current.get(key)

        value = text_value(current)

        if value:
            return value

    return ""


def find_lists(obj):
    """
    Devuelve listas encontradas recursivamente.
    Se utiliza para APIs cuya estructura puede cambiar.
    """

    found = []

    if isinstance(obj, list):
        found.append(obj)

        for item in obj:
            found.extend(
                find_lists(item)
            )

    elif isinstance(obj, dict):
        for value in obj.values():
            found.extend(
                find_lists(value)
            )

    return found


def find_dicts(obj):
    found = []

    if isinstance(obj, dict):
        found.append(obj)

        for value in obj.values():
            found.extend(
                find_dicts(value)
            )

    elif isinstance(obj, list):
        for item in obj:
            found.extend(
                find_dicts(item)
            )

    return found


def parse_date(value):
    if not value:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc
            )
        except Exception:
            return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace(
        "Z",
        "+00:00"
    )

    try:
        return datetime.fromisoformat(
            text
        )
    except Exception:
        pass

    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                text,
                fmt
            ).replace(
                tzinfo=timezone.utc
            )
        except Exception:
            pass

    return None


def iso_utc(date):
    if not date:
        return ""

    if date.tzinfo is None:
        date = date.replace(
            tzinfo=timezone.utc
        )

    return date.astimezone(
        timezone.utc
    ).isoformat().replace(
        "+00:00",
        "Z"
    )


def normalize_url(url):
    if not url:
        return ""

    url = html.unescape(
        str(url).strip()
    )

    return url


# =========================================================
# CARGAR DATOS ANTERIORES
# =========================================================

def load_previous_data():
    if not DATA_FILE.exists():
        return {}

    try:
        with DATA_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


# =========================================================
# F1 - JOLPICA
# =========================================================

def get_f1_races():
    url = (
        f"{F1_BASE}/{YEAR}.json?"
        "limit=100"
    )

    data = get_json(url)

    races = (
        data
        .get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    result = []

    for race in races:

        race_date = race.get("date")
        race_time = race.get("time")

        if race_date:
            if race_time:
                race_datetime = (
                    f"{race_date}T{race_time}"
                )
            else:
                race_datetime = (
                    f"{race_date}T00:00:00Z"
                )
        else:
            race_datetime = ""

        sessions = []

        session_fields = [
            ("FirstPractice", "FP1"),
            ("SecondPractice", "FP2"),
            ("ThirdPractice", "FP3"),
            ("Sprint", "Sprint"),
            ("Qualifying", "Q"),
        ]

        for field, name in session_fields:

            session = race.get(field)

            if not isinstance(
                session,
                dict
            ):
                continue

            date = session.get("date")
            time_value = session.get("time")

            if not date:
                continue

            if time_value:
                session_date = (
                    f"{date}T{time_value}"
                )
            else:
                session_date = (
                    f"{date}T00:00:00Z"
                )

            sessions.append({
                "name": name,
                "date": session_date
            })

        sessions.append({
            "name": "Race",
            "date": race_datetime
        })

        circuit = race.get(
            "Circuit",
            {}
        )

        result.append({
            "id": race.get(
                "season",
                str(YEAR)
            ) + "-" + str(
                race.get("round", "")
            ),

            "round": race.get(
                "round",
                ""
            ),

            "name": race.get(
                "raceName",
                "Gran Premio"
            ),

            "circuit": circuit.get(
                "circuitName",
                ""
            ),

            "race": race_datetime,

            "sessions": sessions
        })

    return result


def get_f1_drivers():
    url = (
        f"{F1_BASE}/{YEAR}/"
        "driverstandings.json?"
        "limit=100"
    )

    data = get_json(url)

    standings = (
        data
        .get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not standings:
        return []

    rows = standings[0].get(
        "DriverStandings",
        []
    )

    result = []

    for row in rows:

        driver = row.get(
            "Driver",
            {}
        )

        constructors = row.get(
            "Constructors",
            []
        )

        team = ""

        if constructors:
            team = constructors[0].get(
                "name",
                ""
            )

        name = (
            f"{driver.get('givenName', '')} "
            f"{driver.get('familyName', '')}"
        ).strip()

        result.append({
            "position": row.get(
                "position",
                ""
            ),

            "name": name,

            "driver": name,

            "team": team,

            "points": row.get(
                "points",
                0
            ),

            "number": driver.get(
                "permanentNumber",
                ""
            )
        })

    return result


def get_f1_teams():
    url = (
        f"{F1_BASE}/{YEAR}/"
        "constructorstandings.json?"
        "limit=100"
    )

    data = get_json(url)

    standings = (
        data
        .get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not standings:
        return []

    rows = standings[0].get(
        "ConstructorStandings",
        []
    )

    result = []

    for row in rows:

        constructor = row.get(
            "Constructor",
            {}
        )

        result.append({
            "position": row.get(
                "position",
                ""
            ),

            "name": constructor.get(
                "name",
                "Equipo"
            ),

            "team": constructor.get(
                "name",
                "Equipo"
            ),

            "points": row.get(
                "points",
                0
            )
        })

    return result


def get_f1_data():
    return {
        "races": get_f1_races(),
        "drivers": get_f1_drivers(),
        "teams": get_f1_teams()
    }


# =========================================================
# MOTOGP - API PULSELIVE
# =========================================================

def motogp_headers():
    return {
        "Origin": "https://www.motogp.com",
        "Referer": "https://www.motogp.com/",
        "Accept": "application/json",
    }


def get_motogp_season_uuid():
    data = get_json(
        MOTOGP_SEASONS_URL,
        headers=motogp_headers()
    )

    candidates = []

    if isinstance(data, list):
        candidates = data

    elif isinstance(data, dict):
        candidates = (
            data.get("content")
            or data.get("seasons")
            or data.get("results")
            or []
        )

    for season in candidates:

        if not isinstance(
            season,
            dict
        ):
            continue

        year = first_value(
            season,
            "year",
            "seasonYear",
            "name"
        )

        if str(year) == str(YEAR):

            return first_value(
                season,
                "uuid",
                "id",
                "seasonUuid"
            )

    raise RuntimeError(
        f"No se encontró la temporada MotoGP {YEAR}"
    )


def get_motogp_category_uuid():
    data = get_json(
        MOTOGP_CATEGORIES_URL,
        headers=motogp_headers()
    )

    candidates = []

    if isinstance(data, list):
        candidates = data

    elif isinstance(data, dict):
        candidates = (
            data.get("content")
            or data.get("categories")
            or data.get("results")
            or []
        )

    for category in candidates:

        if not isinstance(
            category,
            dict
        ):
            continue

        name = " ".join([
            text_value(
                category.get("name")
            ),
            text_value(
                category.get("displayName")
            ),
            text_value(
                category.get("shortName")
            )
        ]).lower()

        if (
            name == "motogp"
            or "motogp" in name
        ):

            return first_value(
                category,
                "uuid",
                "id",
                "categoryUuid"
            )

    raise RuntimeError(
        "No se encontró la categoría MotoGP"
    )


def extract_event_objects(data):
    """
    Intenta encontrar objetos de eventos
    independientemente de cómo venga
    estructurada la respuesta.
    """

    candidates = []

    if isinstance(data, list):
        candidates = data

    elif isinstance(data, dict):

        for key in (
            "content",
            "events",
            "results",
            "items"
        ):
            value = data.get(key)

            if isinstance(value, list):
                candidates.extend(value)

    if not candidates:

        for item in find_lists(data):

            if not item:
                continue

            if all(
                isinstance(x, dict)
                for x in item
            ):
                candidates.extend(item)

    unique = []
    seen = set()

    for event in candidates:

        if not isinstance(
            event,
            dict
        ):
            continue

        event_id = first_value(
            event,
            "uuid",
            "id",
            "eventId"
        )

        key = str(
            event_id
            or id(event)
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(event)

    return unique


def event_name(event):
    return (
        first_value(
            event,
            "name",
            "eventName",
            "displayName",
            "shortName",
            "title"
        )
        or "Gran Premio"
    )


def event_circuit(event):
    direct = first_value(
        event,
        "circuitName",
        "trackName",
        "circuit"
    )

    if isinstance(
        direct,
        dict
    ):
        direct = text_value(
            direct
        )

    if direct:
        return str(direct)

    for key in (
        "circuit",
        "track",
        "venue",
        "location"
    ):

        value = event.get(key)

        if isinstance(
            value,
            dict
        ):

            name = first_value(
                value,
                "name",
                "displayName",
                "circuitName",
                "trackName"
            )

            if name:
                return str(name)

    return ""


def find_session_lists(event):
    result = []

    for key in (
        "sessions",
        "session",
        "eventSessions",
        "races",
        "raceSessions"
    ):

        value = event.get(key)

        if isinstance(
            value,
            list
        ):
            result.extend(value)

    return result


def session_name(session):
    return (
        first_value(
            session,
            "name",
            "sessionName",
            "displayName",
            "type"
        )
        or ""
    )


def session_date(session):
    for key in (
        "startDate",
        "dateStart",
        "scheduledStart",
        "start",
        "date",
        "localDate",
        "sessionDate"
    ):

        value = session.get(key)

        parsed = parse_date(
            value
        )

        if parsed:
            return parsed

    return None


def find_race_datetime(event):
    sessions = find_session_lists(
        event
    )

    race_candidates = []

    for session in sessions:

        if not isinstance(
            session,
            dict
        ):
            continue

        name = session_name(
            session
        ).lower()

        date = session_date(
            session
        )

        if not date:
            continue

        score = 0

        if (
            "motogp" in name
            and "race" in name
        ):
            score += 100

        if "race" in name:
            score += 80

        if "grand prix" in name:
            score += 30

        if "sprint" in name:
            score -= 50

        if (
            "qualifying" in name
            or "practice" in name
            or "warm" in name
        ):
            score -= 40

        race_candidates.append(
            (
                score,
                date
            )
        )

    if race_candidates:

        race_candidates.sort(
            key=lambda x: (
                -x[0],
                x[1]
            )
        )

        return race_candidates[0][1]

    for key in (
        "raceDate",
        "raceStart",
        "startDate",
        "dateStart",
        "date"
    ):

        parsed = parse_date(
            event.get(key)
        )

        if parsed:
            return parsed

    return None


def normalize_motogp_event(
    event,
    index
):
    name = event_name(
        event
    )

    circuit = event_circuit(
        event
    )

    race_date = find_race_datetime(
        event
    )

    if not race_date:
        return None

    event_id = first_value(
        event,
        "uuid",
        "id",
        "eventId"
    )

    round_value = first_value(
        event,
        "round",
        "roundNumber",
        "eventNumber"
    )

    if not round_value:
        round_value = index + 1

    sessions = []

    for session in find_session_lists(
        event
    ):

        if not isinstance(
            session,
            dict
        ):
            continue

        date = session_date(
            session
        )

        name_value = session_name(
            session
        )

        if date and name_value:

            sessions.append({
                "name": name_value,
                "date": iso_utc(date)
            })

    if not any(
        s["date"] == iso_utc(race_date)
        for s in sessions
    ):

        sessions.append({
            "name": "Race",
            "date": iso_utc(race_date)
        })

    return {
        "id": str(
            event_id
            or f"{YEAR}-moto-{index + 1}"
        ),

        "round": str(
            round_value
        ),

        "name": str(
            name
        ),

        "circuit": circuit,

        "race": iso_utc(
            race_date
        ),

        "sessions": sessions
    }


def get_motogp_races(
    season_uuid
):
    errors = []

    urls = [
        (
            MOTOGP_EVENTS_URL
            + "?"
            + urlencode({
                "seasonYear": YEAR
            })
        ),

        (
            MOTOGP_RESULTS_EVENTS_URL
            + "?"
            + urlencode({
                "seasonUuid": season_uuid,
                "isFinished": "false"
            })
        ),

        (
            MOTOGP_RESULTS_EVENTS_URL
            + "?"
            + urlencode({
                "seasonUuid": season_uuid,
                "isFinished": "true"
            })
        )
    ]

    all_events = []

    for url in urls:

        try:

            data = get_json(
                url,
                headers=motogp_headers()
            )

            all_events.extend(
                extract_event_objects(
                    data
                )
            )

        except Exception as exc:

            errors.append(
                str(exc)
            )

    unique = []
    seen = set()

    for event in all_events:

        key = str(
            first_value(
                event,
                "uuid",
                "id",
                "eventId"
            )
            or event_name(event)
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(event)

    races = []

    for index, event in enumerate(
        unique
    ):

        normalized = (
            normalize_motogp_event(
                event,
                index
            )
        )

        if normalized:
            races.append(
                normalized
            )

    races.sort(
        key=lambda race:
            parse_date(
                race["race"]
            )
            or datetime.max.replace(
                tzinfo=timezone.utc
            )
    )

    # Eliminamos duplicados por nombre/fecha.
    final = []
    seen_races = set()

    for race in races:

        key = (
            race["name"].lower(),
            race["race"]
        )

        if key in seen_races:
            continue

        seen_races.add(key)
        final.append(race)

    if not final:

        if errors:
            raise RuntimeError(
                "No se pudieron obtener "
                "los eventos MotoGP: "
                + " | ".join(
                    errors[:3]
                )
            )

        raise RuntimeError(
            "La API de MotoGP no devolvió carreras."
        )

    return final


# =========================================================
# MOTOGP - STANDINGS
# =========================================================

def extract_standing_rows(data):
    rows = []

    preferred_keys = (
        "standings",
        "classification",
        "riders",
        "riderStandings",
        "content",
        "results"
    )

    if isinstance(
        data,
        dict
    ):

        for key in preferred_keys:

            value = data.get(key)

            if isinstance(
                value,
                list
            ):
                rows.extend(
                    value
                )

    if not rows:

        for candidate in find_lists(
            data
        ):

            if not candidate:
                continue

            score = 0

            for item in candidate:

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                keys = {
                    str(k).lower()
                    for k in item.keys()
                }

                if (
                    "position" in keys
                    or "pos" in keys
                    or "rank" in keys
                ):
                    score += 2

                if (
                    "points" in keys
                    or "score" in keys
                    or "totalpoints" in keys
                ):
                    score += 2

                if (
                    "rider" in keys
                    or "ridername" in keys
                    or "competitor" in keys
                ):
                    score += 3

            if score >= 4:
                rows = candidate
                break

    return [
        row
        for row in rows
        if isinstance(
            row,
            dict
        )
    ]


def rider_name(row):
    rider = first_value(
        row,
        "rider",
        "riderData",
        "competitor",
        "riderInfo"
    )

    if isinstance(
        rider,
        dict
    ):

        full = first_value(
            rider,
            "fullName",
            "name",
            "displayName"
        )

        if full:
            return str(full)

        first = first_value(
            rider,
            "firstName",
            "givenName"
        )

        last = first_value(
            rider,
            "lastName",
            "familyName"
        )

        full = (
            f"{text_value(first)} "
            f"{text_value(last)}"
        ).strip()

        if full:
            return full

    direct = first_value(
        row,
        "riderName",
        "fullName",
        "name",
        "driver"
    )

    return text_value(
        direct
    )


def rider_team(row):
    for key in (
        "team",
        "teamName",
        "constructor",
        "constructorName"
    ):

        value = row.get(key)

        if isinstance(
            value,
            dict
        ):

            name = first_value(
                value,
                "name",
                "displayName"
            )

            if name:
                return str(name)

        elif value:
            return str(value)

    rider = row.get(
        "rider"
    )

    if isinstance(
        rider,
        dict
    ):

        for key in (
            "team",
            "teamName",
            "constructor"
        ):

            value = rider.get(
                key
            )

            if isinstance(
                value,
                dict
            ):

                name = first_value(
                    value,
                    "name",
                    "displayName"
                )

                if name:
                    return str(name)

            elif value:
                return str(value)

    return ""


def get_motogp_standings(
    season_uuid,
    category_uuid
):
    url = (
        MOTOGP_STANDINGS_URL
        + "?"
        + urlencode({
            "seasonUuid": season_uuid,
            "categoryUuid": category_uuid
        })
    )

    data = get_json(
        url,
        headers=motogp_headers()
    )

    rows = extract_standing_rows(
        data
    )

    result = []

    for index, row in enumerate(
        rows
    ):

        name = rider_name(
            row
        )

        if not name:
            continue

        position = first_value(
            row,
            "position",
            "pos",
            "rank"
        )

        points = first_value(
            row,
            "points",
            "score",
            "totalPoints"
        )

        rider = row.get(
            "rider"
        )

        number = first_value(
            row,
            "riderNumber",
            "number"
        )

        if isinstance(
            rider,
            dict
        ):

            number = (
                number
                or first_value(
                    rider,
                    "number",
                    "riderNumber"
                )
            )

        result.append({
            "position": (
                position
                or index + 1
            ),

            "name": name,

            "rider": name,

            "team": rider_team(
                row
            ),

            "points": (
                points
                if points is not None
                else 0
            ),

            "number": (
                number
                or ""
            ),

            "bikeImage": (
                first_value(
                    row,
                    "bikeImage",
                    "bike_image",
                    "vehicleImage",
                    "vehicle_image"
                )
                or ""
            ),

            "riderImage": (
                first_value(
                    row,
                    "riderImage",
                    "rider_image",
                    "image",
                    "photo"
                )
                or ""
            )
        })

    result.sort(
        key=lambda x:
            as_int(
                x.get(
                    "position"
                )
            )
            or 999
    )

    return result


def build_motogp_teams(drivers):
    """
    La clasificación oficial de equipos MotoGP
    puede no venir en la misma respuesta que
    la de pilotos.

    Si la API no entrega una clasificación
    específica de equipos, no inventamos una.
    """

    return []


def get_motogp_data():
    season_uuid = (
        get_motogp_season_uuid()
    )

    category_uuid = (
        get_motogp_category_uuid()
    )

    races = get_motogp_races(
        season_uuid
    )

    drivers = get_motogp_standings(
        season_uuid,
        category_uuid
    )

    teams = build_motogp_teams(
        drivers
    )

    return {
        "races": races,
        "drivers": drivers,
        "teams": teams
    }


# =========================================================
# NOTICIAS
# =========================================================

def strip_html(value):
    if not value:
        return ""

    value = html.unescape(
        str(value)
    )

    value = re.sub(
        r"<script.*?</script>",
        "",
        value,
        flags=re.I | re.S
    )

    value = re.sub(
        r"<style.*?</style>",
        "",
        value,
        flags=re.I | re.S
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def extract_image_from_html(value):
    if not value:
        return ""

    decoded = html.unescape(
        str(value)
    )

    patterns = [
        r'<img[^>]+src=["\']([^"\']+)',
        r'<img[^>]+data-src=["\']([^"\']+)',
        r'<source[^>]+src=["\']([^"\']+)'
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            decoded,
            flags=re.I
        )

        if match:
            return normalize_url(
                match.group(1)
            )

    return ""


def xml_text(element):
    if element is None:
        return ""

    return "".join(
        element.itertext()
    ).strip()


def find_child_text(
    element,
    names
):
    names = {
        name.lower()
        for name in names
    }

    for child in list(element):

        tag = child.tag

        if "}" in tag:
            tag = tag.split(
                "}",
                1
            )[1]

        if tag.lower() in names:
            return xml_text(
                child
            )

    return ""


def find_media_image(item):
    """
    Busca imágenes en:
    - media:content
    - media:thumbnail
    - enclosure
    - description/content HTML
    """

    for child in list(item):

        tag = child.tag

        if "}" in tag:
            namespace, local = tag.rsplit(
                "}",
                1
            )
        else:
            namespace = ""
            local = tag

        local = local.lower()

        if local in (
            "content",
            "thumbnail"
        ):

            url = child.attrib.get(
                "url"
            )

            if url:
                return normalize_url(
                    url
                )

        if local == "enclosure":

            url = child.attrib.get(
                "url"
            )

            media_type = (
                child.attrib.get(
                    "type",
                    ""
                )
                .lower()
            )

            if (
                url
                and (
                    media_type.startswith(
                        "image/"
                    )
                    or re.search(
                        r"\.(jpg|jpeg|png|webp)(\?|$)",
                        url,
                        re.I
                    )
                )
            ):
                return normalize_url(
                    url
                )

    for child in list(item):

        tag = child.tag

        if "}" in tag:
            tag = tag.split(
                "}",
                1
            )[1]

        if tag.lower() in (
            "description",
            "encoded",
            "content"
        ):

            image = (
                extract_image_from_html(
                    xml_text(child)
                )
            )

            if image:
                return image

    return ""


def parse_rss_feed(
    raw,
    sport
):
    root = ET.fromstring(
        raw
    )

    items = []

    for item in root.iter():

        tag = item.tag

        if "}" in tag:
            tag = tag.split(
                "}",
                1
            )[1]

        if tag.lower() not in (
            "item",
            "entry"
        ):
            continue

        title = find_child_text(
            item,
            {
                "title"
            }
        )

        link = ""

        for child in list(item):

            child_tag = child.tag

            if "}" in child_tag:
                child_tag = child_tag.split(
                    "}",
                    1
                )[1]

            if child_tag.lower() == "link":

                href = child.attrib.get(
                    "href"
                )

                if href:
                    link = href
                    break

                text = xml_text(
                    child
                )

                if text:
                    link = text
                    break

        published = (
            find_child_text(
                item,
                {
                    "pubDate",
                    "published",
                    "updated",
                    "date"
                }
            )
        )

        description = (
            find_child_text(
                item,
                {
                    "description",
                    "encoded",
                    "summary"
                }
            )
        )

        image = find_media_image(
            item
        )

        title = strip_html(
            title
        )

        if not title or not link:
            continue

        source = (
            "Motorsport.com"
        )

        published_iso = ""

        parsed = parse_date(
            published
        )

        if parsed:
            published_iso = iso_utc(
                parsed
            )

        items.append({
            "title": title,
            "url": normalize_url(
                link
            ),
            "published": published_iso,
            "source": source,
            "image": image,
            "sport": sport
        })

    return items


def get_news_for_sport(
    sport
):
    errors = []

    all_items = []

    for feed_url in NEWS_FEEDS.get(
        sport,
        []
    ):

        try:

            raw = http_get(
                feed_url,
                headers={
                    "Accept": (
                        "application/rss+xml,"
                        "application/xml,"
                        "text/xml,*/*"
                    )
                }
            )

            items = parse_rss_feed(
                raw,
                sport
            )

            all_items.extend(
                items
            )

        except Exception as exc:

            errors.append(
                f"{feed_url}: {exc}"
            )

    # Deduplicar por URL
    unique = []
    seen = set()

    for item in all_items:

        url = item.get(
            "url",
            ""
        )

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)

        unique.append(
            item
        )

    unique.sort(
        key=lambda item:
            parse_date(
                item.get(
                    "published"
                )
            )
            or datetime.min.replace(
                tzinfo=timezone.utc
            ),
        reverse=True
    )

    if not unique:

        if errors:
            raise RuntimeError(
                "No se pudieron obtener "
                "noticias en español: "
                + " | ".join(
                    errors
                )
            )

        raise RuntimeError(
            "El RSS no devolvió noticias."
        )

    return unique[:15]


def get_all_news(previous):
    news = {}

    previous_news = (
        previous.get(
            "news",
            {}
        )
        if isinstance(
            previous,
            dict
        )
        else {}
    )

    for sport in (
        "f1",
        "moto"
    ):

        try:

            news[sport] = (
                get_news_for_sport(
                    sport
                )
            )

        except Exception as exc:

            print(
                f"[NEWS {sport.upper()}] "
                f"Error: {exc}"
            )

            old = previous_news.get(
                sport,
                []
            )

            news[sport] = (
                old
                if isinstance(
                    old,
                    list
                )
                else []
            )

    return news


# =========================================================
# GUARDAR JSON
# =========================================================

def save_data(data):
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary = (
        DATA_FILE.with_suffix(
            ".tmp"
        )
    )

    with temporary.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

        file.write("\n")

    temporary.replace(
        DATA_FILE
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "========================================"
    )
    print(
        "RACING HUB AR - ACTUALIZADOR"
    )
    print(
        f"Temporada: {YEAR}"
    )
    print(
        "========================================"
    )

    previous = (
        load_previous_data()
    )

    errors = []

    data = (
        previous
        if isinstance(
            previous,
            dict
        )
        else {}
    )

    data["year"] = YEAR

    # -----------------------------------------------------
    # F1
    # -----------------------------------------------------

    try:

        print(
            "[F1] Consultando Jolpica..."
        )

        data["f1"] = (
            get_f1_data()
        )

        print(
            "[F1] OK"
        )

    except Exception as exc:

        message = (
            f"F1: {exc}"
        )

        print(
            "[F1] ERROR:",
            exc
        )

        errors.append(
            message
        )

    # -----------------------------------------------------
    # MotoGP
    # -----------------------------------------------------

    try:

        print(
            "[MotoGP] Consultando PulseLive..."
        )

        data["moto"] = (
            get_motogp_data()
        )

        print(
            "[MotoGP] OK"
        )

    except Exception as exc:

        message = (
            f"MotoGP: {exc}"
        )

        print(
            "[MotoGP] ERROR:",
            exc
        )

        errors.append(
            message
        )

    # -----------------------------------------------------
    # Noticias
    # -----------------------------------------------------

    print(
        "[NEWS] Consultando noticias en español..."
    )

    data["news"] = (
        get_all_news(
            previous
        )
    )

    # -----------------------------------------------------
    # Metadata
    # -----------------------------------------------------

    data["updatedAt"] = (
        datetime.now(
            timezone.utc
        ).isoformat().replace(
            "+00:00",
            "Z"
        )
    )

    data["errors"] = errors

    # -----------------------------------------------------
    # Guardar
    # -----------------------------------------------------

    save_data(
        data
    )

    print(
        "========================================"
    )
    print(
        "Datos guardados en:"
    )
    print(
        DATA_FILE
    )
    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
