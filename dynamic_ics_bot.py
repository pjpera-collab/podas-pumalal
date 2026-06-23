import yaml
import requests
import hashlib
from datetime import date, datetime, timedelta, time
from zoneinfo import ZoneInfo

LAT = -38.6525463
LON = -72.5121981
TZ = "America/Santiago"

HORIZON_DAYS = 60
MAX_EVENTS = 40

PRIORITY = {"alta": 0, "media": 1, "baja": 2}


def esc(txt):
    return (
        str(txt)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def parse_md(md, year):
    d, m = md.split("-")
    return date(year, int(m), int(d))


def next_occurrence(md, today):
    d = parse_md(md, today.year)
    if d < today - timedelta(days=30):
        d = parse_md(md, today.year + 1)
    return d


def get_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,precipitation_hours"
        f"&timezone={TZ}&forecast_days=7"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()["daily"]


def rain_sum(w, days=3):
    return float(sum(w["precipitation_sum"][:days]))


def first_frost(w, days=3, threshold=0):
    for d, t in zip(w["time"][:days], w["temperature_2m_min"][:days]):
        if float(t) <= float(threshold):
            return d, float(t)
    return None


def climate_decision(task, w):
    rain = rain_sum(w, 3)

    if task.get("avoid_frost", False):
        f = first_frost(w, 3, task.get("frost_limit_c", 0))
        if f:
            return "POSTERGAR", f"helada o mínima crítica: {f[1]} °C el {f[0]}"

    if task.get("avoid_rain", False) and rain >= float(task.get("rain_limit_mm_72h", 12)):
        return "POSTERGAR", f"lluvia acumulada prevista: {rain:.1f} mm en 72 h"

    if task.get("prefer_after_rain", False) and rain > 2:
        return "ESPERAR POST-LLUVIA", f"viene lluvia ({rain:.1f} mm/72 h); mejor después del frente"

    return "HACER / VENTANA APTA", "sin alerta climática relevante"


def load_kb():
    with open("species.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def active_species(kb):
    return [s for s in kb["species"] if s.get("active", False)]


def candidate_tasks(kb, today):
    rows = []

    for sp in active_species(kb):
        for task in sp.get("tasks", []):
            d = next_occurrence(task["start"], today)
            delta = (d - today).days

            if -1 <= delta <= HORIZON_DAYS:
                rows.append(
                    {
                        "date": d,
                        "species": sp["name"],
                        "latin": sp.get("latin", ""),
                        **task,
                    }
                )

    return sorted(
        rows,
        key=lambda r: (
            PRIORITY.get(r.get("priority", "media"), 1),
            r["date"],
            r["species"],
        ),
    )[:MAX_EVENTS]


def uid(task, status, today):
    raw = f"{today}|{task['date']}|{task['species']}|{task.get('category','')}|{task.get('type','')}|{status}"
    return "pumalal-" + hashlib.sha1(raw.encode()).hexdigest()[:20] + "@podas"


def add_event(lines, uid_value, start_dt, end_dt, summary, desc):
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines.extend(
        [
            "BEGIN:VEVENT",
            f"UID:{uid_value}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=America/Santiago:{start_dt.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=America/Santiago:{end_dt.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(desc)}",
            "BEGIN:VALARM",
            "TRIGGER:-PT30M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc(summary)}",
            "END:VALARM",
            "END:VEVENT",
        ]
    )


def make_ics(tasks, w, today):
    tz = ZoneInfo(TZ)
    generated = datetime.now(tz)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Podas Pumalal ICS Bot//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Podas Pumalal Dinámico",
        "X-WR-TIMEZONE:America/Santiago",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]

    desc = (
        f"Generado: {generated.strftime('%d-%m-%Y %H:%M')}\n"
        f"Lluvia 72 h: {rain_sum(w, 3):.1f} mm\n"
        f"Mínima 72 h: {min(w['temperature_2m_min'][:3])} °C\n"
        "Abrir app Podas Pumalal Pro antes de ejecutar labores."
    )

    start = datetime.combine(today, time(7, 45), tzinfo=tz)
    end = start + timedelta(minutes=15)

    add_event(
        lines,
        f"pumalal-resumen-{today.isoformat()}@podas",
        start,
        end,
        "🌿 Resumen climático Podas Pumalal",
        desc,
    )

    for task in tasks:
        status, reason = climate_decision(task, w)

        event_day = task["date"] if status.startswith("HACER") else today

        start = datetime.combine(event_day, time(8, 30), tzinfo=tz)
        end = start + timedelta(minutes=30)

        icon = "🌿" if status.startswith("HACER") else "⚠️"
        summary = f"{icon} {status}: {task.get('category','tarea')} · {task['species']}"

        desc = (
            f"Especie: {task['species']} ({task.get('latin','')})\n"
            f"Labor: {task.get('category','')} · {task.get('type','')}\n"
            f"Fecha base: {task['date'].strftime('%d-%m-%Y')}\n"
            f"Prioridad: {task.get('priority','media')}\n"
            f"Criterio climático: {status} — {reason}\n\n"
            f"Instrucciones:\n{task.get('instructions','')}\n\n"
            "Antes de ejecutar: abrir Podas Pumalal Pro y revisar clima actualizado."
        )

        if task.get("edible_warning", False):
            desc += "\n\nFRUTA COMESTIBLE: revisar etiqueta SAG y carencia antes de cosechar."

        add_event(lines, uid(task, status, today.isoformat()), start, end, summary, desc)

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    today = datetime.now(ZoneInfo(TZ)).date()
    kb = load_kb()
    w = get_weather()
    tasks = candidate_tasks(kb, today)

    with open("podas_pumalal_dinamico.ics", "w", encoding="utf-8", newline="") as f:
        f.write(make_ics(tasks, w, today))

    print(f"ICS generado con {len(tasks)} tareas dinámicas.")


if __name__ == "__main__":
    main()
