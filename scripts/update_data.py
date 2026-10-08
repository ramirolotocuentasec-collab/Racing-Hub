import json
import os
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen


YEAR = datetime.now(timezone.utc).year

OUTPUT = "data/current.json"

MOTOGP_BASE = (
    "https://api.motogp.pulselive.com/"
    "motogp/v1"
)

MOTOGP_HEADERS = {
    "Origin": "https://www.motogp.com",
    "Referer": "https://www.motogp.com/",
    "User-Agent": "RacingHubAR/2.0"
}


# =========================================================
# HTTP
# =========================================================

def get_json(url, headers=None):

    headers = headers or {}

    request = Request(
        url,
        headers={
            "User-Agent":
                "RacingHubAR/2.0",
            **headers
        }
    )

    with urlopen(
        request,
        timeout=30
    ) as response:

        raw = response.read()

        return json.loads(
            raw.decode("utf-8")
        )


def get_text(url):

    request = Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 "
                "(compatible; RacingHubAR/2.0)"
        }
    )

    with urlopen(
        request,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8",
            errors="replace"
        )


# =========================================================
# UTILIDADES JSON
# =========================================================

def as_list(value):

    if isinstance(value, list):
        return value

    if isinstance(value, dict):

        for key in (
            "content",
            "results",
            "data",
            "items",
            "events",
            "classification"
        ):

            candidate = value.get(key)

            if isinstance(candidate, list):
                return candidate

    return []


def first(obj, *keys):

    if not isinstance(obj, dict):
        return None

    for key in keys:

        value = obj.get(key)

        if value not in (
            None,
            "",
            []
        ):

            return value

    return None


