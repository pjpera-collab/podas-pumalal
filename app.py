import streamlit as st
import yaml
import requests
import pandas as pd
from datetime import date, datetime, timedelta

LAT = -38.6525463
LON = -72.5121981
TZ = "America/Santiago"

st.set_page_config(page_title="Podas Pumalal Pro", page_icon="🌿", layout="centered")

PRIORITY = {"alta": 0, "media": 1, "baja": 2}

@st.cache_data(ttl=3600)
def load_kb():
    with open("species.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

@st.cache_data(ttl=3600)
def weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&daily=temperature_2m_min,temperature_2m_max,precipitation_sum,precipitation_hours"
        f"&timezone={TZ}&forecast_days=7"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()["daily"]

def parse_md(md, year):
    d, m = md.split("-")
    return date(year, int(m), int(d))

def next_date(md):
    today = date.today()
    d = parse_md(md, today.year)
    if d < today - timedelta(days=30):
        d = parse_md(md, today.year + 1)
    return d

def rain72(w):
    return float(sum(w["precipitation_sum"][:3]))

def min72(w):
    return float(min(w["temperature_2m_min"][:3]))

def frost_event(w, threshold):
    for d, t in zip(w["time"][:3], w["temperature_2m_min"][:3]):
        if float(t) <= float(threshold):
            return d, float(t)
    return None

def climate_decision(task, w):
    r = rain72(w)
    if task.get("avoid_frost"):
        f = frost_event(w, task.get("frost_limit_c", 0))
        if f:
            return "⏸️ Postergar", f"mínima crítica {f[1]} °C el {f[0]}"
    if task.get("avoid_rain") and r >= float(task.get("rain_limit_mm_72h", 12)):
        return "⏸️ Postergar", f"lluvia acumulada {r:.1f} mm en 72 h"
    if task.get("prefer_after_rain") and r > 2:
        return "⏳ Esperar post-lluvia", f"viene lluvia ({r:.1f} mm/72 h); aplicar después del frente si corresponde"
    return "✅ Ventana apta", "sin alerta climática relevante"

def active_species(kb):
    return [s for s in kb["species"] if s.get("active")]

def library_species(kb):
    return [s for s in kb["species"] if not s.get("active")]

def upcoming(kb, horizon=90):
    today = date.today()
    rows = []
    for sp in active_species(kb):
        for task in sp.get("tasks", []):
            d = next_date(task["start"])
            delta = (d - today).days
            if -14 <= delta <= horizon:
                rows.append({"date": d, "species": sp["name"], "latin": sp.get("latin",""), "sources": sp.get("sources", []), **task})
    return sorted(rows, key=lambda x: (x["date"], PRIORITY.get(x.get("priority","media"), 1), x["species"]))

def esc(txt):
    return str(txt).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def make_ics(kb):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Podas Pumalal Pro//ES",
        "CALSCALE:GREGORIAN", "X-WR-CALNAME:Podas Pumalal Pro"
    ]
    uid = 0
    for sp in active_species(kb):
        for task in sp.get("tasks", []):
            for year in [date.today().year, date.today().year + 1]:
                d = parse_md(task["start"], year)
                uid += 1
                desc = (
                    f"{task.get('category','').upper()} · {task.get('type','')}\n"
                    f"{task.get('instructions','')}\n"
                    f"Prioridad: {task.get('priority','media')}\n"
                    f"Antes de ejecutar: abrir la app y revisar lluvia/helada.\n"
                )
                if task.get("edible_warning"):
                    desc += "Fruta comestible: revisar etiqueta SAG y carencia del producto exacto antes de consumir.\n"
                lines += [
                    "BEGIN:VEVENT",
                    f"UID:pumalal-{uid}@podas",
                    f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                    f"SUMMARY:{esc(task.get('category','Tarea').capitalize() + ': ' + sp['name'])}",
                    f"DESCRIPTION:{esc(desc)}",
                    "BEGIN:VALARM", "TRIGGER:-P3D", "ACTION:DISPLAY",
                    f"DESCRIPTION:{esc('Revisar app: ' + sp['name'])}", "END:VALARM",
                    "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
                    f"DESCRIPTION:{esc('Mañana: ' + task.get('category','tarea') + ' - ' + sp['name'])}", "END:VALARM",
                    "END:VEVENT"
                ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)

