import frappe
import os
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# 🔑 PRESNÝ NÁZOV TVOJHO JSON SÚBORU
SERVICE_ACCOUNT_FILE = frappe.get_site_path(
    "private",
    "files",
    "summer-heaven-478513-q6-323b705c6baa.json",
)

# Adminov Google kalendár
ADMIN_CALENDAR_ID = "andrej.cernak2007@gmail.com"  # môžeš dať aj email admin@gmail.com
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



def update_call_event_end(call_doc, caller_username: str):
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

    event = service.events().get(
        calendarId=ADMIN_CALENDAR_ID,
        eventId=call_doc.google_event_id,
    ).execute()

    event["summary"] = (
        f"Hovor – {ADMIN_DISPLAY_NAME} – {caller_username} "
        f"({duration_minutes} min)"
    )

    event["description"] = (
        f"Hovor medzi:\n"
        f"Poradca: {ADMIN_DISPLAY_NAME}\n"
        f"Volajúci: {caller_username}\n"
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

# --------------------------------------------------
# CREATE CALL EVENT
# --------------------------------------------------

def create_call_event(call_doc, caller_username: str):
    service = get_calendar_service()

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    # default trvanie – 30 min
    end_dt = start_dt + timedelta(minutes=30)

    event = {
        "summary": f"Hovor – {ADMIN_DISPLAY_NAME} – {caller_username}",
        "description": (
            f"Hovor medzi:\n"
            f"Poradca: {ADMIN_DISPLAY_NAME}\n"
            f"Volajúci: {caller_username}\n\n"
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

