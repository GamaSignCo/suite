import frappe
from frappe.sessions import clear_sessions

ROLES = ("Suite User", "Suite Admin")


def execute() -> None:
    """Take Desk access away from the Suite roles and from the users who had it through them.

    Suite's own apps are the interface for both roles; Desk is left to roles that grant it
    themselves, System Manager above all. A user whose only desk-access roles were the Suite
    ones therefore becomes a Website User.

    The role fixture carries the same change, but fixtures sync after patches, and Frappe
    then re-evaluates every holder with a full ``User.save``. Doing it here first, in bulk,
    leaves that sync nothing to re-evaluate.

    Sessions remember the ``user_type`` they were started with and Desk trusts it, so the
    demoted users are logged out, exactly as Frappe does when a save changes the type.
    """

    frappe.db.set_value("Role", {"name": ("in", ROLES)}, "desk_access", 0, update_modified=False)

    users = system_users_without_desk_access()
    if not users:
        return

    frappe.db.set_value("User", {"name": ("in", users)}, "user_type", "Website User", update_modified=False)
    for user in users:
        clear_sessions(user=user, force=True)


def system_users_without_desk_access() -> list[str]:
    """Holders of the Suite roles still typed System User with no desk-access role to justify it."""

    user = frappe.qb.DocType("User")
    has_role = frappe.qb.DocType("Has Role")
    role = frappe.qb.DocType("Role")

    holders = (
        frappe.qb.from_(has_role)
        .select(has_role.parent)
        .where((has_role.parenttype == "User") & has_role.role.isin(ROLES))
    )
    desk_users = (
        frappe.qb.from_(has_role)
        .join(role)
        .on(role.name == has_role.role)
        .select(has_role.parent)
        .where((has_role.parenttype == "User") & (role.desk_access == 1))
    )

    return (
        frappe.qb.from_(user)
        .select(user.name)
        .where(
            (user.user_type == "System User")
            # Administrator is a System User by definition, whatever roles it holds.
            & (user.name != "Administrator")
            & user.name.isin(holders)
            & user.name.notin(desk_users)
        )
        .run(pluck=True)
    )
