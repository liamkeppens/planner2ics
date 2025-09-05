import io
import re
import hashlib
import pdfplumber
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from dateutil import tz
from dateutil.parser import parse as dtparse
from icalendar import Calendar, Event, Alarm
from unidecode import unidecode

# ---------- App meta ----------
st.set_page_config(page_title="Planner → ICS", page_icon="🗓️", layout="centered")
st.title("🗓️ Planner → ICS generator")
st.caption("Upload je planning (PDF/CSV/Excel) en download een .ics. Dag-/nachtdienst titels, instelbare reminders, en tijdzone-fix.")

# ---------- Regex/const ----------
MONTHS_NL = {
    "JANUARI": 1, "FEBRUARI": 2, "MAART": 3, "APRIL": 4, "MEI": 5, "JUNI": 6,
    "JULI": 7, "AUGUSTUS": 8, "SEPTEMBER": 9, "OKTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})")  # dash & en-dash
DAY_RE = re.compile(r"(^|\s)(\d{1,2})\s*(MA|DI|WO|DO|VR|ZA|ZO)\b", re.IGNORECASE)
PERIODE_RE = re.compile(r"PERIODE\s*:\s*([A-Z]+)\s+(\d{4})", re.IGNORECASE)
ADDRESS_RE = re.compile(r"\b(\d{4})\b.*")  # simpele postcode-heuristiek

# ---------- Helpers ----------
def detect_month_year(text: str):
    for line in text.splitlines():
        m = PERIODE_RE.search(unidecode(line.upper()))
        if m:
            month_name, year = m.group(1), int(m.group(2))
            month = MONTHS_NL.get(month_name)
            if month:
                return month, year
    return None, None

def pdf_to_lines(file_bytes: bytes) -> list[str]:
    lines = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.splitlines())
    return [l.rstrip() for l in lines]

def normalize_time(t: str) -> str:
    h, m = t.strip().split(":")
    return f"{int(h):02d}:{int(m):02d}"

def classify_shift(start_hhmm: str) -> str:
    h = int(start_hhmm.split(":")[0])
    return "Nachtdienst" if h >= 18 or h < 6 else "Dagdienst"

def build_uid(day: int, start: str, end: str, title: str, loc: str) -> str:
    raw = f"{day}-{start}-{end}-{title}-{loc}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest() + "@planner2ics"

def parse_pdf_schedule(file_bytes: bytes):
    """Parse PDF → rijen: {date, start, end, title, location, notes}"""
    lines = pdf_to_lines(file_bytes)
    full_text = "\n".join(lines)
    month, year = detect_month_year(full_text)
    if not month or not year:
        raise ValueError("Kon 'Periode : <MAAND> <JAAR>' niet vinden in de PDF.")

    results, current_loc = [], None
    for i, line in enumerate(lines):
        u = unidecode(line)

        if ADDRESS_RE.search(u):
    # gebruik alleen de regel met postcode, niet de vorige of andere tekst
    current_loc = u.strip()


        if DAY_RE.search(u) and TIME_RE.search(u):
            if "OFF" in u.upper():
                continue
            day = int(DAY_RE.search(u).group(2))
            start_h, end_h = normalize_time(TIME_RE.search(u).group(1)), normalize_time(TIME_RE.search(u).group(2))
            try:
                start_dt = datetime(year, month, day, int(start_h[:2]), int(start_h[3:]))
            except ValueError:
                continue
            results.append({
                "date": start_dt.date().isoformat(),
                "start": start_h,
                "end": end_h,
                "title": classify_shift(start_h),
                "location": current_loc or "",
                "notes": "",
            })
    return results

# --- Automatische kolomherkenning voor CSV/XLSX ---
def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())

COLUMN_ALIASES = {
    "date": {"date", "datum", "dag", "day"},
    "start": {"start", "from", "van", "begin", "starttijd", "starttime"},
    "end": {"end", "tot", "einde", "to", "eindtijd", "endtime", "stop"},
    "title": {"title", "titel", "dienst", "shift", "type"},
    "location": {"location", "locatie", "adres", "address", "place"},
    "notes": {"notes", "opmerking", "opmerkingen", "notities", "description", "beschrijving"},
}
def guess_columns(df: pd.DataFrame):
    cols = list(df.columns)
    norm_map = {_norm(c): c for c in cols}
    result = {}
    for want, aliases in COLUMN_ALIASES.items():
        chosen = None
        for a in aliases:
            if a in norm_map:
                chosen = norm_map[a]; break
        if not chosen and want in norm_map:
            chosen = norm_map[want]
        result[want] = chosen
    return result