def parse_iso(value):

    if not value:
        return None

    if isinstance(value, (int, float)):

        try:

            return datetime.fromtimestamp(
                value,
                tz=timezone.utc
            )

        except Exception:
            return None

    if not isinstance(value, str):
        return None

    text = value.strip()

    if not text:
        return None

    # MotoGP puede devolver +0300
    # y datetime.fromisoformat necesita +03:00.

    if len(text) >= 5:

        tail = text[-5:]

        if (
            tail[0] in "+-"
            and tail[1:].isdigit()
        ):

            text = (
                text[:-5]
                +
                tail[:3]
                +
                ":"
                +
                tail[3:]
            )

    if text.endswith("Z"):

        text = text[:-1] + "+00:00"

    try:

        dt = datetime.fromisoformat(
            text
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt

    except Exception:

        return None


# =========================================================
# F1
# =========================================================

def get_f1():

    result = {
        "races": [],
        "drivers": [],
        "teams": [],
        "error": None
    }

    base = (
        f"https://api.jolpi.ca/"
        f"ergast/f1/{YEAR}"
    )

    try:

        schedule = get_json(
            base +
            ".json?limit=100"
        )

        races = (
            schedule
            .get("MRData", {})
            .get("RaceTable", {})
            .get("Races", [])
        )

        for race in races:

            race_date = race.get(
                "date"
            )

            race_time = race.get(
                "time"
            )

            if not race_date:
                continue

            if race_time:

                race_iso = (
                    race_date +
                    "T" +
                    race_time
                )

            else:

                race_iso = (
                    race_date +
                    "T00:00:00Z"
                )

            sessions = []

            session_names = [

                (
                    "FirstPractice",
                    "Práctica 1"
                ),

                (
                    "SecondPractice",
                    "Práctica 2"
                ),

                (
                    "ThirdPractice",
                    "Práctica 3"
                ),

                (
                    "SprintQualifying",
                    "Clasificación Sprint"
                ),

                (
                    "Sprint",
                    "Sprint"
                ),

                (
                    "Qualifying",
                    "Clasificación"
                )

            ]

            for key, label in session_names:

                session = race.get(key)

                if not isinstance(
                    session,
                    dict
                ):
                    continue

                date = session.get(
                    "date"
                )

                time = session.get(
                    "time"
                )

                if not date:
                    continue

                session_iso = (
                    date +
                    "T" +
                    (
                        time
                        or
                        "00:00:00Z"
                    )
                )

                sessions.append({

                    "name":
                        label,

                    "date":
                        session_iso

                })

            circuit = (
                race
                .get("Circuit", {})
                .get("circuitName")
            )

            result["races"].append({

                "id":
                    race.get("round"),

                "round":
                    race.get("round"),

                "name":
                    race.get("raceName"),

                "circuit":
                    circuit or "",

                "race":
                    race_iso,

                "sessions":
                    sessions

            })

        # -------------------------------------------------
        # F1 PILOTOS
        # -------------------------------------------------

        standings = get_json(
            base +
            "/driverstandings.json"
        )

        lists = (
            standings
            .get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )

        if lists:

            entries = (
                lists[0]
                .get(
                    "DriverStandings",
                    []
                )
            )

            for item in entries:

                driver = item.get(
                    "Driver",
                    {}
                )

                name = (
                    driver.get(
                        "givenName",
                        ""
                    )
                    +
                    " "
                    +
                    driver.get(
                        "familyName",
                        ""
                    )
                ).strip()

                constructors = item.get(
                    "Constructors",
                    []
                )

                team = ""

                if constructors:

                    team = constructors[0].get(
                        "name",
                        ""
                    )

                result["drivers"].append({

                    "position":
                        item.get(
                            "position"
                        ),

                    "name":
                        name,

                    "team":
                        team,

                    "points":
                        item.get(
                            "points"
                        )

                })

        # -------------------------------------------------
        # F1 EQUIPOS
        # -------------------------------------------------

        constructors = get_json(
            base +
            "/constructorstandings.json"
        )

        lists = (
            constructors
            .get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )

        if lists:

            entries = (
                lists[0]
                .get(
                    "ConstructorStandings",
                    []
                )
            )

            for item in entries:

                constructor = item.get(
                    "Constructor",
                    {}
                )

                result["teams"].append({

                    "position":
                        item.get(
                            "position"
                        ),

                    "name":
                        constructor.get(
                            "name",
                            ""
                        ),

                    "points":
                        item.get(
                            "points"
                        )

                })

    except Exception as error:

        result["error"] = str(error)

    return result


# =========================================================
# MOTOGP
# =========================================================

def get_motogp():

    result = {

        "races": [],

        "drivers": [],

        "teams": [],

        "error": None

    }

    try:

        # -------------------------------------------------
        # CATEGORÍAS DEL AÑO
        # -------------------------------------------------

        categories = get_json(
            MOTOGP_BASE +
            f"/categories?seasonYear={YEAR}",
            MOTOGP_HEADERS
        )

        categories = as_list(
            categories
        )

        motogp_category = None

        for category in categories:

            name = str(
                category.get(
                    "name",
                    ""
                )
            ).lower()

            acronym = str(
                category.get(
                    "acronym",
                    ""
                )
            ).upper()

            if (
                "motogp" in name
                or
                acronym == "MGP"
                or
                category.get("legacy_id") == 3
            ):

                motogp_category = category

                break

        if not motogp_category:

            raise RuntimeError(
                "No se encontró la categoría MotoGP."
            )

        category_id = motogp_category.get(
            "id"
        )

        # -------------------------------------------------
        # CALENDARIO REAL
        #
        # IMPORTANTE:
        # Usamos /events?seasonYear
        # y NO /results/events.
        # -------------------------------------------------

        events_url = (
            MOTOGP_BASE +
            f"/events?seasonYear={YEAR}"
        )

        raw_events = get_json(
            events_url,
            MOTOGP_HEADERS
        )

        events = as_list(
            raw_events
        )

        for event in events:

            if not isinstance(
                event,
                dict
            ):
                continue

            # Solo eventos MotoGP
            # y no tests de otras categorías.

            business_unit = event.get(
                "business_unit",
                {}
            )

            business_acronym = str(
                business_unit.get(
                    "acronym",
                    ""
                )
            ).upper()

            categories_in_event = (
                event.get(
                    "categories",
                    []
                )
                or
                event.get(
                    "event_categories",
                    []
                )
            )

            has_motogp = (
                business_acronym == "MGP"
            )

            if not has_motogp:

                for cat in categories_in_event:

                    if not isinstance(
                        cat,
                        dict
                    ):
                        continue

                    if str(
                        cat.get(
                            "acronym",
                            ""
                        )
                    ).upper() == "MGP":

                        has_motogp = True
                        break

            if not has_motogp:
                continue

            event_type = str(
                event.get(
                    "kind",
                    ""
                )
            ).upper()

            # Ignoramos tests.
            if event_type == "TEST":
                continue

            event_id = first(
                event,
                "id",
                "uuid"
            )

            name = first(
                event,
                "name",
                "url",
                "shortname"
            )

            circuit_data = event.get(
                "circuit",
                {}
            )

            if isinstance(
                circuit_data,
                dict
            ):

                circuit = first(
                    circuit_data,
                    "name",
                    "short_name"
                )

            else:

                circuit = str(
                    circuit_data
                )

            # -------------------------------------------------
            # SESIONES
            # -------------------------------------------------

            broadcasts = event.get(
                "broadcasts",
                []
            )

            sessions = []

            race_date = None

            for broadcast in broadcasts:

                if not isinstance(
                    broadcast,
                    dict
                ):
                    continue

                category = broadcast.get(
                    "category",
                    {}
                )

                if not isinstance(
                    category,
                    dict
                ):
                    category = {}

                acronym = str(
                    category.get(
                        "acronym",
                        ""
                    )
                ).upper()

                if acronym != "MGP":
                    continue

                shortname = str(
                    broadcast.get(
                        "shortname",
                        ""
                    )
                ).upper()

                session_name = (
                    broadcast.get(
                        "name"
                    )
                    or
                    shortname
                    or
                    "Sesión"
                )

                date_start = (
                    broadcast.get(
                        "date_start"
                    )
                )

                dt = parse_iso(
                    date_start
                )

                if not dt:
                    continue

                sessions.append({

                    "name":
                        session_name,

                    "shortname":
                        shortname,

                    "date":
                        dt.isoformat()

                })

                # RAC = carrera principal
                if shortname == "RAC":

                    race_date = dt

            # Si por algún cambio de API
            # RAC no aparece, usamos una sesión
            # razonable como último recurso.

            if not race_date:

                for session in sessions:

                    shortname = str(
                        session.get(
                            "shortname",
                            ""
                        )
                    ).upper()

                    if shortname in (
                        "RACE",
                        "GP"
                    ):

                        race_date = parse_iso(
                            session.get(
                                "date"
                            )
                        )

                        break

            if not race_date:
                continue

            result["races"].append({

                "id":
                    event_id,

                "round":
                    event.get(
                        "sequence"
                    ),

                "name":
                    name
                    or
                    "Gran Premio MotoGP",

                "circuit":
                    circuit
                    or
                    "",

                "race":
                    race_date.isoformat(),

                "sessions":
                    sessions

            })

        # -------------------------------------------------
        # ORDENAR Y QUITAR DUPLICADOS
        # -------------------------------------------------

        unique = {}

        for race in result["races"]:

            key = (
                race.get("id")
                or
                race.get("race")
                or
                race.get("name")
            )

            unique[str(key)] = race

        result["races"] = sorted(

            unique.values(),

            key=lambda x:
                parse_iso(
                    x["race"]
                )
                or
                datetime.max.replace(
                    tzinfo=timezone.utc
                )

        )

        # -------------------------------------------------
        # STANDINGS
        # -------------------------------------------------

        standings_url = (
            MOTOGP_BASE +
            "/results/standings"
            f"?seasonUuid="
            f"{YEAR}"
            f"&categoryUuid="
            f"{category_id}"
        )

        # Primero intentamos descubrir
        # el UUID real de temporada.

        seasons = get_json(
            MOTOGP_BASE +
            "/results/seasons",
            MOTOGP_HEADERS
        )

        seasons = as_list(
            seasons
        )

        season = next(
            (
                s for s in seasons
                if s.get("year") == YEAR
            ),
            None
        )

        if season:

            season_uuid = season.get(
                "id"
            )

            standings_url = (
                MOTOGP_BASE +
                "/results/standings"
                f"?seasonUuid="
                f"{season_uuid}"
                f"&categoryUuid="
                f"{category_id}"
            )

            standings = get_json(
                standings_url,
                MOTOGP_HEADERS
            )

            classification = []

            if isinstance(
                standings,
                dict
            ):

                classification = (
                    standings.get(
                        "classification",
                        []
                    )
                )

            for item in classification:

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                rider = item.get(
                    "rider",
                    {}
                )

                team = item.get(
                    "team",
                    {}
                )

                if not isinstance(
                    rider,
                    dict
                ):
                    rider = {}

                if not isinstance(
                    team,
                    dict
                ):
                    team = {}

                result["drivers"].append({

                    "position":
                        item.get(
                            "position"
                        ),

                    "name":
                        rider.get(
                            "full_name",
                            ""
                        ),

                    "team":
                        team.get(
                            "name",
                            ""
                        ),

                    "points":
                        item.get(
                            "points"
                        )

                })

    except Exception as error:

        result["error"] = str(error)

    return result


# =========================================================
# NOTICIAS
# =========================================================

class LinkParser(HTMLParser):

    def __init__(self):

        super().__init__()

        self.links = []

        self.current_href = None

        self.current_text = []

    def handle_starttag(
        self,
        tag,
        attrs
    ):

        if tag.lower() != "a":
            return

        attributes = dict(attrs)

        href = attributes.get(
            "href"
        )

        if href:

            self.current_href = href

            self.current_text = []

    def handle_data(self, data):

        if self.current_href:

            self.current_text.append(
                data
            )

    def handle_endtag(self, tag):

        if (
            tag.lower() == "a"
            and
            self.current_href
        ):

            title = " ".join(
                " ".join(
                    self.current_text
                ).split()
            )

            if title:

                self.links.append({

                    "title":
                        title,

                    "url":
                        self.current_href

                })

            self.current_href = None

            self.current_text = []


def get_news_page(
    url,
    path_markers
):

    try:

        html = get_text(
            url
        )

        parser = LinkParser()

        parser.feed(
            html
        )

        result = []

        seen = set()

        for item in parser.links:

            href = item["url"]

            if not any(
                marker in href
                for marker in path_markers
            ):
                continue

            full_url = urljoin(
                url,
                href
            )

            title = item["title"]

            # Evitamos enlaces de navegación
            # demasiado cortos.

            if len(title) < 20:
                continue

            key = (
                title.lower(),
                full_url
            )

            if key in seen:
                continue

            seen.add(key)

            result.append({

                "title":
                    title,

                "url":
                    full_url

            })

            if len(result) >= 15:
                break

        return result

    except Exception:

        return []


def get_news():

    f1 = get_news_page(

        "https://espanol.motorsport.com/f1/news/",

        [
            "/f1/news/"
        ]

    )

    moto = get_news_page(

        "https://www.motogp.com/es/news/latest-news",

        [
            "/es/news/"
        ]

    )

    return {

        "f1":
            f1,

        "moto":
            moto

    }


# =========================================================
# ARCHIVO ANTERIOR
# =========================================================

def load_previous():

    if not os.path.exists(
        OUTPUT
    ):

        return {}

    try:

        with open(
            OUTPUT,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

            if (
                data.get("year")
                ==
                YEAR
            ):

                return data

    except Exception:
        pass

    return {}


# =========================================================
# MAIN
# =========================================================

def main():

    os.makedirs(
        "data",
        exist_ok=True
    )

    previous = load_previous()

    print(
        "Actualizando F1..."
    )

    f1 = get_f1()

    print(
        "Actualizando MotoGP..."
    )

    moto = get_motogp()

    print(
        "Actualizando noticias..."
    )

    news = get_news()

    # -----------------------------------------------------
    # Si una fuente falla, conservamos los últimos
    # datos válidos en lugar de destruir current.json.
    # -----------------------------------------------------

    previous_f1 = previous.get(
        "f1",
        {}
    )

    previous_moto = previous.get(
        "moto",
        {}
    )

    if (
        not f1["races"]
        and
        previous_f1.get("races")
    ):

        print(
            "F1: respuesta vacía. "
            "Conservando datos anteriores."
        )

        f1 = previous_f1

    if (
        not moto["races"]
        and
        previous_moto.get("races")
    ):

        print(
            "MotoGP: respuesta vacía. "
            "Conservando datos anteriores."
        )

        moto = previous_moto

    previous_news = previous.get(
        "news",
        {}
    )

    if not news["f1"]:

        news["f1"] = (
            previous_news.get(
                "f1",
                []
            )
        )

    if not news["moto"]:

        news["moto"] = (
            previous_news.get(
                "moto",
                []
            )
        )

    output = {

        "updatedAt":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "year":
            YEAR,

        "source": {

            "f1":
                "Jolpica F1",

            "moto":
                "MotoGP / Dorna PulseLive",

            "news_f1":
                "Motorsport.com Español",

            "news_moto":
                "MotoGP oficial"

        },

        "f1":
            f1,

        "moto":
            moto,

        "news":
            news,

        "errors": []

    }

    if f1.get("error"):

        output["errors"].append({

            "source":
                "f1",

            "message":
                f1["error"]

        })

    if moto.get("error"):

        output["errors"].append({

            "source":
                "motogp",

            "message":
                moto["error"]

        })

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print(
        "================================"
    )

    print(
        "RACING HUB ACTUALIZADO"
    )

    print(
        "F1:",
        len(
            f1.get(
                "races",
                []
            )
        ),
        "carreras"
    )

    print(
        "MotoGP:",
        len(
            moto.get(
                "races",
                []
            )
        ),
        "carreras"
    )

    print(
        "Noticias F1:",
        len(
            news.get(
                "f1",
                []
            )
        )
    )

    print(
        "Noticias MotoGP:",
        len(
            news.get(
                "moto",
                []
            )
        )
    )

    print(
        "================================"
    )


if __name__ == "__main__":

    main()
