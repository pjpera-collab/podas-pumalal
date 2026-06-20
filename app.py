import streamlit as st
import yaml
import requests
from datetime import date, datetime, timedelta
from ics import Calendar, Event

LAT = -38.6525463
LON = -72.5121981

st.set_page_config(
    page_title="Podas Pumalal",
    page_icon="🌿",
    layout="centered"
)

st.title("🌿 Podas Pumalal")
st.caption("Calendario de poda según especie, fecha y riesgo de heladas")

@st.cache_data(ttl=3600)
def load_species():
    with open("species.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["species"]

@st.cache_data(ttl=3600)
def get_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum"
        "&timezone=America%2FSantiago"
        "&forecast_days=7"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()["daily"]

def parse_month_day(month_day: str, year: int):
    day, month = month_day.split("-")
    return date(year, int(month), int(day))

def upcoming_tasks(species):
    today = date.today()
    tasks = []
    for sp in species:
        for job in sp["jobs"]:
            d = parse_month_day(job["start"], today.year)
            if d < today - timedelta(days=30):
                d = parse_month_day(job["start"], today.year + 1)
            delta = (d - today).days
            if -7 <= delta <= 45:
                tasks.append({
                    "date": d,
                    "species": sp["name"],
                    "type": job["type"],
                    "instructions": job["instructions"],
                    "notes": job.get("notes", "")
                })
    return sorted(tasks, key=lambda x: x["date"])

def frost_warning(weather):
    warnings = []
    for d, tmin in zip(weather["time"][:3], weather["temperature_2m_min"][:3]):
        if tmin <= 0:
            warnings.append((d, tmin))
    return warnings

def make_ics(species):
    cal = Calendar()
    current_year = date.today().year
    for sp in species:
        for job in sp["jobs"]:
            for year in [current_year, current_year + 1]:
                d = parse_month_day(job["start"], year)
                e = Event()
                e.name = f"Poda: {sp['name']}"
                e.begin = d.isoformat()
                e.make_all_day()
                e.description = (
                    f"Tipo: {job['type']}\n"
                    f"Instrucciones: {job['instructions']}\n"
                    f"Notas: {job.get('notes','')}"
                )
                cal.events.add(e)
    return str(cal)

species = load_species()
weather = get_weather()
warnings = frost_warning(weather)

if warnings:
    st.error("⚠️ Riesgo de helada en los próximos 3 días. No hagas podas fuertes.")
    for d, t in warnings:
        st.write(f"- {d}: mínima {t} °C")
else:
    st.success("Sin heladas bajo 0 °C en los próximos 3 días.")

st.subheader("Tareas próximas")
tasks = upcoming_tasks(species)

if not tasks:
    st.info("No hay tareas relevantes en los próximos 45 días.")
else:
    for t in tasks:
        with st.container(border=True):
            st.markdown(f"### {t['date'].strftime('%d-%m')} · {t['species']}")
            st.write(f"**Tipo:** {t['type']}")
            st.write(t["instructions"])
            if t["notes"]:
                st.caption(t["notes"])

st.subheader("Clima próximos 7 días")
for d, tmin, tmax, rain in zip(
    weather["time"],
    weather["temperature_2m_min"],
    weather["temperature_2m_max"],
    weather["precipitation_sum"]
):
    st.write(f"**{d}** · mín {tmin} °C / máx {tmax} °C · lluvia {rain} mm")

st.subheader("Calendario por especie")
for sp in species:
    with st.expander(sp["name"]):
        for job in sp["jobs"]:
            st.markdown(f"**{job['start']} — {job['type']}**")
            st.write(job["instructions"])
            if job.get("notes"):
                st.caption(job["notes"])

ics_data = make_ics(species)
st.download_button(
    "Descargar calendario .ics",
    data=ics_data,
    file_name="calendario_podas_pumalal.ics",
    mime="text/calendar"
)