def df_to_ics(df: pd.DataFrame, tz_name: str, reminder_value: int, reminder_unit: str,
              force_local_times: bool, no_reminder: bool) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Planner→ICS//NL")
    cal.add("version", "2.0")

    tzinfo = tz.gettz(tz_name)
    for _, row in df.iterrows():
        date = pd.to_datetime(str(row["date"]), errors="coerce")
        if pd.isna(date):
            continue
        sh, sm = map(int, str(row["start"]).split(":"))
        eh, em = map(int, str(row["end"]).split(":"))

        if force_local_times:
            start_dt = datetime(date.year, date.month, date.day, sh, sm)
            end_dt   = datetime(date.year, date.month, date.day, eh, em)
            if end_dt <= start_dt: end_dt += timedelta(days=1)
        else:
            start_dt = datetime(date.year, date.month, date.day, sh, sm, tzinfo=tzinfo)
            end_dt   = start_dt.replace(hour=eh, minute=em)
            if end_dt <= start_dt: end_dt += timedelta(days=1)

        title = str(row.get("title", "Werkdienst") or "Werkdienst")
        location = str(row.get("location", "") or "")
        desc = str(row.get("notes", "") or "")

        ev = Event()
        ev.add("summary", title)
        if location: ev.add("location", location)
        if desc:     ev.add("description", desc)
        ev.add("dtstart", start_dt)
        ev.add("dtend", end_dt)
        ev.add("uid", build_uid(date.day, row["start"], row["end"], title, location))
        ev.add("dtstamp", datetime.utcnow())

        if not no_reminder:
            alarm = Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", f"Herinnering: {title} — {location}" if location else f"Herinnering: {title}")
            if reminder_unit == "dagen":
                delta = timedelta(days=int(reminder_value))
            elif reminder_unit == "uren":
                delta = timedelta(hours=int(reminder_value))
            else:
                delta = timedelta(minutes=int(reminder_value))
            alarm.add("trigger", -delta)  # negatief = vóór aanvang
            ev.add_component(alarm)

        cal.add_component(ev)

    return cal.to_ical()

# ---------- Sidebar instellingen ----------
with st.sidebar:
    st.header("Instellingen")
    tz_name = st.selectbox(
        "Tijdzone (alleen relevant als je géén 'lokale tijden' forceert)",
        options=["Europe/Brussels", "Europe/Amsterdam", "Europe/Berlin", "Europe/Paris", "UTC", "America/New_York"],
        index=0,
    )
    r_unit = st.selectbox("Herinnering eenheid", ["dagen", "uren", "minuten"], index=0)
    r_value = st.number_input("Herinnering hoeveel van tevoren", min_value=0, max_value=30, value=1, step=1)
    force_local_times = st.checkbox("Forceer lokale tijden (zonder tijdzone) – aanbevolen", value=True)
    no_reminder = st.checkbox("Geen herinnering toevoegen", value=True)  # standaard géén reminder

# ---------- Upload ----------
st.subheader("1) Upload je planning (PDF, CSV of Excel)")
uploaded = st.file_uploader("Kies bestand", type=["pdf", "csv", "xlsx"])
parsed_rows = None