def dump_yaml(kb):
    return yaml.safe_dump(kb, allow_unicode=True, sort_keys=False, width=120)

def activate(kb, names):
    names = set(names)
    new = {"metadata": kb.get("metadata", {}), "species": []}
    for sp in kb["species"]:
        cp = dict(sp)
        if cp["name"] in names:
            cp["active"] = True
        new["species"].append(cp)
    return new

def add_manual(kb, name, latin, group, category, start, typ, instructions, priority, edible):
    new_sp = {
        "name": name, "latin": latin, "group": group, "active": True,
        "profile": "Ficha manual pendiente de validación técnica.",
        "sources": ["Pendiente: agregar fuente chilena + RHS/extensión"],
        "tasks": [{
            "start": start, "category": category, "type": typ, "instructions": instructions,
            "priority": priority, "avoid_frost": category in ["poda","siembra","trasplante/división"],
            "avoid_rain": True, "prefer_after_rain": category == "sanidad preventiva",
            "rain_limit_mm_72h": 12, "frost_limit_c": 0, "edible_warning": edible
        }]
    }
    return {"metadata": kb.get("metadata", {}), "species": kb["species"] + [new_sp]}

kb = load_kb()
w = weather()
tasks = upcoming(kb)

st.title("🌿 Podas Pumalal Pro")
st.caption("Poda · fertilización · sanidad preventiva · siembra · clima local · calendario")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Ahora", "Calendario", "Especies", "Agregar", "Registro", "Fuentes"])

with tab1:
    st.subheader("Esta semana en Pumalal")
    c1, c2 = st.columns(2)
    c1.metric("Lluvia 72 h", f"{rain72(w):.1f} mm")
    c2.metric("Mínima 72 h", f"{min72(w):.1f} °C")

    f = frost_event(w, 0)
    if f:
        st.error(f"⚠️ Riesgo de helada: {f[1]} °C el {f[0]}.")
    elif rain72(w) >= 12:
        st.warning("🌧️ Lluvia relevante próxima. Revisar podas y aplicaciones.")
    else:
        st.success("✅ Sin alerta crítica inmediata.")

    for t in tasks[:20]:
        status, reason = climate_decision(t, w)
        with st.container(border=True):
            st.markdown(f"### {t['date'].strftime('%d-%m')} · {t['species']}")
            st.write(f"**{t.get('category','').capitalize()}** · {t.get('type','')} · **Prioridad:** {t.get('priority','media')}")
            st.write(f"**Clima:** {status} — {reason}")
            st.write(t.get("instructions",""))
            if t.get("edible_warning"):
                st.warning("Fruta comestible: usar solo producto autorizado para ese cultivo; revisar etiqueta SAG y carencia antes de cosechar.")
            if t.get("notes"):
                st.caption(t["notes"])

