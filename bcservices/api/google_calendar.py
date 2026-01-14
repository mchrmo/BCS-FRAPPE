import frappe
import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]

SERVICE_ACCOUNT_FILE = frappe.get_site_path(
    "private",
    "files",
    "summer-heaven-478513-q6-323b705c6baa.json",
)

ADMIN_CALENDAR_ID = "andrej.cernak2007@gmail.com"
ADMIN_DISPLAY_NAME = "Admin"


# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def get_calendar_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"Google Calendar JSON not found: {SERVICE_ACCOUNT_FILE}"
        )

    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )

    return build("calendar", "v3", credentials=credentials)


# --------------------------------------------------
# CREATE CALL EVENT
# --------------------------------------------------
def create_call_event(call_doc, display_title: str):
    """
    Vytvorí udalosť v kalendári. 
    display_title je hodnota z pola 'znacka_klienta'.
    """
    service = get_calendar_service()

    # Prevod času zo stringu na datetime objekt
    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    # Predvolená dĺžka v kalendári (30 minút)
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
            calendarId=ADMIN_CALENDAR_ID,
            body=event,
        )
        .execute()
    )

    return created_event.get("id")


# --------------------------------------------------
# UPDATE CALL EVENT END (Volá sa pri ukončení hovoru)
# --------------------------------------------------
def update_call_event_end(call_doc, display_title: str):
    """
    Aktualizuje udalosť po skončení hovoru (reálny čas a trvanie).
    """
    if not getattr(call_doc, "google_event_id", None):
        return

    service = get_calendar_service()

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
            calendarId=ADMIN_CALENDAR_ID,
            eventId=call_doc.google_event_id,
        ).execute()

        # Aktualizujeme summary so značkou a reálnym trvaním
        event["summary"] = (
            f"Hovor – {display_title} ({duration_minutes} min)"
        )

        event["description"] = (
            f"Dokončený hovor\n"
            f"Značka klienta: {display_title}\n"
            f"Poradca: {ADMIN_DISPLAY_NAME}\n"
            f"Trvanie: {duration_minutes} min\n\n"
            f"Call ID: {call_doc.name}"
        )

        event["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": "Europe/Bratislava",
        }

        event["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Europe/Bratislava",
        }

        service.events().update(
            calendarId=ADMIN_CALENDAR_ID,
            eventId=call_doc.google_event_id,
            body=event,
        ).execute()
        
    except Exception as e:
        frappe.log_error(f"Google Calendar Update Error: {e}", "BC Calendar Update")
