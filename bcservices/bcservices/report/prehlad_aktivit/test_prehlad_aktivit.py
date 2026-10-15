# Copyright (c) 2026, Focus Hub s.r.o and contributors
# For license information, please see license.txt

"""Testy rozpisu 'Po dvojiciach'.

Spustenie: bench --site <site> run-tests --module \
  bcservices.bcservices.report.prehlad_aktivit.test_prehlad_aktivit
"""

import unittest
from datetime import date, datetime

import frappe

from bcservices.bcservices.report.prehlad_aktivit.prehlad_aktivit import _by_pair


def _call(poradca=None, poradca2=None, klient=None, sekundy=60):
	return frappe._dict(
		name="c", klient=klient, poradca=poradca, poradca2=poradca2,
		kto_volal="Klient" if klient else "Poradca", trvanie_s=sekundy,
		zaciatok_datum=date(2026, 10, 12), zaciatok_cas="10:00:00",
		je_konferencia=0, ucastnici=[],
	)


def _sprava(poradca=None, poradca2=None, klient=None, skupina=None):
	return frappe._dict(
		name="m", sprava_id="m", datum_cas=datetime(2026, 10, 12, 11, 0),
		odosielatel="a@x.sk", prijemca="b@x.sk", typ="text",
		klient=klient, poradca=poradca, poradca2=poradca2, skupina=skupina,
	)


class TestPrehladAktivit(unittest.TestCase):
	def test_dvojica_poradcov_sa_nerozdeli_podla_smeru(self):
		"""Hovor Boris→Tomáš a Tomáš→Boris je tá istá dvojica, teda jeden riadok.

		V Denníku hovorov je 'poradca' volajúci a 'poradca2' volaný, takže bez
		zoradenia dvojice vznikli dva riadky pre tých istých dvoch ľudí.
		"""
		calls = [
			_call(poradca="BORIS", poradca2="TOMAS"),
			_call(poradca="TOMAS", poradca2="BORIS"),
		]
		_cols, rows = _by_pair(calls, [])

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["hovory"], 2)
		self.assertEqual(rows[0]["cas"], 120)

	def test_sprava_medzi_poradcami_sa_pripocita_k_tej_istej_dvojici(self):
		spravy = [
			_sprava(poradca="BORIS", poradca2="MICHAL"),
			_sprava(poradca="MICHAL", poradca2="BORIS"),
		]
		_cols, rows = _by_pair([], spravy)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["spravy"], 2)

	def test_dvojica_klient_poradca_ostava_nezmenena(self):
		"""Klient je vždy v poli 'klient', smer tam nikdy problém nerobil."""
		calls = [
			_call(klient="KLIENT1", poradca="BORIS"),
			_call(klient="KLIENT1", poradca="BORIS"),
		]
		spravy = [_sprava(klient="KLIENT1", poradca="BORIS")]
		_cols, rows = _by_pair(calls, spravy)

		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["klient"], "KLIENT1")
		self.assertEqual(rows[0]["hovory"], 2)
		self.assertEqual(rows[0]["spravy"], 1)

	def test_rozne_dvojice_ostanu_oddelene(self):
		calls = [
			_call(poradca="BORIS", poradca2="TOMAS"),
			_call(poradca="BORIS", poradca2="MICHAL"),
			_call(klient="KLIENT1", poradca="BORIS"),
		]
		_cols, rows = _by_pair(calls, [])
		self.assertEqual(len(rows), 3)
