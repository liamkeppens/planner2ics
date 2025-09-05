# 🗓️ Planner → ICS Generator

Met deze tool kan je je werkplanning (PDF, CSV of Excel) omzetten naar een `.ics`-bestand dat je kan importeren in **Google Calendar**, **Apple Calendar** of **Outlook**.

## ✨ Features
- ✅ Upload je planning (PDF/CSV/Excel)
- ✅ Automatische herkenning van dag- en nachtdiensten
- ✅ Locatie parsing (enkel échte adresregels, geen “Periode …” of notities)
- ✅ Export naar `.ics` met correcte begin- en eindtijden
- ✅ Optioneel reminders instellen (dagen, uren of minuten op voorhand)
- ✅ **Standaard géén reminders** in de `.ics`
- ✅ Tijden zonder tijdzone (aanbevolen) of met gekozen tijdzone

## 🚀 Gebruik
1. Ga naar [https://planner.uploadplanning.be](https://planner.uploadplanning.be)  
   (of naar de Streamlit Cloud link van de app).
2. Upload je planning (PDF, CSV of Excel).
3. Bekijk de herkende diensten in de tabel.
4. Kies of je herinneringen wil (of standaard geen).
5. Download de `.ics`.
6. Importeer in Google/Apple/Outlook kalender.

## 🔔 Belangrijk over herinneringen
- Als je in de app **“Geen herinnering toevoegen”** aanvinkt, voegen wij **geen enkele `VALARM`** toe in de `.ics`.
- Toch kan je bij import in **Google/Apple/Outlook** nog een melding krijgen (meestal 30 minuten op voorhand).  
  👉 Dit komt door de **standaardmelding van je kalender**, niet door ons `.ics`.
- Je kan dit aanpassen of uitschakelen in de instellingen van je kalender:
  - **Google Calendar** → ⚙️ Instellingen → kies agenda → *Standaardmeldingen* → verwijder “30 minuten”.
  - **Apple Calendar** → Voorkeuren → *Meldingen*.
  - **Outlook** → Bestand → Opties → *Agenda* → *Standaardherinneringen*.

## 📦 Installatie (lokaal)
Voor developers of self-hosting:
```bash
git clone https://github.com/<jouw-username>/planner2ics.git
cd planner2ics
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
