// Filtre prehľadu. Predvolene aktuálny týždeň (pondelok – nedeľa).
frappe.query_reports["Prehlad aktivit"] = {
	filters: [
		{
			fieldname: "od",
			label: __("Od"),
			fieldtype: "Date",
			default: frappe.datetime.week_start(),
			reqd: 1
		},
		{
			fieldname: "do",
			label: __("Do"),
			fieldtype: "Date",
			default: frappe.datetime.week_end(),
			reqd: 1
		},
		{
			fieldname: "poradca",
			label: __("Poradca"),
			fieldtype: "Link",
			options: "Poradca"
		},
		{
			fieldname: "klient",
			label: __("Klient"),
			fieldtype: "Link",
			options: "Klient"
		},
		{
			fieldname: "rozpis",
			label: __("Rozpis"),
			fieldtype: "Select",
			options: "Po dvojiciach\nPo ludoch\nJednotlive zaznamy",
			default: "Po dvojiciach",
			reqd: 1
		}
	]
};
