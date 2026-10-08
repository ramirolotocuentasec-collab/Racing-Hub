#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RacingHub AR - Actualizador de datos
-------------------------------------
Genera data/current.json para F1 y MotoGP.

Fuentes:
- F1: Jolpica / Ergast-compatible API
- MotoGP: PulseLive API
- Noticias: Motorsport.com RSS en español
- Imagen del próximo circuito: Wikimedia Commons API

No necesita paquetes externos: usa solamente la biblioteca estándar de Python.
"""

from __future__ import annotations

import html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT = DATA_DIR / "current.json"

YEAR = datetime.now(timezone.utc).year

F1_API = "https://api.jolpi.ca/ergast/f1"
MOTOGP_API = "https://api.motogp.pulselive.com/motogp/v1"
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"

RSS_F1 = "https://espanol.motorsport.com/rss/f1/news/"
RSS_MOTO = "https://espanol.motorsport.com/rss/category/moto/news/"

USER_AGENT = (
    "RacingHubAR/1.0 (+https://github.com/) "
    "Python urllib"
)

# GitHub Actions normalmente ya tiene certificados válidos.
SSL_CONTEXT = ssl.create_default_context()


# ============================================================
# HTTP
# ============================================================

def http_get(url: str, timeout: int = 25, headers: dict | None = None):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/xml, text/xml, */*",
    }
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers,
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout,
        context=SSL_CONTEXT,
    ) as response:
        return response.read()


def get_json(url: str, timeout: int = 25, headers: dict | None = None):
    raw = http_get(url, timeout, headers)
    return json.loads(raw.decode("utf-8-sig"))


def get_text(url: str, timeout: int = 25, headers: dict | None = None):
    return http_get(url, timeout, headers).decode("utf-8", "replace")


# ============================================================
# UTILIDADES
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def first_value(obj, *keys, default=""):
    if not isinstance(obj, dict):
        return default
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return default


def iso_utc(date_value, time_value=None):
    if not date_value:
        return None

    value = str(date_value).strip()

    if time_value:
        value = f"{value}T{str(time_value).strip()}"

    if value.endswith("Z"):
        return value

    # Date-only values become midnight UTC.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value + "T00:00:00Z"

    # Normalize +00:00 / offsets to ISO string accepted by JS.
    if value.endswith("+00:00"):
        return value[:-6] + "Z"

    return value


def parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_future(value):
    dt = parse_dt(value)
    return bool(dt and dt >= datetime.now(timezone.utc))


def sort_by_date(items, key="date"):
    return sorted(
        items,
        key=lambda x: parse_dt(x.get(key)) or datetime.max.replace(tzinfo=timezone.utc),
    )


# ============================================================
# F1 / JOLPICA
# ============================================================

def f1_race_sessions(race):
    sessions = []

    mapping = [
        ("FirstPractice", "FP1"),
        ("SecondPractice", "FP2"),
        ("ThirdPractice", "FP3"),
        ("SprintQualifying", "Sprint Qualifying"),
        ("Sprint", "Sprint"),
        ("Qualifying", "Q"),
    ]

    for source_key, label in mapping:
        item = race.get(source_key)
        if not isinstance(item, dict):
            continue

        date = iso_utc(
            item.get("date"),
            item.get("time"),
        )

        if date:
            sessions.append({
                "name": label,
                "date": date,
            })

    race_date = iso_utc(
        race.get("date"),
        race.get("time"),
    )

    if race_date:
        sessions.append({
            "name": "Race",
            "date": race_date,
        })

    return sort_by_date(sessions)


def update_f1(previous=None):
    base = f"{F1_API}/{YEAR}"

    schedule = get_json(f"{base}.json")
    races_raw = (
        schedule.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [])
    )

    races = []

    for race in races_raw:
        circuit = race.get("Circuit", {}) or {}
        location = circuit.get("Location", {}) or {}

        race_date = iso_utc(
            race.get("date"),
            race.get("time"),
        )

        races.append({
            "id": (
                f"f1-{YEAR}-"
                f"{race.get('round', '')}-"
                f"{circuit.get('circuitId', '')}"
            ),
            "round": str(race.get("round", "")),
            "name": clean_text(race.get("raceName", "")),
            "circuit": clean_text(circuit.get("circuitName", "")),
            "country": clean_text(location.get("country", "")),
            "locality": clean_text(location.get("locality", "")),
            "race": race_date,
            "officialUrl": race.get("url", ""),
            "circuitUrl": circuit.get("url", ""),
            "circuitId": circuit.get("circuitId", ""),
            "sessions": f1_race_sessions(race),
        })

    races = sort_by_date(races, "race")

    # Driver standings
    driver_rows = []
    try:
        raw = get_json(
            f"{base}/driverstandings.json?limit=100"
        )
        lists = (
            raw.get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )
        standings = lists[0].get("DriverStandings", []) if lists else []

        for row in standings:
            driver = row.get("Driver", {}) or {}
            constructors = row.get("Constructors", []) or []
            team = constructors[0].get("name", "") if constructors else ""

            driver_rows.append({
                "position": int(row.get("position", 0) or 0),
                "name": clean_text(
                    f"{driver.get('givenName', '')} "
                    f"{driver.get('familyName', '')}"
                ),
                "driver": clean_text(driver.get("code", "")),
                "team": clean_text(team),
                "points": float(row.get("points", 0) or 0),
            })
    except Exception as exc:
        print(f"[F1] No se pudieron cargar pilotos: {exc}")

    # Constructor standings
    team_rows = []
    try:
        raw = get_json(
            f"{base}/constructorstandings.json?limit=100"
        )
        lists = (
            raw.get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )
        standings = lists[0].get("ConstructorStandings", []) if lists else []

        for row in standings:
            constructor = row.get("Constructor", {}) or {}
            team_rows.append({
                "position": int(row.get("position", 0) or 0),
                "name": clean_text(constructor.get("name", "")),
                "team": clean_text(constructor.get("name", "")),
                "points": float(row.get("points", 0) or 0),
            })
    except Exception as exc:
        print(f"[F1] No se pudieron cargar constructores: {exc}")

    # Fallback: si un endpoint de standings falla, conserva el anterior.
    old = (previous or {}).get("f1", {})

    if not driver_rows and old.get("drivers"):
        driver_rows = old["drivers"]

    if not team_rows and old.get("teams"):
        team_rows = old["teams"]

    return {
        "races": races,
        "drivers": driver_rows,
        "teams": team_rows,
    }


# ============================================================
# MOTOGP / PULSELIVE
# ============================================================

def motogp_get(path, **params):
    query = urllib.parse.urlencode(params)
    url = f"{MOTOGP_API}/{path.lstrip('/')}"
    if query:
        url += "?" + query

    return get_json(
        url,
        timeout=30,
        headers={
            "Origin": "https://www.motogp.com",
            "Referer": "https://www.motogp.com/",
        },
    )


def find_current_motogp_season():
    data = motogp_get("results/seasons")

    seasons = data if isinstance(data, list) else data.get("content", [])

    current = next(
        (
            item for item in seasons
            if item.get("current") is True
        ),
        None,
    )

    if not current:
        current = next(
            (
                item for item in seasons
                if int(item.get("year", 0) or 0) == YEAR
            ),
            None,
        )

    if not current:
        raise RuntimeError("No se encontró la temporada actual de MotoGP.")

    return current["id"], int(current.get("year") or YEAR)


def motogp_categories(season_uuid):
    data = motogp_get(
        "results/categories",
        seasonUuid=season_uuid,
    )

    if isinstance(data, list):
        items = data
    else:
        items = (
            data.get("content")
            or data.get("categories")
            or data.get("results")
            or []
        )

    return items


def find_motogp_category(categories):
    for item in categories:
        name = clean_text(
            first_value(
                item,
                "name",
                "categoryName",
                default="",
            )
        ).lower()

        if name == "motogp" or "motogp" in name:
            return item

    raise RuntimeError("No se encontró la categoría MotoGP.")


def motogp_events(season_uuid):
    # Primero pedimos todos los eventos. Esto evita perder un GP
    # que esté en curso por un filtro isFinished.
    data = motogp_get(
        "results/events",
        seasonUuid=season_uuid,
    )

    if isinstance(data, list):
        return data

    return (
        data.get("content")
        or data.get("events")
        or data.get("results")
        or []
    )


def event_date_from_obj(event):
    # PulseLive ha utilizado distintos nombres según versión.
    for key in (
        "startDate",
        "date",
        "eventDate",
        "start",
    ):
        value = event.get(key)
        if value:
            return iso_utc(value)

    # Algunas respuestas contienen un objeto date.
    date_obj = event.get("date")
    if isinstance(date_obj, dict):
        return iso_utc(
            date_obj.get("start"),
            date_obj.get("time"),
        )

    return None


def event_name(event):
    return clean_text(
        first_value(
            event,
            "name",
            "shortName",
            "eventName",
            default="Gran Premio",
        )
    )


def event_circuit(event):
    circuit = event.get("circuit") or event.get("track") or {}
    if isinstance(circuit, dict):
        return clean_text(
            first_value(
                circuit,
                "name",
                "circuitName",
                "trackName",
                default="",
            )
        )

    return clean_text(circuit)


def event_country(event):
    country = event.get("country")
    if isinstance(country, dict):
        return clean_text(
            first_value(
                country,
                "name",
                "countryName",
                default="",
            )
        )
    return clean_text(country)


def motogp_sessions(event_uuid, category_uuid):
    data = motogp_get(
        "results/sessions",
        eventUuid=event_uuid,
        categoryUuid=category_uuid,
    )

    if isinstance(data, list):
        items = data
    else:
        items = (
            data.get("content")
            or data.get("sessions")
            or data.get("results")
            or []
        )

    sessions = []

    type_labels = {
        "P1": "P1",
        "P2": "P2",
        "P3": "P3",
        "PR": "PR",
        "Q1": "Q1",
        "Q2": "Q2",
        "SPR": "Sprint",
        "SPRINT": "Sprint",
        "RAC": "Race",
        "RACE": "Race",
        "WUP": "Warm Up",
        "FP": "FP",
        "FP1": "FP1",
        "FP2": "FP2",
        "FP3": "FP3",
    }

    for item in items:
        session_type = (
            item.get("type")
            or item.get("sessionType")
            or item.get("sessionCode")
            or item.get("code")
            or ""
        )

        if isinstance(session_type, dict):
            session_type = (
                session_type.get("code")
                or session_type.get("name")
                or ""
            )

        code = str(session_type).upper().strip()

        name = (
            type_labels.get(code)
            or clean_text(
                item.get("name")
                or item.get("sessionName")
                or code
            )
        )

        date = (
            item.get("startDate")
            or item.get("date")
            or item.get("start")
            or item.get("sessionStart")
        )

        if isinstance(date, dict):
            date = (
                date.get("utc")
                or date.get("iso")
                or date.get("date")
            )

        date = iso_utc(date)

        if date:
            sessions.append({
                "name": name,
                "date": date,
            })

    return sort_by_date(sessions)


def extract_picture(obj, *names):
    if not isinstance(obj, dict):
        return ""

    for name in names:
        value = obj.get(name)

        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

        if isinstance(value, dict):
            for nested in ("main", "url", "src", "href"):
                nested_value = value.get(nested)
                if isinstance(nested_value, str) and nested_value.startswith(("http://", "https://")):
                    return nested_value

    return ""


def motogp_standings(season_uuid, category_uuid):
    data = motogp_get(
        "results/standings",
        seasonUuid=season_uuid,
        categoryUuid=category_uuid,
    )

    if isinstance(data, list):
        items = data
    else:
        items = (
            data.get("content")
            or data.get("classification")
            or data.get("standings")
            or data.get("results")
            or []
        )

    # Algunas respuestas devuelven:
    # {"classification":[...]} y otras directamente una lista.
    if isinstance(items, dict):
        items = (
            items.get("classification")
            or items.get("items")
            or []
        )

    drivers = []

    for row in items:
        rider = (
            row.get("rider")
            or row.get("driver")
            or row.get("competitor")
            or {}
        )

        constructor = (
            row.get("constructor")
            or row.get("team")
            or {}
        )

        if not isinstance(rider, dict):
            rider = {}

        if not isinstance(constructor, dict):
            constructor = {}

        name = clean_text(
            first_value(
                rider,
                "fullName",
                "name",
                default="",
            )
        )

        if not name:
            name = clean_text(
                f"{rider.get('firstName', '')} "
                f"{rider.get('lastName', '')}"
            )

        team_name = clean_text(
            first_value(
                constructor,
                "name",
                "teamName",
                default="",
            )
        )

        points = (
            row.get("points")
            or row.get("totalPoints")
            or rider.get("points")
            or 0
        )

        position = (
            row.get("position")
            or row.get("rank")
            or len(drivers) + 1
        )

        drivers.append({
            "position": int(position or len(drivers) + 1),
            "name": name or f"Piloto {position}",
            "driver": clean_text(
                first_value(
                    rider,
                    "shortName",
                    "code",
                    "abbreviation",
                    default="",
                )
            ),
            "team": team_name,
            "points": float(points or 0),
            "riderImage": extract_picture(
                rider,
                "profile",
                "profileImage",
                "picture",
                "image",
            ),
            "bikeImage": extract_picture(
                constructor,
                "bike",
                "bikeImage",
                "picture",
                "image",
            ),
        })

    drivers.sort(
        key=lambda x: (
            int(x.get("position", 9999)),
            -float(x.get("points", 0)),
        )
    )

    return drivers


def motogp_teams(season_uuid, category_uuid, drivers):
    """
    Calcula el campeonato por equipos a partir de los puntos de pilotos.
    Es más estable que depender de un endpoint separado que puede variar.
    """
    totals = {}

    for rider in drivers:
        team = rider.get("team") or "Equipo no disponible"
        totals.setdefault(
            team,
            {
                "name": team,
                "team": team,
                "points": 0.0,
            },
        )
        totals[team]["points"] += float(
            rider.get("points", 0) or 0
        )

    rows = list(totals.values())

    rows.sort(
        key=lambda x: -float(x["points"])
    )

    for index, row in enumerate(rows, 1):
        row["position"] = index

    return rows


def update_motogp(previous=None):
    season_uuid, season_year = find_current_motogp_season()

    categories = motogp_categories(
        season_uuid
    )

    category = find_motogp_category(
        categories
    )

    category_uuid = (
        category.get("id")
        or category.get("uuid")
    )

    if not category_uuid:
        raise RuntimeError(
            "La categoría MotoGP no tiene UUID."
        )

    events = motogp_events(
        season_uuid
    )

    races = []

    for event in events:
        # Los test no forman parte del calendario de GPs.
        if event.get("test") is True:
            continue

        event_uuid = (
            event.get("id")
            or event.get("uuid")
            or event.get("eventUuid")
        )

        if not event_uuid:
            continue

        sessions = []

        try:
            sessions = motogp_sessions(
                event_uuid,
                category_uuid,
            )
        except Exception as exc:
            print(
                f"[MotoGP] Sesiones no disponibles para "
                f"{event_name(event)}: {exc}"
            )

        # El horario de carrera debe ser el de la sesión Race.
        race_session = next(
            (
                s for s in sessions
                if s["name"].lower() in {
                    "race",
                    "carrera",
                }
            ),
            None,
        )

        race_date = (
            race_session["date"]
            if race_session
            else event_date_from_obj(event)
        )

        if not race_date:
            # Si no tenemos fecha, no podemos mostrar el GP.
            continue

        races.append({
            "id": f"moto-{season_year}-{event_uuid}",
            "round": str(
                event.get("sequence")
                or event.get("round")
                or event.get("number")
                or ""
            ),
            "name": event_name(event),
            "circuit": event_circuit(event),
            "country": event_country(event),
            "race": race_date,
            "officialUrl": "",
            "eventUuid": event_uuid,
            "sessions": sessions,
        })

    races = sort_by_date(
        races,
        "race"
    )

    old = (previous or {}).get("moto", {})

    drivers = []
    try:
        drivers = motogp_standings(
            season_uuid,
            category_uuid,
        )
    except Exception as exc:
        print(
            f"[MotoGP] No se pudieron cargar standings: {exc}"
        )

    if not drivers and old.get("drivers"):
        drivers = old["drivers"]

    teams = motogp_teams(
        season_uuid,
        category_uuid,
        drivers,
    )

    if not teams and old.get("teams"):
        teams = old["teams"]

    return {
        "seasonUuid": season_uuid,
        "categoryUuid": category_uuid,
        "races": races,
        "drivers": drivers,
        "teams": teams,
    }


# ============================================================
# WIKIMEDIA - IMAGEN DEL PRÓXIMO CIRCUITO
# ============================================================

def wikimedia_image(query):
    params = urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "8",
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": "1600",
    })

    data = get_json(
        f"{WIKIMEDIA_API}?{params}",
        timeout=20,
        headers={
            "User-Agent": USER_AGENT,
        },
    )

    pages = (
        data.get("query", {})
        .get("pages", {})
    )

    for page in pages.values():
        title = str(page.get("title", "")).lower()

        # Evitamos logos, mapas, trazados puros y archivos pequeños.
        bad = (
            "logo",
            "map",
            "flag",
            "diagram",
            "layout",
            "track map",
        )

        if any(word in title for word in bad):
            continue

        info = page.get("imageinfo", [])
        if not info:
            continue

        item = info[0]

        return (
            item.get("thumburl")
            or item.get("url")
        )

    return ""


def add_next_circuit_image(data, sport):
    section = data.get(sport, {})
    races = section.get("races") or []

    now = datetime.now(timezone.utc)

    future = [
        race for race in races
        if parse_dt(race.get("race"))
        and parse_dt(race.get("race")) >= now
    ]

    if not future:
        return

    future.sort(
        key=lambda race: parse_dt(race["race"])
    )

    next_race = future[0]

    if next_race.get("circuitImage"):
        return

    circuit = next_race.get("circuit", "")
    country = next_race.get("country", "")

    if not circuit:
        return

    queries = [
        f"{circuit} {country} circuit",
        circuit,
    ]

    for query in queries:
        try:
            image = wikimedia_image(query)

            if image:
                next_race["circuitImage"] = image
                print(
                    f"[Imagen] {sport}: "
                    f"{circuit} -> {image}"
                )
                return

        except Exception as exc:
            print(
                f"[Imagen] Error buscando {query}: {exc}"
            )

    print(
        f"[Imagen] No encontrada para {sport}: {circuit}"
    )


# ============================================================
# RSS DE NOTICIAS
# ============================================================

def rss_image(item):
    # Media RSS
    for child in item:
        tag = child.tag.lower()

        if tag.endswith("content") or tag.endswith("thumbnail"):
            url = child.attrib.get("url")
            if url:
                return url

    # enclosure
    enclosure = item.find("enclosure")
    if enclosure is not None:
        url = enclosure.attrib.get("url")
        if url:
            return url

    # HTML de description/content: primera imagen.
    for key in ("description", "encoded"):
        text = item.findtext(key, default="")
        match = re.search(
            r'<img[^>]+src=["\']([^"\']+)["\']',
            text,
            flags=re.I,
        )
        if match:
            return html.unescape(match.group(1))

    return ""


def parse_rss(url, limit=15):
    raw = http_get(
        url,
        timeout=25,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )

    root = ET.fromstring(
        raw
    )

    items = root.findall(
        ".//item"
    )

    output = []

    for item in items[:limit * 2]:
        title = clean_text(
            item.findtext("title", default="")
        )

        link = clean_text(
            item.findtext("link", default="")
        )

        published = clean_text(
            item.findtext("pubDate", default="")
        )

        if not title or not link:
            continue

        output.append({
            "title": title,
            "url": link,
            "published": published,
            "source": "Motorsport.com",
            "language": "es",
            "image": rss_image(item),
        })

        if len(output) >= limit:
            break

    return output


def update_news(previous=None):
    old = (previous or {}).get("news", {})

    news = {
        "f1": old.get("f1", []),
        "moto": old.get("moto", []),
    }

    try:
        news["f1"] = parse_rss(
            RSS_F1,
            limit=15,
        )
    except Exception as exc:
        print(f"[News F1] {exc}")

    try:
        news["moto"] = parse_rss(
            RSS_MOTO,
            limit=15,
        )
    except Exception as exc:
        print(f"[News MotoGP] {exc}")

    return news


# ============================================================
# MAIN / FALLBACKS
# ============================================================

def load_previous():
    if not OUTPUT.exists():
        return {}

    try:
        with OUTPUT.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)
    except Exception:
        return {}


def update():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    previous = load_previous()

    data = {
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "year": YEAR,
        "f1": previous.get("f1", {
            "races": [],
            "drivers": [],
            "teams": [],
        }),
        "moto": previous.get("moto", {
            "races": [],
            "drivers": [],
            "teams": [],
        }),
        "news": previous.get("news", {
            "f1": [],
            "moto": [],
        }),
        "errors": [],
    }

    # --------------------------
    # F1
    # --------------------------
    try:
        print("[F1] Actualizando...")
        data["f1"] = update_f1(
            previous
        )
        print(
            f"[F1] {len(data['f1']['races'])} carreras, "
            f"{len(data['f1']['drivers'])} pilotos, "
            f"{len(data['f1']['teams'])} equipos."
        )
    except Exception as exc:
        message = f"F1: {type(exc).__name__}: {exc}"
        print("[ERROR]", message)
        data["errors"].append(message)

    # --------------------------
    # MotoGP
    # --------------------------
    try:
        print("[MotoGP] Actualizando...")
        data["moto"] = update_motogp(
            previous
        )
        print(
            f"[MotoGP] {len(data['moto']['races'])} carreras, "
            f"{len(data['moto']['drivers'])} pilotos, "
            f"{len(data['moto']['teams'])} equipos."
        )
    except Exception as exc:
        message = f"MotoGP: {type(exc).__name__}: {exc}"
        print("[ERROR]", message)
        data["errors"].append(message)

    # --------------------------
    # Imágenes de próximo GP
    # --------------------------
    for sport in ("f1", "moto"):
        try:
            add_next_circuit_image(
                data,
                sport,
            )
        except Exception as exc:
            message = (
                f"Imagen circuito {sport}: "
                f"{type(exc).__name__}: {exc}"
            )
            print("[ERROR]", message)
            data["errors"].append(message)

    # --------------------------
    # Noticias
    # --------------------------
    try:
        print("[Noticias] Actualizando...")
        data["news"] = update_news(
            previous
        )
    except Exception as exc:
        message = f"Noticias: {type(exc).__name__}: {exc}"
        print("[ERROR]", message)
        data["errors"].append(message)

    # Si algo quedó vacío y antes existían datos, conserva el backup.
    for sport in ("f1", "moto"):
        old_sport = previous.get(sport, {})
        new_sport = data.get(sport, {})

        for key in ("races", "drivers", "teams"):
            if not new_sport.get(key) and old_sport.get(key):
                new_sport[key] = old_sport[key]

    # Escritura atómica.
    temp = OUTPUT.with_suffix(".tmp")

    with temp.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    temp.replace(OUTPUT)

    print(
        f"[OK] JSON escrito en {OUTPUT}"
    )

    if data["errors"]:
        print(
            "[AVISO] Hubo errores, pero se conservaron "
            "los datos anteriores cuando fue posible:"
        )
        for error in data["errors"]:
            print(" -", error)


if __name__ == "__main__":
    update()
