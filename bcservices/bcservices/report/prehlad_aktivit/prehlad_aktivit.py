# Copyright (c) 2026, Focus Hub s.r.o and contributors
# For license information, please see license.txt

"""Týždenný prehľad aktivít: čas na hovoroch a počty odoslaných správ.

Hovory sa čítajú z 'Dennik hovorov', správy z 'Aktivita sprav'. Report nič
neukladá — pri každom otvorení sa dopočíta z aktuálnych dát.
"""

from datetime import datetime, time

import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	od = getdate(filters.get("od"))
	do = getdate(filters.get("do"))
	rozpis = filters.get("rozpis") or "Po dvojiciach"

	people = _people_index()
	calls = _load_calls(od, do, filters)
	messages = _load_messages(od, do, filters)

	if rozpis == "Po ludoch":
		return _by_person(calls, messages, people)
	if rozpis == "Jednotlive zaznamy":
		return _detail(calls, messages, people)
	return _by_pair(calls, messages)


# ---------------------------------------------------------------- načítanie


def _people_index():
	"""email -> (rola, docname, zobrazované meno). Poradca má meno v 'meno',
	klient v 'username' — rovnaké rozlíšenie ako v notify.py."""
	index = {}
	for row in frappe.get_all("Poradca", fields=["name", "email", "meno"]):
		if row.email:
			index[row.email.lower()] = ("Poradca", row.name, row.meno or row.name)
	for row in frappe.get_all("Klient", fields=["name", "email", "username"]):
		if row.email:
			index[row.email.lower()] = ("Klient", row.name, row.username or row.name)
	return index


def _load_calls(od, do, filters):
	conds = {"zaciatok_datum": ["between", [od, do]]}
	if filters.get("klient"):
		conds["klient"] = filters.get("klient")

	or_conds = None
	if filters.get("poradca"):
		or_conds = {"poradca": filters.get("poradca"), "poradca2": filters.get("poradca")}

	calls = frappe.get_all(
		"Dennik hovorov",
		filters=conds,
		or_filters=or_conds,
		fields=[
			"name", "klient", "poradca", "poradca2", "kto_volal",
			"trvanie_s", "zaciatok_datum", "zaciatok_cas", "je_konferencia",
		],
		order_by="zaciatok_datum asc, zaciatok_cas asc",
	)

	# Konferencia je jeden záznam s viacerými účastníkmi — bez rozvinutia by sa
	# čas pripísal len dvojici z hlavičky.
	conference_ids = [c.name for c in calls if c.je_konferencia]
	participants = {}
	if conference_ids:
		for row in frappe.get_all(
			"Ucastnik hovoru",
			filters={"parent": ["in", conference_ids], "parenttype": "Dennik hovorov"},
			fields=["parent", "email"],
		):
			participants.setdefault(row.parent, []).append(row.email)

	for call in calls:
		call["ucastnici"] = participants.get(call.name, [])
	return calls


def _load_messages(od, do, filters):
	conds = {"datum_cas": ["between", [datetime.combine(od, time.min), datetime.combine(do, time.max)]]}
	if filters.get("klient"):
		conds["klient"] = filters.get("klient")

	or_conds = None
	if filters.get("poradca"):
		or_conds = {"poradca": filters.get("poradca"), "poradca2": filters.get("poradca")}

	return frappe.get_all(
		"Aktivita sprav",
		filters=conds,
		or_filters=or_conds,
		fields=[
			"name", "sprava_id", "datum_cas", "odosielatel", "prijemca",
			"typ", "klient", "poradca", "poradca2", "skupina",
		],
		order_by="datum_cas asc",
	)


def _call_started_at(call):
	return datetime.combine(getdate(call.zaciatok_datum), (call.zaciatok_cas and _as_time(call.zaciatok_cas)) or time.min)