with tab2:
    st.subheader("Calendario")
    rows = []
    for t in tasks:
        status, reason = climate_decision(t, w)
        rows.append({
            "fecha": t["date"].strftime("%d-%m-%Y"),
            "especie": t["species"],
            "módulo": t.get("category",""),
            "tipo": t.get("type",""),
            "prioridad": t.get("priority","media"),
            "clima": status,
            "razón": reason
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.download_button(
        "Descargar calendario .ics con avisos",
        data=make_ics(kb),
        file_name="podas_pumalal_pro.ics",
        mime="text/calendar"
    )
    st.caption("El calendario avisa fecha base. La app decide si conviene ejecutar o postergar por clima.")

    st.subheader("Clima próximos 7 días")
    for d, mn, mx, pr, hrs in zip(w["time"], w["temperature_2m_min"], w["temperature_2m_max"], w["precipitation_sum"], w["precipitation_hours"]):
        st.write(f"**{d}** · mín {mn} °C / máx {mx} °C · lluvia {pr} mm · horas lluvia {hrs}")

with tab3:
    st.subheader("Fichas activas")
    for sp in active_species(kb):
        with st.expander(f"{sp['name']} · {sp.get('latin','')}"):
            st.write(sp.get("profile",""))
            st.caption("Fuentes: " + " · ".join(sp.get("sources", [])))
            for task in sp.get("tasks", []):
                st.markdown(f"**{task['start']} — {task.get('category','')} — {task.get('type','')}**")
                st.write(task.get("instructions",""))
                if task.get("edible_warning"):
                    st.caption("Comestible: carencia según etiqueta SAG del producto exacto.")

with tab4:
    st.subheader("Agregar especies")
    st.write("Activa especies frecuentes en Chile ya precargadas, o agrega una especie manual.")

    lib = library_species(kb)
    names = [s["name"] for s in lib]
    selected = st.multiselect("Activar desde biblioteca", names)
    if selected:
        updated = activate(kb, selected)
        st.download_button("Descargar species.yaml actualizado", dump_yaml(updated), "species.yaml", "text/yaml")
        st.info("Reemplaza species.yaml en GitHub. Streamlit se actualiza solo.")

    st.divider()
    st.markdown("### Agregar manual")
    with st.form("manual"):
        name = st.text_input("Nombre común")
        latin = st.text_input("Nombre científico si lo sabes")
        group = st.selectbox("Grupo", ["arbusto","árbol","frutal","perenne/herbácea","bulbosa","gramínea","trepadora","semillas/flores"])
        category = st.selectbox("Primera tarea", ["poda","fertilización","sanidad preventiva","siembra","trasplante/división"])
        start = st.text_input("Fecha inicio DD-MM", "01-08")
        typ = st.text_input("Tipo", "tarea inicial")
        instructions = st.text_area("Instrucciones", "Ficha pendiente de validación técnica.")
        priority = st.selectbox("Prioridad", ["alta","media","baja"], index=1)
        edible = st.checkbox("Produce fruta/parte comestible", value=False)
        ok = st.form_submit_button("Generar YAML")

    if ok and name:
        updated = add_manual(kb, name, latin, group, category, start, typ, instructions, priority, edible)
        st.download_button("Descargar species.yaml actualizado", dump_yaml(updated), "species.yaml", "text/yaml")
        st.warning("La ficha queda pendiente de validación; no es criterio definitivo todavía.")

with tab5:
    st.subheader("Registro manual")
    if "log" not in st.session_state:
        st.session_state.log = []
    with st.form("registro"):
        d = st.date_input("Fecha", value=date.today())
        spn = st.selectbox("Especie", [s["name"] for s in active_species(kb)])
        action = st.selectbox("Acción", ["poda","fertilización","fungicida/sanidad","siembra","trasplante/división","observación"])
        product = st.text_input("Producto o nota")
        carencia = st.number_input("Carencia en días si aplica", min_value=0, max_value=180, value=0)
        comment = st.text_area("Comentario")
        add = st.form_submit_button("Agregar registro")
    if add:
        st.session_state.log.append({
            "fecha": d.isoformat(), "especie": spn, "acción": action,
            "producto_nota": product, "carencia_dias": int(carencia), "comentario": comment
        })
    if st.session_state.log:
        df = pd.DataFrame(st.session_state.log)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Descargar registro CSV", df.to_csv(index=False), "registro_pumalal.csv", "text/csv")
    else:
        st.info("Aún no hay registros en esta sesión.")

with tab6:
    st.subheader("Fuentes y criterio")
    st.write(kb.get("metadata", {}).get("methodology", ""))
    for s in kb.get("metadata", {}).get("sources", []):
        st.markdown(f"- **{s.get('name','')}** — {s.get('role','')}")
        if s.get("url"):
            st.caption(s["url"])
    st.warning("La app no entrega dosis ni mezclas de plaguicidas. En fruta: etiqueta SAG, producto autorizado y carencia mandan.")
