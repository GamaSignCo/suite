import frappe

# Doctypes that mix in OwnerFromUser (suite.utils.permissions) as of this patch.
OWNER_FROM_USER_DOCTYPES = (
    "Calendar Exchange",
    "Contacts Exchange",
    "Mail Exchange",
    "Mail Queue",
    "Mail Signature",
    "User Account",
    "User Settings",
)


def execute() -> None:
    """Realign ``owner`` with the ``user`` field on records that predate OwnerFromUser.

    The Suite User role reaches these doctypes through ``if_owner``, which keys off the
    standard ``owner`` (created-by) field. New records get ``owner = user`` pinned by the
    OwnerFromUser mixin, but records provisioned before the mixin — e.g. User Settings
    created by the User after_insert hook while an admin or the signup flow's
    Administrator session was active — are still owned by whoever ran the code, so the
    user they belong to gets a 403 on their own record.
    """

    for doctype in OWNER_FROM_USER_DOCTYPES:
        table = frappe.qb.DocType(doctype)
        (
            frappe.qb.update(table)
            .set(table.owner, table.user)
            .where(table.user.isnotnull() & (table.user != "") & (table.owner != table.user))
        ).run()
