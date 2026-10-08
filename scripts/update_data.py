#!/usr/bin/env python3

"""
Racing Hub AR
Actualizador automático de datos F1 + MotoGP.

Genera:
    data/current.json

Fuentes:
    F1     -> Jolpica F1 API
    MotoGP -> MotoGP PulseLive API
    News   -> Google News RSS filtrado a fuentes oficiales

El script está diseñado para NO destruir los datos anteriores
si una API falla temporalmente.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from pathlib import Path


# =========================================================
# CONFIGURACIÓN
# =========================================================

YEAR = datetime.now(timezone.utc).year

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "current.json"

ARGENTINA_TZ = "America/Argentina/Buenos_Aires"


F1_BASE = "https://api.jolpi.ca/ergast/f1"

MOTOGP_BASE = "https://api.motogp.pulselive.com/motogp/v1"


MOTOGP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.motogp.com",
    "Referer": "https://www.motogp.com/",
}


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


# =========================================================
# UTILIDADES
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    print(f"[RACING HUB] {message}")


def fetch_json(url, headers=None, timeout=30):
    request = urllib.request.Request(
        url,
        headers=headers or DEFAULT_HEADERS,
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:

        raw = response.read()

        if not raw:
            raise RuntimeError("Respuesta vacía")

        return json.loads(
            raw.decode("utf-8")
        )


def fetch_text(url, headers=None, timeout=30):
    request = urllib.request.Request(
        url,
        headers=headers or DEFAULT_HEADERS,
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


def safe_float(value, default=0):
    try:
        if value is None:
            return default

        return float(value)

    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default

        return int(float(value))

    except Exception:
        return default


def first_value(obj, *keys, default=None):
    if not isinstance(obj, dict):
        return default

    for key in keys:
        if key in obj:

            value = obj[key]

            if value is not None and value != "":
                return value

    return default


def recursive_find(obj, keys):
    """
    Busca recursivamente una clave dentro de un JSON.
    """

    wanted = {
        str(k).lower()
        for k in keys
    }

    if isinstance(obj, dict):

        for key, value in obj.items():

            if str(key).lower() in wanted:
                return value

            found = recursive_find(
                value,
                keys
            )

            if found is not None:
                return found

    elif isinstance(obj, list):

        for item in obj:

            found = recursive_find(
                item,
                keys
            )

            if found is not None:
                return found

    return None


def as_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, dict):

        for key in (
            "content",
            "items",
            "data",
            "results",
            "events",
            "standings",
            "rows",
        ):

            if isinstance(
                value.get(key),
                list
            ):
                return value[key]

    return []


def parse_iso_date(value):
    """
    Convierte diferentes formatos de fecha
    a ISO UTC.
    """

    if value is None:
        return None

    if isinstance(value, (int, float)):

        try:

            # Milisegundos
            if value > 100000000000:

                dt = datetime.fromtimestamp(
                    value / 1000,
                    tz=timezone.utc
                )

            else:

                dt = datetime.fromtimestamp(
                    value,
                    tz=timezone.utc
                )

            return dt.isoformat()

        except Exception:
            return None

    text = str(value).strip()

    if not text:
        return None

    # ISO directo
    try:

        normalized = text.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(
            normalized
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        ).isoformat()

    except Exception:
        pass

    # Timestamp numérico dentro de string
    try:

        number = float(text)

        return parse_iso_date(number)

    except Exception:
        pass

    return None


def clean_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value)
    ).strip()


def make_id(*parts):
    raw = "-".join(
        clean_text(p)
        for p in parts
        if p is not None
    )

    raw = raw.lower()

    raw = re.sub(
        r"[^a-z0-9\-]+",
        "-",
        raw
    )

    raw = re.sub(
        r"-+",
        "-",
        raw
    )

    return raw.strip("-")


# =========================================================
# ARCHIVO ANTERIOR
# =========================================================

def load_previous_data():

    if not DATA_FILE.exists():
        return {}

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(data, dict):
                return data

    except Exception as error:

        log(
            "No se pudo leer current.json anterior: "
            + str(error)
        )

    return {}


# =========================================================
# F1 - CALENDARIO
# =========================================================

def fetch_f1_races():

    url = (
        f"{F1_BASE}/"
        f"{YEAR}.json"
        f"?limit=100"
    )

    data = fetch_json(url)

    races = (
        data
        .get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    normalized = []

    for race in races:

        race_name = first_value(
            race,
            "raceName",
            "name",
            default="Gran Premio"
        )

        round_number = first_value(
            race,
            "round",
            default=""
        )

        circuit = (
            race
            .get("Circuit", {})
        )

        circuit_name = first_value(
            circuit,
            "circuitName",
            "name",
            default=""
        )

        race_date = race.get("date")
        race_time = race.get("time")

        race_datetime = None

        if race_date:

            if race_time:

                race_datetime = (
                    f"{race_date}T{race_time}"
                )

            else:

                race_datetime = (
                    f"{race_date}T00:00:00Z"
                )

        race_datetime = parse_iso_date(
            race_datetime
        )

        sessions = []

        # -------------------------------------------------
        # Sesiones estándar F1
        # -------------------------------------------------

        session_fields = [
            ("FirstPractice", "FP1"),
            ("SecondPractice", "FP2"),
            ("ThirdPractice", "FP3"),
            ("Sprint", "Sprint"),
            ("Qualifying", "Clasificación"),
        ]

        for field, label in session_fields:

            session = race.get(field)

            if not isinstance(
                session,
                dict
            ):
                continue

            date = session.get("date")
            time = session.get("time")

            if not date:
                continue

            if time:
                value = (
                    f"{date}T{time}"
                )
            else:
                value = (
                    f"{date}T00:00:00Z"
                )

            iso = parse_iso_date(
                value
            )

            if iso:

                sessions.append({
                    "name": label,
                    "date": iso
                })

        # -------------------------------------------------
        # Carrera
        # -------------------------------------------------

        if race_datetime:

            sessions.append({
                "name": "Carrera",
                "date": race_datetime
            })

        circuit_url = ""

        if isinstance(
            circuit,
            dict
        ):

            circuit_url = first_value(
                circuit,
                "url",
                default=""
            )

        normalized.append({

            "id": make_id(
                "f1",
                YEAR,
                round_number,
                race_name
            ),

            "round": round_number,

            "name": race_name,

            "circuit": circuit_name,

            "race": race_datetime,

            "sessions": sessions,

            "circuitUrl": circuit_url,

            "circuitImage": ""

        })

    return normalized


# =========================================================
# F1 - PILOTOS
# =========================================================

def fetch_f1_drivers():

    url = (
        f"{F1_BASE}/"
        f"{YEAR}/driverstandings.json"
        f"?limit=100"
    )

    data = fetch_json(url)

    lists = (
        data
        .get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not lists:
        return []

    standings = (
        lists[0]
        .get("DriverStandings", [])
    )

    result = []

    for item in standings:

        driver = item.get(
            "Driver",
            {}
        )

        constructor_list = item.get(
            "Constructors",
            []
        )

        constructor = ""

        if constructor_list:

            constructor = first_value(
                constructor_list[0],
                "name",
                default=""
            )

        given = first_value(
            driver,
            "givenName",
            default=""
        )

        family = first_value(
            driver,
            "familyName",
            default=""
        )

        name = clean_text(
            f"{given} {family}"
        )

        result.append({

            "position": safe_int(
                item.get("position")
            ),

            "name": name,

            "driver": name,

            "team": constructor,

            "constructor": constructor,

            "points": safe_float(
                item.get("points")
            ),

            "number": first_value(
                driver,
                "permanentNumber",
                default=""
            ),

            "teamLogo": "",

            "teamColor": ""

        })

    return result


# =========================================================
# F1 - EQUIPOS
# =========================================================

def fetch_f1_teams():

    url = (
        f"{F1_BASE}/"
        f"{YEAR}/constructorstandings.json"
        f"?limit=100"
    )

    data = fetch_json(url)

    lists = (
        data
        .get("MRData", {})
        .get("StandingsTable", {})
        .get("StandingsLists", [])
    )

    if not lists:
        return []

    standings = (
        lists[0]
        .get("ConstructorStandings", [])
    )

    result = []

    for item in standings:

        constructor = item.get(
            "Constructor",
            {}
        )

        name = first_value(
            constructor,
            "name",
            default="Sin nombre"
        )

        result.append({

            "position": safe_int(
                item.get("position")
            ),

            "name": name,

            "team": name,

            "points": safe_float(
                item.get("points")
            ),

            "logo": "",

            "teamColor": ""

        })

    return result


# =========================================================
# MOTOGP - TEMPORADA
# =========================================================

def fetch_motogp_season():

    url = (
        f"{MOTOGP_BASE}/"
        "results/seasons"
    )

    seasons = fetch_json(
        url,
    )

    if isinstance(
        seasons,
        dict
    ):
        seasons = as_list(
            seasons
        )

    for season in seasons:

        if safe_int(
            season.get("year")
        ) == YEAR:

            return season

    raise RuntimeError(
        f"No se encontró la temporada MotoGP {YEAR}"
    )


# =========================================================
# MOTOGP - CATEGORÍA
# =========================================================

def fetch_motogp_category():

    """
    Obtiene las categorías disponibles.
    La API puede cambiar ligeramente su respuesta,
    por eso hacemos varias rutas de búsqueda.
    """

    possible_urls = [

        (
            f"{MOTOGP_BASE}/"
            "results/categories"
        ),

        (
            f"{MOTOGP_BASE}/"
            "results/categories/"
        ),

    ]

    last_error = None

    for url in possible_urls:

        try:

            data = fetch_json(
                url,
                MOTOGP_HEADERS
            )

            categories = as_list(
                data
            )

            # A veces el JSON es un objeto
            if not categories:

                categories = (
                    data
                    if isinstance(
                        data,
                        list
                    )
                    else []
                )

            for category in categories:

                if not isinstance(
                    category,
                    dict
                ):
                    continue

                name = clean_text(
                    first_value(
                        category,
                        "name",
                        "displayName",
                        "categoryName",
                        default=""
                    )
                )

                if name.lower() == "motogp":

                    category_id = first_value(
                        category,
                        "id",
                        "uuid",
                        "categoryUuid",
                        default=""
                    )

                    if category_id:

                        return {
                            "id": str(category_id),
                            "name": "MotoGP"
                        }

        except Exception as error:

            last_error = error

    if last_error:

        raise last_error

    raise RuntimeError(
        "No se encontró la categoría MotoGP"
    )


# =========================================================
# MOTOGP - EVENTOS
# =========================================================

def extract_motogp_events(
    season_uuid
):

    urls = [

        (
            f"{MOTOGP_BASE}/"
            "results/events"
            f"?seasonUuid={urllib.parse.quote(str(season_uuid))}"
            "&isFinished=false"
        ),

        (
            f"{MOTOGP_BASE}/"
            "results/events"
            f"?seasonUuid={urllib.parse.quote(str(season_uuid))}"
            "&isFinished=true"
        ),

        (
            f"{MOTOGP_BASE}/"
            "events"
            f"?seasonYear={YEAR}"
        ),

    ]

    all_events = []

    seen = set()

    for url in urls:

        try:

            data = fetch_json(
                url,
                MOTOGP_HEADERS
            )

            events = as_list(
                data
            )

            for event in events:

                if not isinstance(
                    event,
                    dict
                ):
                    continue

                event_id = first_value(
                    event,
                    "id",
                    "uuid",
                    "eventId",
                    default=""
                )

                key = str(
                    event_id
                    or
                    first_value(
                        event,
                        "name",
                        "shortName",
                        default=""
                    )
                )

                if not key:
                    continue

                if key in seen:
                    continue

                seen.add(key)

                all_events.append(
                    event
                )

        except Exception as error:

            log(
                "MotoGP eventos: "
                + str(error)
            )

    return all_events


# =========================================================
# MOTOGP - FECHA DE EVENTO
# =========================================================

def find_event_datetime(
    event
):

    # Posibles campos directos
    direct_keys = [

        "date",

        "startDate",

        "startTime",

        "eventDate",

        "eventStartDate",

        "raceDate",

        "raceStartDate",

        "utcDate",

        "utcStartDate",

    ]

    for key in direct_keys:

        value = event.get(
            key
        )

        parsed = parse_iso_date(
            value
        )

        if parsed:
            return parsed

    # Buscar recursivamente
    candidate = recursive_find(
        event,
        direct_keys
    )

    parsed = parse_iso_date(
        candidate
    )

    if parsed:
        return parsed

    return None


# =========================================================
# MOTOGP - NOMBRE / CIRCUITO
# =========================================================

def find_event_name(event):

    return clean_text(
        first_value(
            event,
            "name",
            "shortName",
            "displayName",
            "eventName",
            "title",
            default="Gran Premio MotoGP"
        )
    )


def find_event_circuit(event):

    circuit = event.get(
        "circuit"
    )

    if isinstance(
        circuit,
        dict
    ):

        value = first_value(
            circuit,
            "name",
            "shortName",
            "displayName",
            default=""
        )

        if value:
            return clean_text(value)

    return clean_text(
        first_value(
            event,
            "circuitName",
            "venueName",
            "trackName",
            "circuit",
            "venue",
            default=""
        )
    )


# =========================================================
# MOTOGP - SESIONES
# =========================================================

def extract_session_list(
    event
):

    sessions = []

    possible_lists = [

        event.get(
            "sessions"
        ),

        event.get(
            "eventSessions"
        ),

        event.get(
            "session"
        ),

        event.get(
            "schedule"
        ),

    ]

    for value in possible_lists:

        if isinstance(
            value,
            list
        ):

            sessions.extend(
                value
            )

    # También buscamos una lista anidada
    recursive = recursive_find(
        event,
        [
            "sessions",
            "eventSessions",
            "schedule"
        ]
    )

    if isinstance(
        recursive,
        list
    ):

        sessions.extend(
            recursive
        )

    return sessions


def normalize_motogp_session(
    session
):

    if not isinstance(
        session,
        dict
    ):
        return None

    name = clean_text(
        first_value(
            session,
            "name",
            "sessionName",
            "type",
            "sessionType",
            "displayName",
            default=""
        )
    )

    date_value = first_value(
        session,
        "date",
        "startDate",
        "startTime",
        "utcDate",
        "utcStartDate",
        default=None
    )

    date = parse_iso_date(
        date_value
    )

    if not name or not date:
        return None

    return {
        "name": name,
        "date": date
    }


# =========================================================
# MOTOGP - CALENDARIO NORMALIZADO
# =========================================================

def normalize_motogp_races(
    events
):

    normalized = []

    for index, event in enumerate(
        events,
        start=1
    ):

        race_datetime = (
            find_event_datetime(
                event
            )
        )

        if not race_datetime:
            continue

        name = find_event_name(
            event
        )

        circuit = find_event_circuit(
            event
        )

        event_id = first_value(
            event,
            "id",
            "uuid",
            "eventId",
            default=""
        )

        sessions = []

        for session in extract_session_list(
            event
        ):

            normalized_session = (
                normalize_motogp_session(
                    session
                )
            )

            if normalized_session:

                sessions.append(
                    normalized_session
                )

        # -------------------------------------------------
        # Si la API no entrega las sesiones,
        # intentamos crear al menos la carrera.
        # -------------------------------------------------

        race_session_exists = any(

            str(
                s.get("name", "")
            ).lower()
            in (
                "race",
                "grand prix",
                "motogp"
            )

            for s in sessions
        )

        if not race_session_exists:

            sessions.append({

                "name": "Grand Prix",

                "date": race_datetime

            })

        # Ordenar
        sessions.sort(
            key=lambda x:
                x.get("date", "")
        )

        round_number = first_value(
            event,
            "round",
            "roundNumber",
            "eventNumber",
            default=index
        )

        normalized.append({

            "id": make_id(
                "moto",
                YEAR,
                event_id or index,
                name
            ),

            "round": str(
                round_number
            ),

            "name": name,

            "circuit": circuit,

            "race": race_datetime,

            "sessions": sessions,

            "circuitImage": "",

            "eventUrl": ""

        })

    # -----------------------------------------------------
    # El endpoint puede devolver elementos duplicados.
    # -----------------------------------------------------

    unique = {}

    for race in normalized:

        key = (
            race.get("name", ""),
            race.get("race", "")
        )

        unique[key] = race

    result = list(
        unique.values()
    )

    result.sort(
        key=lambda x:
            x.get("race") or ""
    )

    # Renumeramos únicamente si no hay round válido
    for index, race in enumerate(
        result,
        start=1
    ):

        if not race.get(
            "round"
        ):

            race["round"] = str(
                index
            )

    return result


# =========================================================
# MOTOGP - STANDINGS
# =========================================================

def find_motogp_standings(
    season_uuid,
    category_uuid
):

    url = (

        f"{MOTOGP_BASE}/"
        "results/standings"

        f"?seasonUuid="
        f"{urllib.parse.quote(str(season_uuid))}"

        f"&categoryUuid="
        f"{urllib.parse.quote(str(category_uuid))}"

    )

    data = fetch_json(
        url,
        MOTOGP_HEADERS
    )

    return data


def normalize_motogp_standings(
    data
):

    # La API puede envolver la información
    # en diferentes niveles.

    raw = as_list(
        data
    )

    if not raw:

        if isinstance(
            data,
            list
        ):
            raw = data

        else:

            candidate = recursive_find(
                data,
                [
                    "standings",
                    "riders",
                    "riderStandings",
                    "content",
                    "items",
                    "rows"
                ]
            )

            raw = as_list(
                candidate
            )

    drivers = []

    teams_map = {}

    for index, item in enumerate(
        raw,
        start=1
    ):

        if not isinstance(
            item,
            dict
        ):
            continue

        rider = (
            item.get("rider")
            or
            item.get("driver")
            or
            {}
        )

        if not isinstance(
            rider,
            dict
        ):
            rider = {}

        team = (
            item.get("team")
            or
            item.get("constructor")
            or
            {}
        )

        if not isinstance(
            team,
            dict
        ):
            team = {}

        given = first_value(
            rider,
            "firstName",
            "givenName",
            default=""
        )

        family = first_value(
            rider,
            "lastName",
            "familyName",
            default=""
        )

        rider_name = clean_text(
            f"{given} {family}"
        )

        if not rider_name:

            rider_name = clean_text(
                first_value(
                    item,
                    "riderName",
                    "driverName",
                    "name",
                    "fullName",
                    default=""
                )
            )

        team_name = clean_text(
            first_value(
                team,
                "name",
                "teamName",
                "constructorName",
                default=""
            )
        )

        if not team_name:

            team_name = clean_text(
                first_value(
                    item,
                    "teamName",
                    "constructorName",
                    "team",
                    default=""
                )
            )

        position = safe_int(
            first_value(
                item,
                "position",
                "pos",
                "rank",
                default=index
            ),
            index
        )

        points = safe_float(
            first_value(
                item,
                "points",
                "score",
                "totalPoints",
                default=0
            )
        )

        number = first_value(
            rider,
            "number",
            "riderNumber",
            default=""
        )

        if not rider_name:
            continue

        drivers.append({

            "position": position,

            "name": rider_name,

            "driver": rider_name,

            "rider": rider_name,

            "team": team_name,

            "teamName": team_name,

            "points": points,

            "number": number,

            "teamLogo": "",

            "teamColor": "",

            "bikeImage": "",

            "riderImage": ""

        })

        if team_name:

            current = teams_map.get(
                team_name
            )

            if not current:

                teams_map[team_name] = {

                    "name": team_name,

                    "team": team_name,

                    "points": points

                }

            else:

                current["points"] += points

    drivers.sort(
        key=lambda x:
            (
                safe_int(
                    x.get("position"),
                    999
                )
            )
    )

    teams = []

    for team in teams_map.values():

        teams.append(team)

    teams.sort(
        key=lambda x:
            -safe_float(
                x.get("points")
            )
    )

    for index, team in enumerate(
        teams,
        start=1
    ):

        team["position"] = index

        team["logo"] = ""

        team["teamColor"] = ""

    return drivers, teams


# =========================================================
# MOTOGP - PROCESO COMPLETO
# =========================================================

def fetch_motogp():

    season = fetch_motogp_season()

    season_uuid = first_value(
        season,
        "id",
        "uuid",
        default=""
    )

    if not season_uuid:

        raise RuntimeError(
            "MotoGP: UUID de temporada no encontrado"
        )

    category = fetch_motogp_category()

    category_uuid = category["id"]

    events = extract_motogp_events(
        season_uuid
    )

    races = normalize_motogp_races(
        events
    )

    standings_raw = find_motogp_standings(
        season_uuid,
        category_uuid
    )

    drivers, teams = (
        normalize_motogp_standings(
            standings_raw
        )
    )

    return {

        "races": races,

        "drivers": drivers,

        "teams": teams

    }


# =========================================================
# NOTICIAS - GOOGLE NEWS RSS
# =========================================================

def parse_google_news_rss(
    url,
    default_source
):

    xml_text = fetch_text(
        url,
        DEFAULT_HEADERS,
        timeout=30
    )

    root = ET.fromstring(
        xml_text
    )

    results = []

    channel = root.find(
        "channel"
    )

    if channel is None:
        return results

    for item in channel.findall(
        "item"
    ):

        title = item.findtext(
            "title",
            default=""
        )

        link = item.findtext(
            "link",
            default=""
        )

        pub_date = item.findtext(
            "pubDate",
            default=""
        )

        source_element = item.find(
            "source"
        )

        source = default_source

        if source_element is not None:

            source = clean_text(
                source_element.text
                or
                default_source
            )

        title = clean_text(
            title
        )

        link = clean_text(
            link
        )

        if not title or not link:
            continue

        results.append({

            "title": title,

            "url": link,

            "published": pub_date,

            "source": source

        })

    return results[:15]


def fetch_news():

    encoded_f1 = urllib.parse.quote(
        "site:formula1.com when:7d"
    )

    encoded_moto = urllib.parse.quote(
        "site:motogp.com when:7d"
    )

    f1_url = (
        "https://news.google.com/rss/search"
        f"?q={encoded_f1}"
        "&hl=es-419"
        "&gl=AR"
        "&ceid=AR:es-419"
    )

    moto_url = (
        "https://news.google.com/rss/search"
        f"?q={encoded_moto}"
        "&hl=es-419"
        "&gl=AR"
        "&ceid=AR:es-419"
    )

    return {

        "f1": parse_google_news_rss(
            f1_url,
            "Formula 1"
        ),

        "moto": parse_google_news_rss(
            moto_url,
            "MotoGP"
        )

    }


# =========================================================
# EJECUCIÓN PRINCIPAL
# =========================================================

def main():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    previous = load_previous_data()

    # -----------------------------------------------------
    # Base
    # -----------------------------------------------------

    output = {

        "updatedAt": now_iso(),

        "year": YEAR,

        "f1":
            previous.get(
                "f1",
                {
                    "races": [],
                    "drivers": [],
                    "teams": []
                }
            ),

        "moto":
            previous.get(
                "moto",
                {
                    "races": [],
                    "drivers": [],
                    "teams": []
                }
            ),

        "news":
            previous.get(
                "news",
                {
                    "f1": [],
                    "moto": []
                }
            ),

        "errors": []

    }

    # =====================================================
    # F1
    # =====================================================

    try:

        log(
            f"Actualizando F1 {YEAR}..."
        )

        f1_races = fetch_f1_races()

        f1_drivers = fetch_f1_drivers()

        f1_teams = fetch_f1_teams()

        output["f1"] = {

            "races": f1_races,

            "drivers": f1_drivers,

            "teams": f1_teams

        }

        log(
            f"F1 OK: "
            f"{len(f1_races)} carreras, "
            f"{len(f1_drivers)} pilotos, "
            f"{len(f1_teams)} equipos"
        )

    except Exception as error:

        message = (
            "F1: "
            + str(error)
        )

        log(
            "ERROR " +
            message
        )

        output["errors"].append(
            message
        )

    # =====================================================
    # MOTOGP
    # =====================================================

    try:

        log(
            f"Actualizando MotoGP {YEAR}..."
        )

        moto = fetch_motogp()

        output["moto"] = moto

        log(
            f"MotoGP OK: "
            f"{len(moto.get('races', []))} carreras, "
            f"{len(moto.get('drivers', []))} pilotos, "
            f"{len(moto.get('teams', []))} equipos"
        )

    except Exception as error:

        message = (
            "MotoGP: "
            + str(error)
        )

        log(
            "ERROR " +
            message
        )

        output["errors"].append(
            message
        )

    # =====================================================
    # NOTICIAS
    # =====================================================

    try:

        log(
            "Actualizando noticias..."
        )

        news = fetch_news()

        output["news"] = news

        log(
            f"Noticias OK: "
            f"{len(news.get('f1', []))} F1 + "
            f"{len(news.get('moto', []))} MotoGP"
        )

    except Exception as error:

        message = (
            "Noticias: "
            + str(error)
        )

        log(
            "ERROR " +
            message
        )

        output["errors"].append(
            message
        )

    # =====================================================
    # LIMPIEZA DE ERRORES
    # =====================================================

    if not output["errors"]:

        output.pop(
            "errors",
            None
        )

    # =====================================================
    # GUARDAR
    # =====================================================

    temporary_file = (
        DATA_FILE.with_suffix(
            ".tmp"
        )
    )

    with open(
        temporary_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

        file.write("\n")

    os.replace(
        temporary_file,
        DATA_FILE
    )

    log(
        "======================================"
    )

    log(
        "current.json actualizado correctamente"
    )

    log(
        f"Archivo: {DATA_FILE}"
    )

    log(
        "======================================"
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print(
            "[RACING HUB] ERROR FATAL:",
            error
        )

        sys.exit(1)
