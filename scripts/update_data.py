import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen


YEAR = datetime.now(timezone.utc).year

OUTPUT = "data/current.json"


def get_json(url, headers=None):

    headers = headers or {}

    request = Request(
        url,
        headers={
            "User-Agent":
                "RacingHubAR/1.0",
            **headers
        }
    )

    with urlopen(
        request,
        timeout=30
    ) as response:

        return json.loads(
            response.read().decode("utf-8")
        )


def first_value(obj, *keys):

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


# =========================================================
# F1
# =========================================================

def get_f1():

    result = {
        "races": [],
        "drivers": [],
        "teams": []
    }

    base = (
        f"https://api.jolpi.ca/"
        f"ergast/f1/{YEAR}"
    )

    try:

        schedule = get_json(
            base + ".json?limit=100"
        )

        races = (
            schedule
            .get("MRData", {})
            .get("RaceTable", {})
            .get("Races", [])
        )

        for race in races:

            race_date = race.get("date")
            race_time = race.get("time")

            if not race_date:
                continue

            if race_time:
                iso = (
                    race_date +
                    "T" +
                    race_time
                )
            else:
                iso = (
                    race_date +
                    "T00:00:00Z"
                )

            sessions = []

            session_names = [
                ("FirstPractice", "Práctica 1"),
                ("SecondPractice", "Práctica 2"),
                ("ThirdPractice", "Práctica 3"),
                ("SprintQualifying", "Clasificación Sprint"),
                ("Sprint", "Sprint"),
                ("Qualifying", "Clasificación")
            ]

            for key, name in session_names:

                session = race.get(key)

                if not session:
                    continue

                date = session.get("date")
                time = session.get("time")

                if not date:
                    continue

                session_iso = (
                    date +
                    "T" +
                    (time or "00:00:00Z")
                )

                sessions.append({
                    "name": name,
                    "date": session_iso
                })

            result["races"].append({
                "id":
                    race.get("round"),
                "round":
                    race.get("round"),
                "name":
                    race.get("raceName"),
                "circuit":
                    race.get("Circuit", {})
                        .get("circuitName"),
                "race":
                    iso,
                "sessions":
                    sessions
            })

        # -------------------------
        # PILOTOS
        # -------------------------

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
                .get("DriverStandings", [])
            )

            for item in entries:

                driver = item.get(
                    "Driver",
                    {}
                )

                name = (
                    driver.get("givenName","") +
                    " " +
                    driver.get("familyName","")
                ).strip()

                constructors = item.get(
                    "Constructors",
                    []
                )

                team = (
                    constructors[0]
                    .get("name")
                    if constructors
                    else ""
                )

                result["drivers"].append({
                    "position":
                        item.get("position"),
                    "name":
                        name,
                    "team":
                        team,
                    "points":
                        item.get("points")
                })

        # -------------------------
        # EQUIPOS
        # -------------------------

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
                        item.get("position"),
                    "name":
                        constructor.get("name"),
                    "points":
                        item.get("points")
                })

    except Exception as error:

        result["error"] = str(error)

    return result


# =========================================================
# MOTOGP
# =========================================================

MOTOGP_HEADERS = {
    "Origin":
        "https://www.motogp.com",
    "Referer":
        "https://www.motogp.com/"
}


def get_motogp():

    result = {
        "races": [],
        "drivers": [],
        "teams": []
    }

    try:

        seasons = get_json(
            "https://api.motogp.pulselive.com/"
            "motogp/v1/results/seasons",
            MOTOGP_HEADERS
        )

        season = next(
            (
                x for x in seasons
                if x.get("year") == YEAR
            ),
            None
        )

        if not season:

            raise RuntimeError(
                "No se encontró temporada MotoGP."
            )

        season_id = season["id"]

        # -------------------------------------------------
        # CATEGORÍAS
        # -------------------------------------------------

        categories = get_json(
            "https://api.motogp.pulselive.com/"
            "motogp/v1/results/categories",
            MOTOGP_HEADERS
        )

        category = next(
            (
                x for x in categories
                if str(
                    x.get("name", "")
                ).lower() == "motogp"
            ),
            None
        )

        if not category:

            raise RuntimeError(
                "No se encontró categoría MotoGP."
            )

        category_id = category["id"]

        # -------------------------------------------------
        # EVENTOS
        # -------------------------------------------------

        events_url = (
            "https://api.motogp.pulselive.com/"
            "motogp/v1/results/events"
            f"?seasonUuid={season_id}"
        )

        events = get_json(
            events_url,
            MOTOGP_HEADERS
        )

        for event in events:

            # Algunas respuestas contienen
            # objetos internos diferentes.
            # Buscamos de forma tolerante.

            event_id = first_value(
                event,
                "id",
                "uuid"
            )

            name = first_value(
                event,
                "name",
                "shortName"
            )

            if not name:

                competition = event.get(
                    "competition",
                    {}
                )

                name = first_value(
                    competition,
                    "name",
                    "shortName"
                )

            start = first_value(
                event,
                "startDate",
                "dateFrom",
                "start"
            )

            end = first_value(
                event,
                "endDate",
                "dateTo",
                "end"
            )

            circuit = first_value(
                event,
                "circuit",
                "circuitName",
                "venue"
            )

            # Si no encontramos fecha,
            # no inventamos nada.

            if not start:
                continue

            result["races"].append({
                "id":
                    event_id,
                "name":
                    name or "Gran Premio MotoGP",
                "circuit":
                    circuit or "",
                "race":
                    start,
                "end":
                    end,
                "sessions":
                    []
            })

        # -------------------------------------------------
        # STANDINGS
        # -------------------------------------------------

        standings_url = (
            "https://api.motogp.pulselive.com/"
            "motogp/v1/results/standings"
            f"?seasonUuid={season_id}"
            f"&categoryUuid={category_id}"
        )

        standings = get_json(
            standings_url,
            MOTOGP_HEADERS
        )

        if isinstance(
            standings,
            dict
        ):

            rows = (
                standings.get("content")
                or standings.get("results")
                or standings.get("standings")
                or []
            )

        elif isinstance(
            standings,
            list
        ):

            rows = standings

        else:

            rows = []

        for index, item in enumerate(rows):

            rider = (
                item.get("rider")
                or item.get("riderFullName")
                or item.get("competitor")
                or {}
            )

            if isinstance(
                rider,
                dict
            ):

                name = (
                    first_value(
                        rider,
                        "fullName",
                        "name"
                    )
                    or ""
                )

            else:

                name = str(rider)

            result["drivers"].append({
                "position":
                    first_value(
                        item,
                        "position",
                        "rank"
                    )
                    or index + 1,
                "name":
                    name,
                "team":
                    first_value(
                        item,
                        "team",
                        "constructor"
                    )
                    or "",
                "points":
                    first_value(
                        item,
                        "points",
                        "totalPoints"
                    )
                    or 0
            })

    except Exception as error:

        result["error"] = str(error)

    return result


# =========================================================
# MAIN
# =========================================================

def main():

    os.makedirs(
        "data",
        exist_ok=True
    )

    f1 = get_f1()
    moto = get_motogp()

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
                "MotoGP / PulseLive"

        },

        "f1":
            f1,

        "moto":
            moto,

        "errors": []

    }

    if f1.get("error"):

        output["errors"].append({
            "sport": "f1",
            "message": f1["error"]
        })

    if moto.get("error"):

        output["errors"].append({
            "sport": "moto",
            "message": moto["error"]
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

    print(
        "Racing Hub actualizado:"
    )

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    main()
