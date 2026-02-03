import frappe
import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def get_calendar_service(advisor_doc):
    """
    Získa Google Calendar službu pre konkrétneho poradcu.
    Očakáva na vstupe dokument poradcu (nie ID).
    """
    
    # Získame cestu k súboru priamo z dokumentu poradcu
    json_file_path = advisor_doc.google_json_file
    
    if not json_file_path:
        frappe.throw(f"Poradca {advisor_doc.name} nemá nahraný Google JSON súbor.")

    # Prevod relatívnej cesty (/files/...) na absolútnu cestu na serveri
    absolute_path = frappe.get_site_path(json_file_path.strip("/"))
    
    # Ak by súbor nebol nájdený cez relatívnu cestu, skúsime ju vybudovať manuálne
    if not os.path.exists(absolute_path):
        # Štandardné Frappe ukladanie: public/files/ alebo private/files/
        absolute_path = frappe.get_public_path(json_file_path.strip("/"))

    if not os.path.exists(absolute_path):
        # Skúsiť pozrieť do private files, ak je súbor súkromný
        absolute_path = frappe.get_site_path("private", "files", json_file_path.split("/")[-1])

    if not os.path.exists(absolute_path):
        raise FileNotFoundError(f"Google Calendar JSON súbor nebol nájdený pre poradcu {advisor_doc.name} na ceste: {absolute_path}")

    credentials = service_account.Credentials.from_service_account_file(
        absolute_path,
        scopes=SCOPES,
    )

    return build("calendar", "v3", credentials=credentials)


def get_advisor_doc(call_doc):
    """
    Nájde dokument poradcu na základe hovoru.
    Získa ho cez Link pole 'poradca'.
    """
    if not call_doc.poradca:
        frappe.throw("Hovor nemá priradeného poradcu, nie je možné zapísať do kalendára.")
        
    # Predpokladáme, že DocType, na ktorý odkazuje pole 'poradca', sa volá 'Poradca'
    return frappe.get_doc("Poradca", call_doc.poradca)

# --------------------------------------------------
# CREATE CALL EVENT
# --------------------------------------------------
def create_call_event(call_doc, display_title: str):
    # 1. Načítame poradcu priradeného k hovoru
    advisor = get_advisor_doc(call_doc)
    
    # 2. Vytvoríme službu s credentials konkrétneho poradcu
    service = get_calendar_service(advisor)
    
    # 3. Získame Calendar ID z profilu poradcu
    calendar_id = advisor.google_calendar_id
    
    if not calendar_id:
        frappe.throw(f"Poradca {advisor.meno} nemá nastavené Google Calendar ID.")

    start_dt = datetime.combine(
        call_doc.zaciatok_datum,
        datetime.strptime(call_doc.zaciatok_cas, "%H:%M:%S").time(),
    )

    end_dt = start_dt + timedelta(minutes=30)
    
    # Použijeme meno poradcu do popisu (ak má pole 'meno', inak ID)
    advisor_display_name = advisor.meno if hasattr(advisor, 'meno') else advisor.name

    event = {
        "summary": f"Hovor – {display_title}",
        "description": (
            f"Hovor cez aplikáciu\n"
            f"Značka klienta: {display_title}\n"
            f"Poradca: {advisor_display_name}\n\n"
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

    try:
        created_event = (
            service.events()
            .insert(
                calendarId=calendar_id, 
                body=event,
            )
            .execute()
        )
        return created_event.get("id")
        
    except Exception as e:
        frappe.log_error(f"Google Calendar Insert Error (Poradca: {advisor.name}): {e}", "BC Calendar Insert")
        return None

# --------------------------------------------------
# UPDATE CALL EVENT END
# --------------------------------------------------
def update_call_event_end(call_doc, display_title: str):
    if not getattr(call_doc, "google_event_id", None):
        return

    # 1. Načítame poradcu
    advisor = get_advisor_doc(call_doc)
    
    # 2. Služba a Calendar ID
    service = get_calendar_service(advisor)
    calendar_id = advisor.google_calendar_id
    
    advisor_display_name = advisor.meno if hasattr(advisor, 'meno') else advisor.name

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
            calendarId=calendar_id,
            eventId=call_doc.google_event_id,
        ).execute()

        event["summary"] = f"Hovor – {display_title} ({duration_minutes} min)"
        event["description"] = (
            f"Dokončený hovor\n"
            f"Značka klienta: {display_title}\n"
            f"Poradca: {advisor_display_name}\n"
            f"Trvanie: {duration_minutes} min\n\n"
            f"Call ID: {call_doc.name}"
        )

        event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Bratislava"}
        event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Bratislava"}

        service.events().update(
            calendarId=calendar_id,
            eventId=call_doc.google_event_id,
            body=event,
        ).execute()
        
    except Exception as e:
        frappe.log_error(f"Google Calendar Update Error (Poradca: {advisor.name}): {e}", "BC Calendar Update")
