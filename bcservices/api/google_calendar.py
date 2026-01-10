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

def create_call_event(call_doc, caller_username: str):
    service = get_calendar_service()

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    # default trvanie – 30 min (upraviš pri end())
    end_dt = start_dt + timedelta(minutes=30)

    event = {
        "summary": f"Hovor – {caller_username}",
        "description": (
            f"Call ID: {call_doc.name}\n"
            f"Volajúci: {caller_username}\n"
            f"Poradca: {call_doc.poradca}"
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
