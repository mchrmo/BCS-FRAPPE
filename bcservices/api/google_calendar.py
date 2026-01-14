import frappe
import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIG (Načítavaný z DocTypu Nastavenie)
# --------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]
ADMIN_DISPLAY_NAME = "Admin"

def get_settings():
    """Pomocná funkcia na získanie hodnôt z Nastavenia"""
    return frappe.get_single("Nastavenie")

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def get_calendar_service():
    settings = get_settings()
    
    # Získame cestu k súboru z poľa Attach
    json_file_path = settings.google_json_file
    
    if not json_file_path:
        frappe.throw("V nastaveniach chýba Google JSON súbor.")

    # Prevod relatívnej cesty (/files/...) na absolútnu cestu na serveri
    absolute_path = frappe.get_site_path(json_file_path.strip("/"))
    
    # Ak by súbor nebol nájdený cez relatívnu cestu, skúsime ju vybudovať manuálne
    if not os.path.exists(absolute_path):
        # Štandardné Frappe ukladanie: public/files/ alebo private/files/
        absolute_path = frappe.get_public_path(json_file_path.strip("/"))

    if not os.path.exists(absolute_path):
        raise FileNotFoundError(f"Google Calendar JSON súbor nebol nájdený na ceste: {absolute_path}")

    credentials = service_account.Credentials.from_service_account_file(
        absolute_path,
        scopes=SCOPES,
    )

    return build("calendar", "v3", credentials=credentials)


# --------------------------------------------------
# CREATE CALL EVENT
# --------------------------------------------------
def create_call_event(call_doc, display_title: str):
    service = get_calendar_service()
    settings = get_settings()
    
    calendar_id = settings.google_calendar_id
    if not calendar_id:
        frappe.throw("V nastaveniach chýba Google Calendar ID (Email).")

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    end_dt = start_dt + timedelta(minutes=30)

    event = {
        "summary": f"Hovor – {display_title}",
        "description": (
            f"Hovor cez aplikáciu\n"
            f"Značka klienta: {display_title}\n"
            f"Poradca: {ADMIN_DISPLAY_NAME}\n\n"
            f"Call ID: {call_doc.name}"
        ),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "Europe/Bratislava",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Europe/Bratislava",
        },
    }

    created_event = (
        service.events()
        .insert(
            calendarId=calendar_id, # Použité ID z nastavení
            body=event,
        )
        .execute()
    )

    return created_event.get("id")

# --------------------------------------------------
# UPDATE CALL EVENT END
# --------------------------------------------------
def update_call_event_end(call_doc, display_title: str):
    if not getattr(call_doc, "google_event_id", None):
        return

    service = get_calendar_service()
    settings = get_settings()
    calendar_id = settings.google_calendar_id

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    end_dt = datetime.combine(
        call_doc.koniec_datum,
        datetime.strptime(call_doc.koniec_cas, "%H:%M:%S").time(),
    )

    duration_minutes = max(1, int((call_doc.trvanie_s or 0) / 60))

    try:
        event = service.events().get(
            calendarId=calendar_id, # Použité ID z nastavení
            eventId=call_doc.google_event_id,
        ).execute()

        event["summary"] = f"Hovor – {display_title} ({duration_minutes} min)"
        event["description"] = (
            f"Dokončený hovor\n"
            f"Značka klienta: {display_title}\n"
            f"Poradca: {ADMIN_DISPLAY_NAME}\n"
            f"Trvanie: {duration_minutes} min\n\n"
            f"Call ID: {call_doc.name}"
        )

        event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Bratislava"}
        event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Bratislava"}

        service.events().update(
            calendarId=calendar_id, # Použité ID z nastavení
            eventId=call_doc.google_event_id,
            body=event,
        ).execute()
        
    except Exception as e:
        frappe.log_error(f"Google Calendar Update Error: {e}", "BC Calendar Update")
