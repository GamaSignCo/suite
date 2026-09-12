from datetime import UTC, datetime
from typing import ClassVar

from suite import __version__
from suite.mail.jmap.models import EmailCreateModel
from suite.mail.jmap.services.core import CallIdGenerator, CoreService
from suite.mail.jmap.services.mail.identity import IdentityService
from suite.mail.jmap.services.mail.mailbox import MailboxService


class EmailSubmissionService(CoreService):
    """Service for handling email submission-related functionality based on the JMAP server capabilities."""

    type: ClassVar[str] = "EmailSubmission"
    capabilities: ClassVar[list[str]] = [
        "urn:ietf:params:jmap:core",
        "urn:ietf:params:jmap:mail",
        "urn:ietf:params:jmap:submission",
    ]
    SUBMISSION_PROPERTIES: ClassVar[list[str]] = ["id", "emailId", "undoStatus", "sendAt"]

    def __post_init__(self) -> None:
        """Post-initialization to check if the JMAP server supports the Mail and EmailSubmission capability and raise an error if not."""

        super().__post_init__()

        if "urn:ietf:params:jmap:mail" not in self.connection.capabilities:
            raise NotImplementedError("The JMAP server does not support the Mail capability.")

        if "urn:ietf:params:jmap:submission" not in self.connection.capabilities:
            raise NotImplementedError("The JMAP server does not support the EmailSubmission capability.")

    @property
    def primary_account_id(self) -> str:
        """Returns the primary account ID for the logged-in user."""

        return self.connection.primary_accounts["urn:ietf:params:jmap:submission"]

    @property
    def max_delayed_send(self) -> int:
        """Returns the maximum delay in seconds allowed for a FUTURERELEASE (RFC 4865) submission, defaulting to 30 days."""

        account = self.connection.accounts.get(self.account) or {}
        submission_caps = (account.get("accountCapabilities") or {}).get(
            "urn:ietf:params:jmap:submission"
        ) or {}

        return int(submission_caps.get("maxDelayedSend") or 2_592_000)

    @staticmethod
    def _build_envelope(
        from_email: str,
        rcpt_emails: set[str] | list[str],
        envelope_id: str,
        priority: int,
        hold_until: int | None = None,
    ) -> dict:
        """Builds the SMTP envelope for a submission; `hold_until` (epoch seconds) adds the RFC 4865 HOLDUNTIL parameter so the server holds delivery."""

        parameters = {
            "RET": "FULL",
            "ENVID": envelope_id,
            "MT-PRIORITY": str(priority),
        }

        if hold_until:
            # RFC 4865 requires an RFC 3339 date-time; Stalwart >= 0.16.17 rejects epoch seconds.
            parameters["HOLDUNTIL"] = datetime.fromtimestamp(hold_until, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        return {
            "mailFrom": {
                "email": from_email,
                "parameters": parameters,
            },
            "rcptTo": [
                {
                    "email": rcpt,
                    "parameters": {
                        "NOTIFY": "DELAY,FAILURE",
                        "ORCPT": f"rfc822;{rcpt}",
                    },
                }
                for rcpt in sorted(set(rcpt_emails))
            ],
        }

    def query(
        self,
        filter: dict | None = None,
        position: int = 0,
        limit: int | None = None,
        sort: list[dict] | None = None,
    ) -> tuple[list[str], int]:
        """Returns one page of ids of submissions matching `filter` (e.g. {"undoStatus":
        "pending"}), in `sort` order (e.g. [{"property": "sentAt", "isAscending": False}]),
        plus the server's total match count.

        The page is filled across follow-up queries when the server enforces a lower limit
        than requested (it then echoes the limit it used, RFC 8620 §5.5) — otherwise a clamp
        below the page length would silently shrink the page and strand the rows behind it,
        since the pager advances in strides of the full page."""

        limit = limit or self.max_objects_in_get
        # One id past the page is a look-ahead: whether more matches exist is then known even
        # when the server's total is missing or zero-valued.
        target = limit + 1

        ids: list[str] = []
        total = None
        while len(ids) < target:
            remaining = target - len(ids)
            response = self._query(filter=filter, position=position + len(ids), limit=remaining, sort=sort)
            if not (method_responses := response.get("methodResponses")):
                if not ids:
                    return [], 0
                break

            body = method_responses[0][1]
            batch = body.get("ids", [])[:remaining]
            served_limit = min(int(body.get("limit") or remaining), remaining)
            if total is None and body.get("total") is not None:
                total = int(body["total"])

            ids.extend(batch)
            # A batch below the enforced limit is the end of the results; one that merely
            # filled a clamp is not — loop on for the rest of the page.
            if not batch or len(batch) < served_limit:
                break
            if total is not None and position + len(ids) >= total:
                break

        has_more = len(ids) > limit
        ids = ids[:limit]

        if total is None:
            # calculateTotal is requested, but RFC 8620 §5.5 lets a server omit total; the
            # floor then sits one past a full page, so the pager can still advance.
            total = position + len(ids) + (1 if has_more else 0)

        return ids, int(total)

    def get(self, ids: list[str], properties: list[str] | None = None) -> list[dict]:
        """Public method to get email submissions by ids, handling batching if the number of ids exceeds the server's maximum allowed in a single 'get' call."""

        results = []
        for batch in self.create_batches(ids, self.max_objects_in_get):
            response = self._get(batch, properties=properties or self.SUBMISSION_PROPERTIES)

            if method_responses := response.get("methodResponses"):
                results.extend(method_responses[0][1].get("list", []))

        return results

    def cancel(self, submission_id: str) -> None:
        """Cancels a held (FUTURERELEASE) submission by setting its undoStatus to 'canceled' — the only mutable property per RFC 8621 §7.5."""

        from suite.mail.jmap import get_jmap_set_error_message

        response = self._update({submission_id: {"undoStatus": "canceled"}})

        result = {}
        if method_responses := response.get("methodResponses"):
            result = method_responses[0][1]

        if submission_id not in (result.get("updated") or {}):
            raise ValueError(get_jmap_set_error_message(result, "notUpdated", submission_id))

    def destroy(self, submission_id: str) -> None:
        """Destroys a submission object (its record, not the message) — used to drop a finalized
        delivery from the Outbox listing."""

        from suite.mail.jmap import get_jmap_set_error_message

        response = self._delete([submission_id])

        result = {}
        if method_responses := response.get("methodResponses"):
            result = method_responses[0][1]

        if submission_id not in (result.get("destroyed") or []):
            raise ValueError(get_jmap_set_error_message(result, "notDestroyed", submission_id))

    def resubmit(
        self,
        email_id: str,
        from_email: str,
        rcpt_emails: list[str],
        envelope_id: str,
        priority: int = 0,
        hold_until: int | None = None,
    ) -> dict:
        """Creates a new submission for an already-stored email (reschedule / send-now: the old
        submission must be canceled first, since undoStatus is the only mutable property).

        Returns the created object; its echoed undoStatus is unreliable (Stalwart echoes "final"
        for held submissions) — use `get` for the real state.
        """

        from suite.mail.jmap import get_jmap_set_error_message

        identity_service = IdentityService(self.account, self.connection)
        identity_id = identity_service.get_identity_id_by_email(from_email, raise_exception=True)

        submit_ref = f"submit-{envelope_id}"
        # Not self._create — this service overrides it as the batch-compose hook used by
        # EmailService.create; go straight to the generic 'set' primitive instead.
        response = self._exec(
            "set",
            create={
                submit_ref: {
                    "identityId": identity_id,
                    "emailId": email_id,
                    "envelope": self._build_envelope(
                        from_email, rcpt_emails, envelope_id, priority, hold_until
                    ),
                }
            },
        )

        result = {}
        if method_responses := response.get("methodResponses"):
            result = method_responses[0][1]

        created = (result.get("created") or {}).get(submit_ref)
        if not created:
            raise ValueError(get_jmap_set_error_message(result, "notCreated", submit_ref))

        return created

    def _create(
        self, emails: list[EmailCreateModel], draft_refs: dict[str, str], call_id_gen: CallIdGenerator
    ) -> list:
        """Creates email submissions for the given list of EmailCreateModel instances and returns the method calls for the JMAP request."""

        method_calls = []

        identity_service = IdentityService(self.account, self.connection)
        mailbox_service = MailboxService(self.account, self.connection)

        draft_mailbox_id = mailbox_service.get_mailbox_id_by_role(
            "drafts", create_if_not_exists=True, raise_exception=True
        )
        sent_mailbox_id = mailbox_service.get_mailbox_id_by_role(
            "sent", create_if_not_exists=True, raise_exception=True
        )

        create_payload = {}
        on_success_update = {}
        on_success_destroy = []

        for email in emails:
            if email.save_as_draft:
                continue

            # -----------------------------
            # Get Identity
            # -----------------------------

            identity_id = identity_service.get_identity_id_by_email(email.from_email, raise_exception=True)

            # -----------------------------
            # CREATE Submission
            # -----------------------------

            draft_ref = draft_refs[email.creation_id]
            submit_ref = f"submit-{email.creation_id}"

            create_payload[submit_ref] = {
                "identityId": identity_id,
                "emailId": f"#{draft_ref}",
                "envelope": self._build_envelope(
                    from_email=email.from_email,
                    rcpt_emails={r.email for r in email.recipients},
                    envelope_id=email.creation_id,
                    priority=email.priority,
                    hold_until=email.hold_until,
                ),
            }

            # -----------------------------
            # Success Handlers
            # -----------------------------

            if email.destroy_after_submit:
                # No Mailbox updates, just destroy the draft email after successful submission.
                on_success_destroy.append(f"#{submit_ref}")

            else:
                # Move the draft email to the Sent mailbox and update keywords after successful submission.
                on_success_update[f"#{submit_ref}"] = {
                    f"mailboxIds/{draft_mailbox_id}": None,
                    f"mailboxIds/{sent_mailbox_id}": True,
                    "keywords/$draft": None,
                    "keywords/$seen": True,
                }

            # -----------------------------
            # Forward / Reply Keywords
            # -----------------------------

            for target_id, keyword in [
                (email.forwarded_id, "$forwarded"),
                (email.reply_to_id, "$answered"),
            ]:
                if target_id:
                    on_success_update.setdefault(target_id, {})[f"keywords/{keyword}"] = True

        if create_payload:
            payload = {
                "accountId": self.account,
                "create": create_payload,
            }

            if on_success_update:
                payload["onSuccessUpdateEmail"] = on_success_update

            if on_success_destroy:
                payload["onSuccessDestroyEmail"] = on_success_destroy

            method_calls.append(["EmailSubmission/set", payload, call_id_gen.next()])

        return method_calls
