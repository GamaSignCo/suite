import frappe

SETUP_WIZARD_URL = "/suite/setup"


def uses_suite_setup_wizard() -> bool:
    """Whether this site's setup wizard is Suite's onboarding."""
    try:
        from frappe.desk.page.setup_wizard.setup_wizard import get_setup_wizard_url
    except ImportError:
        return False

    return get_setup_wizard_url() == SETUP_WIZARD_URL


def build_setup_args(timezone: str | None) -> dict:
    """Locale args for Frappe's setup engine: prefilled country, else guessed from timezone."""
    country = frappe.db.get_single_value("System Settings", "country")
    if not country:
        return {"timezone": timezone, **locale_from_timezone(timezone)}

    from frappe.geo.country_info import get_country_info

    return {
        "country": country,
        "currency": frappe.db.get_single_value("System Settings", "currency")
        or get_country_info(country).get("currency"),
        "timezone": timezone or frappe.db.get_single_value("System Settings", "time_zone"),
    }


def locale_from_timezone(timezone: str | None) -> dict:
    """The country and currency a timezone belongs to, like the desk wizard's prefill."""
    if not timezone:
        return {}

    from frappe.geo.country_info import get_all

    for country, info in get_all().items():
        if timezone in info.get("timezones", []):
            return {"country": country, "currency": info.get("currency")}

    return {}