if uploaded:
    name = uploaded.name.lower()
    if name.endswith(".pdf"):
        try:
            data = uploaded.read()
            rows = parse_pdf_schedule(data)
            parsed_rows = pd.DataFrame(rows)
        except Exception as e:
            st.error(f"Kon PDF niet parsen: {e}")
    elif name.endswith(".csv"):
        parsed_rows = pd.read_csv(uploaded)
    else:  # xlsx
        parsed_rows = pd.read_excel(uploaded)

    if parsed_rows is not None and not parsed_rows.empty:
        # ---------- Automatische kolomherkenning ----------
        st.subheader("2) Gevonden diensten (automatisch herkend)")
        g = guess_columns(parsed_rows)

        norm = pd.DataFrame()
        def pick(name, default=""):
            col = g.get(name)
            return parsed_rows[col] if col in parsed_rows.columns else default

        norm["date"] = pick("date")
        norm["start"] = pick("start")
        norm["end"] = pick("end")
        norm["title"] = pick("title", "")
        norm["location"] = pick("location", "")
        norm["notes"] = pick("notes", "")

        # Auto titel & tijdformaat
        def _auto_title(row):
            t = str(row.get("title", "")).strip()
            if t: return t
            try:
                h = int(str(row["start"]).split(":")[0])
                return "Nachtdienst" if h >= 18 or h < 6 else "Dagdienst"
            except Exception:
                return "Werkdienst"
        norm["title"] = norm.apply(_auto_title, axis=1)

        def _norm_time(x):
            m = re.match(r"\s*(\d{1,2}):(\d{2})\s*", str(x))
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else str(x)
        norm["start"] = norm["start"].map(_norm_time)
        norm["end"]   = norm["end"].map(_norm_time)

        st.dataframe(norm[["date", "start", "end", "title", "location"]].head(50), use_container_width=True)

        # ---------- Geavanceerde mapping (optioneel) ----------
        with st.expander("Geavanceerde mapping (optioneel)"):
            cols = parsed_rows.columns.tolist()
            date_col  = st.selectbox("Datum kolom", options=cols, index=cols.index(g["date"]) if g["date"] in cols else 0)
            start_col = st.selectbox("Starttijd kolom", options=cols, index=cols.index(g["start"]) if g["start"] in cols else 0)
            end_col   = st.selectbox("Eindtijd kolom", options=cols, index=cols.index(g["end"]) if g["end"] in cols else 0)
            title_col = st.selectbox("Titel kolom", options=["(geen)"]+cols, index=(cols.index(g["title"])+1) if g["title"] in cols else 0)
            loc_col   = st.selectbox("Locatie kolom", options=["(geen)"]+cols, index=(cols.index(g["location"])+1) if g["location"] in cols else 0)
            notes_col = st.selectbox("Notities kolom", options=["(geen)"]+cols, index=(cols.index(g["notes"])+1) if g["notes"] in cols else 0)
            if st.button("Pas mapping toe"):
                norm["date"] = parsed_rows[date_col]
                norm["start"] = parsed_rows[start_col]
                norm["end"] = parsed_rows[end_col]
                norm["title"] = parsed_rows[title_col] if title_col != "(geen)" else ""
                norm["location"] = parsed_rows[loc_col] if loc_col != "(geen)" else ""
                norm["notes"] = parsed_rows[notes_col] if notes_col != "(geen)" else ""
                st.success("Mapping toegepast. Controleer de tabel hierboven.")

        # ---------- Export ----------
        st.subheader("3) Genereer ICS")
        if force_local_times:
            st.info("Export zet tijden zonder tijdzone (floating). Google toont ze dan exact zoals hierboven.")
        else:
            st.warning(f"Export gebruikt tijdzone: {tz_name}. Bij afwijkende kalender-TZ kunnen tijden verschuiven.")

        # Status over herinneringen
        if no_reminder:
            st.warning("⚠️ Er worden géén herinneringen toegevoegd aan dit .ics-bestand.")
        else:
            unit_map = {"dagen": "dag", "uren": "uur", "minuten": "minuut"}
            unit_label = unit_map.get(r_unit, r_unit)
            amount = int(r_value)
            unit_text = ("uur" if amount == 1 else "uren") if unit_label == "uur" else (unit_label if amount == 1 else unit_label + "en")
            st.success(f"✅ Herinneringen actief: {amount} {unit_text} vóór aanvang.")

        if st.button("Maak .ics"):
            ics_bytes = df_to_ics(norm, tz_name, int(r_value), r_unit, force_local_times, no_reminder)
            try:
                first_date = pd.to_datetime(norm["date"]).min()
                fname = f"planning_{first_date.year}_{first_date.month:02d}.ics"
            except Exception:
                fname = "planning.ics"

            st.download_button("Download .ics", ics_bytes, file_name=fname, mime="text/calendar")
            st.info("✅ Bestand klaar. Importeer in Google/Apple/Outlook kalender.")
    else:
        st.info("Geen rijen gevonden. Controleer of je bestand duidelijk datum en tijden bevat.")

st.markdown("---")
st.caption("Nachtdiensten (eind vóór start) worden automatisch naar de volgende dag verlengd. Gebruik 'Forceer lokale tijden' om verschuivingen te voorkomen.")