def _as_time(value):
	if isinstance(value, time):
		return value
	# Frappe vracia Time ako timedelta
	total = int(getattr(value, "total_seconds", lambda: 0)())
	return time(total // 3600 % 24, total % 3600 // 60, total % 60)


# ------------------------------------------------------------ po dvojiciach


def _by_pair(calls, messages):
	"""Riadok = dvojica ľudí (alebo skupina). Pokrýva aj poradca ↔ poradca."""
	columns = [
		{"fieldname": "klient", "label": _("Klient"), "fieldtype": "Link", "options": "Klient", "width": 170},
		{"fieldname": "poradca", "label": _("Poradca"), "fieldtype": "Link", "options": "Poradca", "width": 170},
		{"fieldname": "poradca2", "label": _("Poradca 2"), "fieldtype": "Link", "options": "Poradca", "width": 150},
		{"fieldname": "skupina", "label": _("Skupina"), "fieldtype": "Link", "options": "Skupina", "width": 150},
		{"fieldname": "hovory", "label": _("Hovory"), "fieldtype": "Int", "width": 80},
		{"fieldname": "cas", "label": _("Čas na hovoroch"), "fieldtype": "Duration", "width": 140},
		{"fieldname": "spravy", "label": _("Správy"), "fieldtype": "Int", "width": 90},
		{"fieldname": "posledny", "label": _("Posledný kontakt"), "fieldtype": "Datetime", "width": 160},
	]

	rows = {}

	def bucket(klient, poradca, poradca2, skupina):
		key = (klient, poradca, poradca2, skupina)
		if key not in rows:
			rows[key] = {
				"klient": klient, "poradca": poradca, "poradca2": poradca2,
				"skupina": skupina, "hovory": 0, "cas": 0, "spravy": 0, "posledny": None,
			}
		return rows[key]

	for call in calls:
		row = bucket(call.klient, call.poradca, call.poradca2, None)
		row["hovory"] += 1
		row["cas"] += int(call.trvanie_s or 0)
		row["posledny"] = _later(row["posledny"], _call_started_at(call))

	for msg in messages:
		row = bucket(msg.klient, msg.poradca, msg.poradca2, msg.skupina)
		row["spravy"] += 1
		row["posledny"] = _later(row["posledny"], msg.datum_cas)

	data = sorted(
		rows.values(),
		key=lambda r: (r["klient"] or "", r["poradca"] or "", r["skupina"] or ""),
	)
	return columns, data


# --------------------------------------------------------------- po ľuďoch


def _by_person(calls, messages, people):
	"""Riadok = človek. Odpovedá na „koľko toho kto odoslal a prevolal",
	vrátane správ do skupín."""
	columns = [
		{"fieldname": "meno", "label": _("Meno"), "fieldtype": "Data", "width": 200},
		{"fieldname": "rola", "label": _("Rola"), "fieldtype": "Data", "width": 100},
		{"fieldname": "email", "label": _("E-mail"), "fieldtype": "Data", "width": 220},
		{"fieldname": "odoslane_spravy", "label": _("Odoslané správy"), "fieldtype": "Int", "width": 140},
		{"fieldname": "hovory", "label": _("Hovory"), "fieldtype": "Int", "width": 90},
		{"fieldname": "cas", "label": _("Čas na hovoroch"), "fieldtype": "Duration", "width": 150},
	]

	# docname -> email, aby sa hovor (odkazy) a správa (e-maily) stretli v jednom riadku
	email_by_doc = {(rola, doc): mail for mail, (rola, doc, _n) in people.items()}
	rows = {}

	def bucket(email):
		email = (email or "").lower()
		if not email:
			return None
		if email not in rows:
			rola, _doc, meno = people.get(email, ("", "", email))
			rows[email] = {
				"meno": meno, "rola": rola, "email": email,
				"odoslane_spravy": 0, "hovory": 0, "cas": 0,
			}
		return rows[email]

	for call in calls:
		duration = int(call.trvanie_s or 0)
		emails = set(call.get("ucastnici") or [])
		for rola, doc in (("Klient", call.klient), ("Poradca", call.poradca), ("Poradca", call.poradca2)):
			if doc and email_by_doc.get((rola, doc)):
				emails.add(email_by_doc[(rola, doc)])
		for email in emails:
			row = bucket(email)
			if row:
				row["hovory"] += 1
				row["cas"] += duration

	for msg in messages:
		row = bucket(msg.odosielatel)
		if row:
			row["odoslane_spravy"] += 1

	data = sorted(rows.values(), key=lambda r: (-r["odoslane_spravy"], -r["cas"], r["meno"]))
	return columns, data


# ------------------------------------------------------- jednotlivé záznamy


def _detail(calls, messages, people):
	columns = [
		{"fieldname": "kedy", "label": _("Dátum a čas"), "fieldtype": "Datetime", "width": 170},
		{"fieldname": "druh", "label": _("Typ"), "fieldtype": "Data", "width": 90},
		{"fieldname": "od", "label": _("Od"), "fieldtype": "Data", "width": 190},
		{"fieldname": "komu", "label": _("Komu / Skupina"), "fieldtype": "Data", "width": 220},
		{"fieldname": "cas", "label": _("Trvanie"), "fieldtype": "Duration", "width": 130},
	]

	name_by_doc = {(rola, doc): meno for _m, (rola, doc, meno) in people.items()}

	def person(email):
		entry = people.get((email or "").lower())
		return entry[2] if entry else (email or "")

	data = []

	for call in calls:
		volal_klient = call.kto_volal == "Klient"
		od = name_by_doc.get(("Klient", call.klient)) if volal_klient else name_by_doc.get(("Poradca", call.poradca))
		komu = name_by_doc.get(("Poradca", call.poradca)) if volal_klient else name_by_doc.get(("Klient", call.klient))
		if call.je_konferencia:
			komu = _("Konferencia") + f" ({len(call.get('ucastnici') or [])})"
		elif not komu and call.poradca2:
			komu = name_by_doc.get(("Poradca", call.poradca2))
		data.append({
			"kedy": _call_started_at(call),
			"druh": _("Hovor"),
			"od": od or "",
			"komu": komu or "",
			"cas": int(call.trvanie_s or 0),
		})

	for msg in messages:
		if msg.skupina:
			komu = frappe.db.get_value("Skupina", msg.skupina, "nazov") or msg.skupina
			komu = _("Skupina") + f": {komu}"
		else:
			komu = person(msg.prijemca)
		data.append({
			"kedy": msg.datum_cas,
			"druh": _("Súbor") if msg.typ == "subor" else _("Správa"),
			"od": person(msg.odosielatel),
			"komu": komu,
			"cas": 0,
		})

	data.sort(key=lambda r: r["kedy"])
	return columns, data


def _later(current, candidate):
	if not candidate:
		return current
	if not current:
		return candidate
	return max(current, candidate)
