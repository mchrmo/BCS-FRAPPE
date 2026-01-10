from google.oauth2 import service_account
from googleapiclient.discovery import build
import frappe
from datetime import datetime, timedelta

SCOPES = ["https://www.googleapis.com/auth/calendar"]
SERVICE_ACCOUNT_FILE = (
    frappe.get_site_path("private", "files", "google-calendar.json")
)

ADMIN_CALENDAR_ID = "primary"  # adminov hlavný kalendár

def get_calendar_service():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials)

def create_call_event(call_doc, caller_username: str):
    service = get_calendar_service()

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    # default 30 min (neskôr update pri end())
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

    created = (
        service.events()
        .insert(calendarId=ADMIN_CALENDAR_ID, body=event)
        .execute()
    )

    return created.get("id")
