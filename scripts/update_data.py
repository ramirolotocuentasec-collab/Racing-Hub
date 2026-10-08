from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


# ============================================================
# CONFIGURACIÓN
# ============================================================

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


# ============================================================
# IMÁGENES
# ============================================================
#
# Son imágenes generales del deporte. No dependemos de que cada
# noticia tenga una fotografía propia.
#
# Wikimedia Commons permite utilizar imágenes mediante sus URLs.
#

F1_IMAGE = (
    "https://commons.wikimedia.org/wiki/Special:FilePath/"
    + quote("Lewis Hamilton Ferrari F1 Car (55383746481).jpg")
    + "?width=1280"
)

MOTOGP_IMAGE = (
    "https://commons.wikimedia.org/wiki/Special:FilePath/"
    + quote("MotoGP 2026 season launch Kuala Lumpur 01.jpg")
    + "?width=1280"
)


# ============================================================
# UTILIDADES HTTP
# ============================================================

def fetch_bytes(url: str, headers: dict | None = None) -> bytes:
    final_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    if headers:
        final_headers.update(headers)

    last_error = None

    for attempt in range(RETRIES):
        try:
            request = Request(url, headers=final_headers)

            with urlopen(request, timeout=TIMEOUT) as response:
                return response.read()

        except Exception as exc:
            last_error = exc

            if attempt < RETRIES - 1:
                time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"No se pudo descargar {url}: {last_error}")


def fetch_json(url: str, headers: dict | None = None) -> dict | list:
    raw = fetch_bytes(
        url,
        headers={
            "Accept": "application/json, text/plain, */*",
            **(headers or {}),
        },
    )

    return json.loads(raw.decode("utf-8-sig"))


def fetch_text(url: str, headers: dict | None = None) -> str:
    raw = fetch_bytes(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            **(headers or {}),
        },
    )

    return raw.decode("utf-8", errors="replace")


# ============================================================
# UTILIDADES GENERALES
# ============================================================

def load_existing_data() -> dict:
    if not DATA_FILE.exists():
        return {}

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_data(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary = DATA_FILE.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    temporary.replace(DATA_FILE)


def clean_text(value) -> str:
    if value is None:
        return ""

    text = unescape(str(value))

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def first_value(obj, *keys, default=None):
    if not isinstance(obj, dict):
        return default

    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]

    return default


def safe_number(value, default=0):
    try:
        if value is None or value == "":
            return default

        return float(value)

    except Exception:
        return default


def parse_datetime(value: str | None) -> str:
    if not value:
        return ""

    value = str(value).strip()

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    except Exception:
        pass

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    except Exception:
        return value


# ============================================================
# FÓRMULA 1 - JOLPICA
# ============================================================

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"


def build_f1_session(name: str, session_data: dict) -> dict | None:
    if not isinstance(session_data, dict):
        return None

    date = session_data.get("date")
    time_value = session_data.get("time")

    if not date:
        return None

    if time_value:
        iso = f"{date}T{time_value}"
    else:
        iso = date

    return {
        "name": name,
        "date": parse_datetime(iso),
    }


