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

st.set_page_config(page_title="Planner → ICS", page_icon="🗓️", layout="centered")
st.title("🗓️ Planner → ICS generator")
st.caption("Upload je planning (PDF/CSV/Excel) en download een .ics. Titel = Dagdienst/Nachtdienst. Reminders naar keuze.")

# ---------- Helpers ----------
MONTHS_NL = {
    "JANUARI": 1, "FEBRUARI": 2, "MAART": 3, "APRIL": 4, "MEI": 5, "JUNI": 6,
    "JULI": 7, "AUGUSTUS": 8, "SEPTEMBER": 9, "OKTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

# Ook de en-dash “–” toelaten
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})")
DAY_RE = re.compile(r"(^|\s)(\d{1,2})\s*(MA|DI|WO|DO|VR|ZA|ZO)\b", re.IGNORECASE)
PERIODE_RE = re.compile(r"PERIODE\s*:\s*([A-Z]+)\s+(\d{4})", re.IGNORECASE)
ADDRESS_RE = re.compile(r"\b(\d{4})\b.*")

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

def add_days_if_cross_midnight(start_dt: datetime, end_hhmm: str) -> datetime:
    eh, em = map(int, end_hhmm.split(":"))
    end_dt = start_dt.replace(hour=eh, minute=em)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return end_dt

def parse_pdf_schedule(file_bytes: bytes):
    lines = pdf_to_lines(file_bytes)
    full_text = "\n".join(lines)
    month, year = detect_month_year(full_text)
    if not month or not year:
        raise ValueError("Kon 'Periode : <MAAND> <JAAR>' niet vinden in de PDF.")

    results = []
    current_loc = None

    for i, line in enumerate(lines):
        u = unidecode(line)

        if ADDRESS_RE.search(u):
            prev = unidecode(lines[i-1]) if i > 0 else ""
            current_loc = (prev + "\n" + u).strip()

        if DAY_RE.search(u) and TIME_RE.search(u):
            if "OFF" in u.upper():
                continue
            day = int(DAY_RE.search(u).group(2))
            start_h, end_h = normalize_time(TIME_RE.search(u).group(1)), normalize_time(TIME_RE.search(u).group(2))

            try:
                start_dt = datetime(year, month, day, int(start_h[:2]), int(start_h[3:]))
            except ValueError:
                continue

            title = classify_shift(start_h)
            loc = current_loc or ""

            results.append({
                "date": start_dt.date().isoformat(),
                "start": start_h,
                "end": end_h,
                "title": title,
                "location": loc,
                "notes": "",
            })
    return results

def df_to_ics(df: pd.DataFrame, tz_name: str, reminder_value: int, reminder_unit: str, force_local_times: bool) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Planner→ICS//NL")
    cal.add("version", "2.0")

    tzinfo = tz.gettz(tz_name)

    for _, row in df.iterrows():
        date = dtparse(str(row["date"]))
        sh, sm = map(int, str(row["start"]).split(":"))
        eh, em = map(int, str(row["end"]).split(":"))

        if force_local_times:
            # “floating” tijd: geen TZID → Google neemt exact de kloktijd over
            start_dt = datetime(date.year, date.month, date.day, sh, sm)
            end_dt = datetime(date.year, date.month, date.day, eh, em)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)
        else:
            # TZ-bewust
            start_dt = datetime(date.year, date.month, date.day, sh, sm, tzinfo=tzinfo)
            end_dt = start_dt.replace(hour=eh, minute=em)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

        title = str(row.get("title", "Werkdienst") or "Werkdienst")
        location = str(row.get("location", "") or "")
        desc = str(row.get("notes", "") or "")

        ev = Event()
        ev.add("summary", title)
        if location:
            ev.add("location", location)
        if desc:
            ev.add("description", desc)
        ev.add("dtstart", start_dt)
        ev.add("dtend", end_dt)
        ev.add("uid", build_uid(date.day, row["start"], row["end"], title, location))
        ev.add("dtstamp", datetime.utcnow())

        # Reminder met timedelta (negatief = vooraf)
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"Herinnering: {title} — {location}" if location else f"Herinnering: {title}")
        if reminder_unit == "dagen":
            delta = timedelta(days=int(reminder_value))
        elif reminder_unit == "uren":
            delta = timedelta(hours=int(reminder_value))
        else:
            delta = timedelta(minutes=int(reminder_value))
        alarm.add("trigger", -delta)
        ev.add_component(alarm)

        cal.add_component(ev)

    return cal.to_ical()

