import frappe
import os
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# 🔑 PRESNÝ NÁZOV SERVICE ACCOUNT JSON
SERVICE_ACCOUNT_FILE = frappe.get_site_path(
    "private",
    "files",
    "summer-heaven-478513-q6-323b705c6baa.json",
)

# Admin Google kalendár
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
# UPDATE CALL EVENT (END TIME)
# --------------------------------------------------

def update_call_event_end(call_doc, znacka_klienta: str):
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

    event = service.events().get(
        calendarId=ADMIN_CALENDAR_ID,
        eventId=call_doc.google_event_id,
    ).execute()

    # 🔹 FINÁLNY NÁZOV A POPIS
    event["summary"] = znacka_klienta
    event["description"] = "daný telefonát"

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

def create_call_event(call_doc, znacka_klienta: str):
    service = get_calendar_service()

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    # default trvanie – 30 min
    end_dt = start_dt + timedelta(minutes=30)

    event = {
        "summary": znacka_klienta,
        "description": "daný telefonát",
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