def get_f1_schedule(year: int) -> list:
    url = f"{JOLPICA_BASE}/{year}.json?limit=100"

    data = fetch_json(url)

    races = (
        data.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    result = []

    for race in races:
        race_name = race.get("raceName", "")
        round_number = race.get("round", "")

        circuit = race.get("Circuit", {})
        circuit_name = circuit.get("circuitName", "")

        date = race.get("date")
        race_time = race.get("time")

        if not date:
            continue

        if race_time:
            race_datetime = f"{date}T{race_time}"
        else:
            race_datetime = date

        sessions = []

        session_map = [
            ("FP1", "FirstPractice"),
            ("FP2", "SecondPractice"),
            ("FP3", "ThirdPractice"),
            ("Sprint", "Sprint"),
            ("Q", "Qualifying"),
        ]

        for display_name, source_name in session_map:
            session = build_f1_session(
                display_name,
                race.get(source_name),
            )

            if session:
                sessions.append(session)

        sessions.append({
            "name": "Race",
            "date": parse_datetime(race_datetime),
        })

        result.append({
            "id": f"f1-{year}-{round_number}",
            "round": str(round_number),
            "name": race_name,
            "circuit": circuit_name,
            "race": parse_datetime(race_datetime),
            "sessions": sessions,
        })

    return result


def get_f1_driver_standings(year: int) -> list:
    url = (
        f"{JOLPICA_BASE}/{year}/driverstandings.json"
        "?limit=100"
    )

    data = fetch_json(url)

    lists = (
        data.get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not lists:
        return []

    standings = lists[0].get("DriverStandings", [])

    result = []

    for row in standings:
        driver = row.get("Driver", {})
        constructors = row.get("Constructors", [])

        team = ""

        if constructors:
            team = constructors[0].get("name", "")

        given = driver.get("givenName", "")
        family = driver.get("familyName", "")

        full_name = f"{given} {family}".strip()

        result.append({
            "position": int(row.get("position", 0) or 0),
            "name": full_name,
            "driver": driver.get("code", ""),
            "number": driver.get("permanentNumber", ""),
            "team": team,
            "points": safe_number(row.get("points")),
        })

    return result


def get_f1_team_standings(year: int) -> list:
    url = (
        f"{JOLPICA_BASE}/{year}/constructorstandings.json"
        "?limit=100"
    )

    data = fetch_json(url)

    lists = (
        data.get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not lists:
        return []

    standings = lists[0].get("ConstructorStandings", [])

    result = []

    for row in standings:
        constructor = row.get("Constructor", {})

        result.append({
            "position": int(row.get("position", 0) or 0),
            "name": constructor.get("name", ""),
            "team": constructor.get("name", ""),
            "points": safe_number(row.get("points")),
        })

    return result


def get_f1_data(previous: dict) -> dict:
    previous_f1 = previous.get("f1", {})

    result = {
        "races": previous_f1.get("races", []),
        "drivers": previous_f1.get("drivers", []),
        "teams": previous_f1.get("teams", []),
        "image": F1_IMAGE,
    }

    result["races"] = get_f1_schedule(YEAR)
    result["drivers"] = get_f1_driver_standings(YEAR)
    result["teams"] = get_f1_team_standings(YEAR)

    return result


# ============================================================
# MOTOGP - PULSELIVE
# ============================================================

MOTOGP_BASE = "https://api.motogp.pulselive.com/motogp/v1"

MOTOGP_HEADERS = {
    "Origin": "https://www.motogp.com",
    "Referer": "https://www.motogp.com/",
    "Accept": "application/json, text/plain, */*",
}


def find_list_recursive(obj):
    if isinstance(obj, list):
        if obj:
            return obj

        return None

    if isinstance(obj, dict):
        for value in obj.values():
            found = find_list_recursive(value)

            if found:
                return found

    return None


def find_key_recursive(obj, keys: set):
    if isinstance(obj, dict):

        for key, value in obj.items():

            if key.lower() in {x.lower() for x in keys}:
                return value

            found = find_key_recursive(value, keys)

            if found is not None:
                return found

    elif isinstance(obj, list):

        for item in obj:
            found = find_key_recursive(item, keys)

            if found is not None:
                return found

    return None


def get_motogp_season_uuid(year: int) -> str:
    url = f"{MOTOGP_BASE}/results/seasons"

    data = fetch_json(url, MOTOGP_HEADERS)

    seasons = find_list_recursive(data) or []

    for season in seasons:
        if not isinstance(season, dict):
            continue

        season_year = first_value(
            season,
            "year",
            "seasonYear",
        )

        uuid = first_value(
            season,
            "id",
            "uuid",
            "seasonUuid",
        )

        if str(season_year) == str(year) and uuid:
            return str(uuid)

    raise RuntimeError(
        f"No se encontró la temporada MotoGP {year}"
    )


def get_motogp_category_uuid() -> str:
    url = f"{MOTOGP_BASE}/results/categories"

    data = fetch_json(url, MOTOGP_HEADERS)

    categories = find_list_recursive(data) or []

    for category in categories:
        if not isinstance(category, dict):
            continue

        name = clean_text(
            first_value(
                category,
                "name",
                "displayName",
                "categoryName",
                default="",
            )
        ).lower()

        uuid = first_value(
            category,
            "id",
            "uuid",
            "categoryUuid",
        )

        if uuid and (
            name == "motogp"
            or "motogp" in name
        ):
            return str(uuid)

    # UUID conocido/fallback habitual de MotoGP.
    for category in categories:
        if not isinstance(category, dict):
            continue

        uuid = first_value(
            category,
            "id",
            "uuid",
            "categoryUuid",
        )

        if uuid:
            return str(uuid)

    raise RuntimeError(
        "No se encontró la categoría MotoGP"
    )


def extract_name(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""

    name = first_value(
        obj,
        "name",
        "displayName",
        "eventName",
        "circuitName",
        "shortName",
    )

    if isinstance(name, dict):
        name = first_value(
            name,
            "name",
            "displayName",
            "shortName",
        )

    return clean_text(name)


def extract_datetime_from_object(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""

    value = first_value(
        obj,
        "date",
        "startDate",
        "dateStart",
        "eventDate",
        "scheduledStart",
        "startTime",
        "localDate",
    )

    if isinstance(value, dict):
        value = first_value(
            value,
            "date",
            "value",
        )

    return parse_datetime(value)


def normalize_motogp_event(event: dict, index: int) -> dict | None:
    if not isinstance(event, dict):
        return None

    nested_event = event.get("event")

    if isinstance(nested_event, dict):
        source = nested_event
    else:
        source = event

    event_name = extract_name(source)

    if not event_name:
        event_name = extract_name(event)

    event_id = first_value(
        source,
        "id",
        "uuid",
        "eventUuid",
        "eventId",
        default=f"motogp-{YEAR}-{index}",
    )

    round_number = first_value(
        source,
        "round",
        "roundNumber",
        "sequence",
        "order",
        default=index + 1,
    )

    circuit_obj = source.get("circuit")

    if not isinstance(circuit_obj, dict):
        circuit_obj = {}

    circuit_name = extract_name(circuit_obj)

    if not circuit_name:
        circuit_name = clean_text(
            first_value(
                source,
                "circuitName",
                "trackName",
                "venueName",
                default="",
            )
        )

    sessions = []

    possible_sessions = []

    for key in (
        "sessions",
        "session",
        "eventSessions",
        "races",
    ):
        value = source.get(key)

        if isinstance(value, list):
            possible_sessions.extend(value)

    if isinstance(event.get("sessions"), list):
        possible_sessions.extend(event["sessions"])

    for session in possible_sessions:
        if not isinstance(session, dict):
            continue

        session_name = clean_text(
            first_value(
                session,
                "name",
                "displayName",
                "sessionName",
                "type",
                default="",
            )
        )

        session_date = extract_datetime_from_object(session)

        if not session_date:
            continue

        sessions.append({
            "name": session_name or "Sesión",
            "date": session_date,
        })

    # Intentamos identificar específicamente la carrera.
    race_date = ""

    for session in sessions:
        session_name = session["name"].lower()

        if (
            "motogp" in session_name
            or "race" in session_name
            or "carrera" in session_name
            or session_name == "gp"
        ):
            race_date = session["date"]

    if not race_date:
        race_date = extract_datetime_from_object(source)

    if not event_name:
        return None

    return {
        "id": str(event_id),
        "round": str(round_number),
        "name": event_name,
        "circuit": circuit_name,
        "race": race_date,
        "sessions": sessions,
    }


def get_motogp_schedule(year: int) -> list:
    season_uuid = get_motogp_season_uuid(year)

    urls = [
        (
            f"{MOTOGP_BASE}/results/events"
            f"?seasonUuid={season_uuid}&isFinished=false"
        ),
        (
            f"{MOTOGP_BASE}/results/events"
            f"?seasonUuid={season_uuid}&isFinished=true"
        ),
        (
            f"{MOTOGP_BASE}/events"
            f"?seasonYear={year}"
        ),
    ]

    all_events = []

    for url in urls:
        try:
            data = fetch_json(url, MOTOGP_HEADERS)

            found = find_list_recursive(data)

            if found:
                all_events.extend(found)

        except Exception:
            continue

    result = []
    seen = set()

    for index, event in enumerate(all_events):
        normalized = normalize_motogp_event(
            event,
            index,
        )

        if not normalized:
            continue

        key = (
            normalized["name"].lower(),
            normalized["circuit"].lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(normalized)

    result.sort(
        key=lambda item: (
            safe_number(item.get("round"), 9999),
            item.get("name", ""),
        )
    )

    return result


def normalize_motogp_standing(row: dict, index: int) -> dict | None:
    if not isinstance(row, dict):
        return None

    rider = row.get("rider")

    if not isinstance(rider, dict):
        rider = row.get("riderData")

    if not isinstance(rider, dict):
        rider = {}

    participant = row.get("participant")

    if not isinstance(participant, dict):
        participant = {}

    name = clean_text(
        first_value(
            rider,
            "fullName",
            "name",
            "displayName",
            default="",
        )
    )

    if not name:
        first = first_value(
            rider,
            "firstName",
            "givenName",
            default="",
        )

        last = first_value(
            rider,
            "lastName",
            "familyName",
            default="",
        )

        name = f"{first} {last}".strip()

    if not name:
        name = clean_text(
            first_value(
                row,
                "riderName",
                "name",
                "fullName",
                default="",
            )
        )

    if not name:
        return None

    team_obj = row.get("team")

    if not isinstance(team_obj, dict):
        team_obj = participant.get("team")

    if not isinstance(team_obj, dict):
        team_obj = {}

    team = clean_text(
        first_value(
            team_obj,
            "name",
            "displayName",
            "teamName",
            default="",
        )
    )

    if not team:
        team = clean_text(
            first_value(
                row,
                "teamName",
                "team",
                default="",
            )
        )

    number = first_value(
        rider,
        "number",
        "riderNumber",
        default=first_value(row, "number"),
    )

    position = first_value(
        row,
        "position",
        "rank",
        "classification",
        default=index + 1,
    )

    points = first_value(
        row,
        "points",
        "score",
        "totalPoints",
        "championshipPoints",
        default=0,
    )

    image = first_value(
        rider,
        "image",
        "imageUrl",
        "photo",
        "photoUrl",
        "riderImage",
        default="",
    )

    return {
        "position": int(safe_number(position, index + 1)),
        "name": name,
        "driver": str(number or ""),
        "number": str(number or ""),
        "team": team,
        "points": safe_number(points),
        "riderImage": image or "",
    }


def get_motogp_standings(year: int) -> list:
    season_uuid = get_motogp_season_uuid(year)
    category_uuid = get_motogp_category_uuid()

    url = (
        f"{MOTOGP_BASE}/results/standings"
        f"?seasonUuid={season_uuid}"
        f"&categoryUuid={category_uuid}"
    )

    data = fetch_json(url, MOTOGP_HEADERS)

    rows = find_list_recursive(data) or []

    result = []

    for index, row in enumerate(rows):
        normalized = normalize_motogp_standing(
            row,
            index,
        )

        if normalized:
            result.append(normalized)

    result.sort(
        key=lambda item: (
            item.get("position", 9999)
        )
    )

    return result


def get_motogp_data(previous: dict) -> dict:
    previous_moto = previous.get("moto", {})

    result = {
        "races": previous_moto.get("races", []),
        "drivers": previous_moto.get("drivers", []),
        "teams": previous_moto.get("teams", []),
        "image": MOTOGP_IMAGE,
    }

    result["races"] = get_motogp_schedule(YEAR)
    result["drivers"] = get_motogp_standings(YEAR)

    # No fabricamos una clasificación de equipos si la API no
    # entrega una clasificación oficial compatible.
    #
    # Si ya teníamos datos válidos, los conservamos.
    if "teams" not in result:
        result["teams"] = []

    return result


# ============================================================
# NOTICIAS
# ============================================================

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"


def google_news_url(query: str) -> str:
    params = {
        "q": query,
        "hl": "es-419",
        "gl": "AR",
        "ceid": "AR:es-419",
    }

    return GOOGLE_NEWS_BASE + "?" + urlencode(params)


def parse_rss_news(xml_data: bytes, limit: int = 8) -> list:
    root = ET.fromstring(xml_data)

    result = []

    for item in root.iter():
        tag = item.tag.lower()

        if not tag.endswith("item"):
            continue

        title = ""
        link = ""
        published = ""
        source = ""

        for child in item:
            child_tag = child.tag.lower()

            if child_tag.endswith("title"):
                title = clean_text(child.text)

            elif child_tag.endswith("link"):
                link = clean_text(child.text)

                if not link:
                    link = clean_text(
                        child.attrib.get("href", "")
                    )

            elif child_tag.endswith("pubdate"):
                published = parse_datetime(
                    clean_text(child.text)
                )

            elif child_tag.endswith("source"):
                source = clean_text(child.text)

        if not title or not link:
            continue

        result.append({
            "title": title,
            "url": link,
            "published": published,
            "source": source,
        })

        if len(result) >= limit:
            break

    return result


def get_google_news(query: str, limit: int = 8) -> list:
    url = google_news_url(query)

    raw = fetch_bytes(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )

    return parse_rss_news(raw, limit)


def get_f1_news(previous: dict) -> list:
    queries = [
        'Fórmula 1 noticias site:soymotor.com',
        'Fórmula 1 noticias site:es.motorsport.com',
        'Fórmula 1 noticias site:caranddriver.com/es',
        'Fórmula 1 noticias español',
    ]

    result = []

    for query in queries:
        try:
            articles = get_google_news(
                query,
                limit=5,
            )

            result.extend(articles)

        except Exception:
            continue

        if len(result) >= 8:
            break

    return deduplicate_news(result)[:8]


def get_motogp_news(previous: dict) -> list:
    queries = [
        'MotoGP site:motogp.com/es',
        'MotoGP noticias español site:es.motorsport.com',
        'MotoGP noticias español',
    ]

    result = []

    for query in queries:
        try:
            articles = get_google_news(
                query,
                limit=5,
            )

            result.extend(articles)

        except Exception:
            continue

        if len(result) >= 8:
            break

    return deduplicate_news(result)[:8]


def deduplicate_news(items: list) -> list:
    result = []
    seen = set()

    for item in items:
        title = clean_text(
            item.get("title", "")
        )

        url = item.get("url", "")

        key = (
            re.sub(
                r"[^a-z0-9áéíóúüñ]+",
                " ",
                title.lower(),
            ).strip()
        )

        if not key or key in seen:
            continue

        seen.add(key)

        result.append({
            "title": title,
            "url": url,
            "published": item.get("published", ""),
            "source": item.get("source", ""),
        })

    return result


def add_news_images(
    articles: list,
    sport_image: str,
) -> list:
    result = []

    for article in articles:
        item = dict(article)

        # Imagen general del deporte.
        # De esta manera nunca queda una noticia sin imagen
        # aunque el feed no proporcione una fotografía.
        item["image"] = sport_image

        result.append(item)

    return result


def get_news(previous: dict) -> dict:
    previous_news = previous.get("news", {})

    f1_previous = previous_news.get("f1", [])
    moto_previous = previous_news.get("moto", [])

    f1_news = get_f1_news(previous)
    moto_news = get_motogp_news(previous)

    # Si una fuente falla y no devuelve nada, conservamos
    # las noticias anteriores.
    if not f1_news:
        f1_news = f1_previous

    if not moto_news:
        moto_news = moto_previous

    return {
        "f1": add_news_images(
            f1_news,
            F1_IMAGE,
        ),
        "moto": add_news_images(
            moto_news,
            MOTOGP_IMAGE,
        ),
    }


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    previous = load_existing_data()

    errors = []

    data = {
        "updatedAt": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),

        "year": YEAR,

        "f1": previous.get("f1", {
            "races": [],
            "drivers": [],
            "teams": [],
            "image": F1_IMAGE,
        }),

        "moto": previous.get("moto", {
            "races": [],
            "drivers": [],
            "teams": [],
            "image": MOTOGP_IMAGE,
        }),

        "news": previous.get("news", {
            "f1": [],
            "moto": [],
        }),

        "errors": [],
    }

    # --------------------------------------------------------
    # F1
    # --------------------------------------------------------

    try:
        data["f1"] = get_f1_data(previous)

        print(
            f"F1 OK: "
            f"{len(data['f1'].get('races', []))} carreras, "
            f"{len(data['f1'].get('drivers', []))} pilotos."
        )

    except Exception as exc:
        message = f"F1: {exc}"

        print(f"ERROR {message}")

        errors.append(message)

        # Conservamos la última información válida.
        data["f1"] = previous.get(
            "f1",
            {
                "races": [],
                "drivers": [],
                "teams": [],
                "image": F1_IMAGE,
            },
        )

        data["f1"]["image"] = F1_IMAGE

    # --------------------------------------------------------
    # MotoGP
    # --------------------------------------------------------

    try:
        data["moto"] = get_motogp_data(previous)

        print(
            f"MotoGP OK: "
            f"{len(data['moto'].get('races', []))} carreras, "
            f"{len(data['moto'].get('drivers', []))} pilotos."
        )

    except Exception as exc:
        message = f"MotoGP: {exc}"

        print(f"ERROR {message}")

        errors.append(message)

        data["moto"] = previous.get(
            "moto",
            {
                "races": [],
                "drivers": [],
                "teams": [],
                "image": MOTOGP_IMAGE,
            },
        )

        data["moto"]["image"] = MOTOGP_IMAGE

    # --------------------------------------------------------
    # NOTICIAS
    # --------------------------------------------------------

    try:
        data["news"] = get_news(previous)

        print(
            f"Noticias F1: "
            f"{len(data['news'].get('f1', []))}"
        )

        print(
            f"Noticias MotoGP: "
            f"{len(data['news'].get('moto', []))}"
        )

    except Exception as exc:
        message = f"Noticias: {exc}"

        print(f"ERROR {message}")

        errors.append(message)

        data["news"] = previous.get(
            "news",
            {
                "f1": [],
                "moto": [],
            },
        )

    data["errors"] = errors

    save_data(data)

    print("")
    print("========================================")
    print(" Racing Hub AR - actualización completa")
    print("========================================")
    print(f"Año: {YEAR}")
    print(f"Archivo: {DATA_FILE}")
    print(f"Errores: {len(errors)}")
    print("========================================")


if __name__ == "__main__":
    main()
