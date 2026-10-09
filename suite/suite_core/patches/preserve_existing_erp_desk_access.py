import frappe

ROLE = "Gama - Desk Access"
SUITE_ROLES = ("Suite User", "Suite Admin")


def execute() -> None:
    """Keep existing ERP users on Desk when the Suite roles stop granting access."""
    if not is_erp_site():
        return
    users = existing_users_relying_on_suite_roles()
    if not users:
        return
    if not frappe.db.exists("Role", ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1, "is_custom": 1}).insert(
            ignore_permissions=True
        )
    elif not frappe.db.get_value("Role", ROLE, "desk_access"):
        frappe.throw(f"{ROLE} must grant Desk access before the Suite role migration.")
    for name in users:
        user = frappe.get_doc("User", name)
        if ROLE not in {row.role for row in user.roles}:
            user.append("roles", {"role": ROLE})
            user.save(ignore_permissions=True)


def existing_users_relying_on_suite_roles() -> list[str]:
    user = frappe.qb.DocType("User")
    has_role = frappe.qb.DocType("Has Role")
    role = frappe.qb.DocType("Role")
    holders = (
        frappe.qb.from_(has_role)
        .select(has_role.parent)
        .where((has_role.parenttype == "User") & has_role.role.isin(SUITE_ROLES))
    )
    desk_users = (
        frappe.qb.from_(has_role)
        .join(role)
        .on(role.name == has_role.role)
        .select(has_role.parent)
        .where((has_role.parenttype == "User") & (role.desk_access == 1) & role.name.notin(SUITE_ROLES))
    )
    return (
        frappe.qb.from_(user)
        .select(user.name)
        .where(
            (user.user_type == "System User")
            & (user.name != "Administrator")
            & user.name.isin(holders)
            & user.name.notin(desk_users)
        )
        .run(pluck=True)
    )


def is_erp_site() -> bool:
    return {"erpnext", "gama"}.issubset(frappe.get_installed_apps())