# ---------- UI ----------
with st.sidebar:
    st.header("Instellingen")
    tz_name = st.selectbox(
        "Tijdzone (alleen relevant als je GEEN 'lokale tijden' forceert)",
        options=["Europe/Brussels", "Europe/Amsterdam", "Europe/Berlin", "Europe/Paris", "UTC", "America/New_York"],
        index=0,
    )
    r_unit = st.selectbox("Herinnering eenheid", ["dagen", "uren", "minuten"], index=0)
    r_value = st.number_input("Herinnering hoeveel van tevoren", min_value=0, max_value=30, value=1, step=1)
    force_local_times = st.checkbox("Forceer lokale tijden (zonder tijdzone) – aan te raden", value=True)

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
        st.subheader("2) Controleer/Map kolommen")
        cols = parsed_rows.columns.tolist()
        date_col = st.selectbox("Datum kolom", options=cols, index=cols.index("date") if "date" in cols else 0)
        start_col = st.selectbox("Starttijd kolom", options=cols, index=cols.index("start") if "start" in cols else 1)
        end_col = st.selectbox("Eindtijd kolom", options=cols, index=cols.index("end") if "end" in cols else 2)
        title_col = st.selectbox("Titel kolom (Dagdienst/Nachtdienst)", options=["(geen)"] + cols, index=(cols.index("title") + 1) if "title" in cols else 0)
        loc_col = st.selectbox("Locatie kolom", options=["(geen)"] + cols, index=(cols.index("location") + 1) if "location" in cols else 0)
        notes_col = st.selectbox("Notities kolom", options=["(geen)"] + cols, index=(cols.index("notes") + 1) if "notes" in cols else 0)

        # Normaliseren
        norm = pd.DataFrame()
        norm["date"] = parsed_rows[date_col]
        norm["start"] = parsed_rows[start_col]
        norm["end"] = parsed_rows[end_col]
        norm["title"] = parsed_rows[title_col] if title_col != "(geen)" else ""
        norm["location"] = parsed_rows[loc_col] if loc_col != "(geen)" else ""
        norm["notes"] = parsed_rows[notes_col] if notes_col != "(geen)" else ""

        # Auto titel
        def _auto_title(row):
            t = str(row.get("title", "")).strip()
            if t:
                return t
            try:
                h = int(str(row["start"]).split(":")[0])
                return "Nachtdienst" if h >= 18 or h < 6 else "Dagdienst"
            except Exception:
                return "Werkdienst"
        norm["title"] = norm.apply(_auto_title, axis=1)

        # Tijden netjes HH:MM
        def _norm_time(x):
            m = re.match(r"\s*(\d{1,2}):(\d{2})\s*", str(x))
            return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else str(x)
        norm["start"] = norm["start"].map(_norm_time)
        norm["end"] = norm["end"].map(_norm_time)

        # ---------- DEBUG-TABEL ----------
        st.subheader("✅ Gevonden diensten (check de tijden vóór export)")
        st.dataframe(norm[["date", "start", "end", "title", "location"]].head(50), use_container_width=True)

        st.subheader("3) Genereer ICS")
        if force_local_times:
            st.info("Export zet tijden zonder tijdzone (floating). Google toont ze dan exact zoals hierboven.")
        else:
            st.warning(f"Export gebruikt tijdzone: {tz_name}. Als je kalender een andere TZ heeft, kunnen tijden verschuiven.")

        if st.button("Maak .ics"):
            ics_bytes = df_to_ics(norm, tz_name, int(r_value), r_unit, force_local_times)
            try:
                first_date = dtparse(str(norm.iloc[0]["date"]))
                fname = f"planning_{first_date.year}_{first_date.month:02d}.ics"
            except Exception:
                fname = "planning.ics"

            st.download_button(
                label="Download .ics",
                data=ics_bytes,
                file_name=fname,
                mime="text/calendar",
            )
    else:
        st.info("Geen rijen gevonden. Controleer of je bestand duidelijk datum en tijden bevat.")

st.markdown("---")
st.caption("Tip: nachtdiensten (eind vóór start) worden automatisch naar de volgende dag verlengd. Reminders: kies dagen/uren/minuten vooraf.")
