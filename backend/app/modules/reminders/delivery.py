"""Revalidate only reminder outbox rows; ordinary business notifications are untouched."""

from datetime import timedelta

from app.modules.merchants.models import Merchant
from app.modules.reminders.engine import ReminderEngine, in_window, utc
from app.modules.reminders.models import Reminder
from app.modules.reminders.policies import effective_rules


class ReminderDispatchGuard:
    def __init__(self, session):
        self.session = session
        self.cache = {}

    async def check(self, notification, now):
        reminder = await self.session.get(Reminder, notification.entity_id)
        if (
            reminder is None
            or notification.event_type.rsplit(".", 1)[-1] != str(reminder.reminder_count)
            or reminder.status in ("RESOLVED", "ACKNOWLEDGED")
        ):
            return "SKIP"
        if reminder.kind == "VISIT" or (
            reminder.kind == "PROXIMITY" and (reminder.assigned_user_id or reminder.site_id)
        ):
            return "SKIP"
        if reminder.merchant_id not in self.cache:
            merchant = await self.session.get(Merchant, reminder.merchant_id)
            if (
                merchant is None
                or merchant.status != "ACTIVE"
                or merchant.approval_status != "APPROVED"
            ):
                return "SKIP"
            rules, _, _ = await effective_rules(self.session, merchant.id)
            engine = ReminderEngine(self.session, now)
            candidates = (
                await engine.candidates(merchant, rules)
                if any(r.enabled for r in rules.values())
                else []
            )
            self.cache[merchant.id] = (
                rules,
                {c.fingerprint(merchant.id): c for c in candidates},
                engine,
                {},
            )
        rules, candidates, engine, recipients = self.cache[reminder.merchant_id]
        rule = rules[reminder.kind]
        candidate = candidates.get(reminder.fingerprint)
        if (
            not rule.enabled
            or candidate is None
            or utc(notification.created_at) + timedelta(hours=rule.notificationTtlHours) < now
        ):
            return "SKIP"
        if (
            reminder.status == "SNOOZED"
            and reminder.next_due_at
            and utc(reminder.next_due_at) > now
        ):
            return "WAIT"
        if not in_window(rule, now):
            return "WAIT"
        if notification.recipient_channel == "CUSTOMER":
            if (
                reminder.kind not in ("PROXIMITY", "INACTIVE")
                or notification.recipient_id != reminder.customer_id
            ):
                return "SKIP"
        elif notification.recipient_channel == "DELIVERY" or reminder.kind == "PROXIMITY":
            return "SKIP"
        else:
            if reminder.kind not in recipients:
                recipients[reminder.kind] = await engine.recipients(
                    reminder.merchant_id, rule, reminder.kind
                )
            if notification.recipient_id not in recipients[reminder.kind]:
                return "SKIP"
        notification.title = rule.title.format(**candidate.context)[:180]
        template = (
            rule.customerTemplate
            if notification.recipient_channel == "CUSTOMER"
            else rule.staffTemplate
        )
        notification.body = template.format(**candidate.context)
        return "SEND" if rule.pushEnabled else "IN_APP"
