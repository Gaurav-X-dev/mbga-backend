from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.business_catalogue.models import CustomerTypeDefinition
from app.modules.customers.models import CustomerReportGroup
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.reminders.models import ReminderPolicy
from app.modules.reminders.schemas import Rule
from app.modules.users.models import User
from app.shared.exceptions.api_error import ApiError

KINDS = ("PROXIMITY", "INACTIVE", "PRICING")


def audit(session, user_id, entity_id, message):
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type="AUTOMATION_UPDATED",
            actor_user_id=user_id,
            entity_type="reminder",
            entity_id=entity_id,
            message=message[:255],
            created_at=datetime.now(UTC),
        )
    )


async def effective_rules(session, merchant_id=None):
    rows = (
        await session.scalars(
            select(ReminderPolicy).where(
                ReminderPolicy.scope.in_(
                    ["platform", merchant_id] if merchant_id else ["platform"]
                ),
                ReminderPolicy.kind.in_(KINDS),
            )
        )
    ).all()
    defaults = {r.kind: Rule.model_validate_json(r.config) for r in rows if r.scope == "platform"}
    if set(defaults) != set(KINDS):
        raise ApiError(
            "REMINDER_SETTINGS_MISSING",
            503,
            "Apply the reminder policy migration before using automated reminders.",
        )
    overrides = {r.kind: Rule.model_validate_json(r.config) for r in rows if r.scope != "platform"}
    return (
        {
            kind: overrides[kind]
            if kind in overrides and defaults[kind].allowMerchantOverride
            else defaults[kind]
            for kind in KINDS
        },
        defaults,
        overrides,
    )


async def policy_view(session, merchant_id=None):
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    effective, defaults, overrides = await effective_rules(session, merchant_id)
    customer_types = [
        {"value": row.code, "label": row.label}
        for row in (
            await session.scalars(
                select(CustomerTypeDefinition)
                .where(CustomerTypeDefinition.is_active.is_(True))
                .order_by(CustomerTypeDefinition.sort_order)
            )
        ).all()
    ]
    groups = []
    recipients = []
    if merchant_id:
        groups = [
            {"value": row.id, "label": row.name}
            for row in (
                await session.scalars(
                    select(CustomerReportGroup)
                    .where(
                        CustomerReportGroup.merchant_id == merchant_id,
                        CustomerReportGroup.active.is_(True),
                    )
                    .order_by(CustomerReportGroup.name)
                )
            ).all()
        ]
        staff = (
            await session.execute(
                select(User.id, User.full_name)
                .join(MerchantUser, MerchantUser.user_id == User.id)
                .where(
                    MerchantUser.merchant_id == merchant_id,
                    MerchantUser.status == "ACTIVE",
                    User.status == "ACTIVE",
                )
            )
        ).all()
        recipients = [{"value": uid, "label": name or uid} for uid, name in dict(staff).items()]
    return {
        "customerTypes": customer_types,
        "groups": groups,
        "recipients": recipients,
        "merchantId": merchant_id,
        "rules": [
            {
                "kind": kind,
                "config": effective[kind].model_dump(),
                "default": defaults[kind].model_dump(),
                "hasOverride": kind in overrides,
                "inherited": kind not in overrides or not defaults[kind].allowMerchantOverride,
            }
            for kind in KINDS
        ],
        "placeholders": [
            "customer_name",
            "merchant_name",
            "days",
            "distance_km",
            "month",
            "reason",
        ],
    }


async def save_policy(session, actor, kind, config, merchant_id=None):
    if kind not in KINDS:
        raise ApiError("RULE_NOT_FOUND", 404)
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    # Lock the platform policy before an override, matching worker and concurrent-save ordering.
    platform = await session.scalar(
        select(ReminderPolicy)
        .where(ReminderPolicy.scope == "platform", ReminderPolicy.kind == kind)
        .with_for_update()
    )
    if platform is None:
        raise ApiError("REMINDER_SETTINGS_MISSING", 503)
    default = Rule.model_validate_json(platform.config)
    if merchant_id and config is not None and not default.allowMerchantOverride:
        raise ApiError(
            "REMINDER_OVERRIDE_DISABLED",
            403,
            "Platform policy does not allow a merchant override for this rule.",
        )
    if config and kind != "PROXIMITY" and config.days < 1:
        raise ApiError(
            "INVALID_REMINDER_POLICY",
            422,
            "Days must be at least one for inactivity and pricing reminders.",
        )
    if config and kind == "PROXIMITY":
        config.staffUserIds = []
    if config:
        types = set(
            (
                await session.scalars(
                    select(CustomerTypeDefinition.code).where(
                        CustomerTypeDefinition.is_active.is_(True)
                    )
                )
            ).all()
        )
        if not set(config.customerTypes) <= types:
            raise ApiError(
                "INVALID_REMINDER_POLICY",
                422,
                "Choose active customer types from the business catalogue.",
            )
    if config and merchant_id:
        if config.allowMerchantOverride != default.allowMerchantOverride:
            raise ApiError(
                "INVALID_REMINDER_POLICY",
                422,
                "Only Admin platform settings may change override authority.",
            )
        groups = set(
            (
                await session.scalars(
                    select(CustomerReportGroup.id).where(
                        CustomerReportGroup.merchant_id == merchant_id
                    )
                )
            ).all()
        )
        if not set(config.groupIds) <= groups:
            raise ApiError("GROUP_NOT_FOUND", 404, "Choose groups belonging to this merchant.")
        staff = set(
            (
                await session.scalars(
                    select(MerchantUser.user_id).where(
                        MerchantUser.merchant_id == merchant_id, MerchantUser.status == "ACTIVE"
                    )
                )
            ).all()
        )
        if not set(config.staffUserIds) <= staff:
            raise ApiError(
                "RECIPIENT_NOT_FOUND", 404, "Choose active users belonging to this merchant."
            )
    if not merchant_id and config and (config.groupIds or config.staffUserIds):
        raise ApiError(
            "INVALID_REMINDER_POLICY",
            422,
            "Customer groups and selected recipients require a merchant-specific policy.",
        )
    scope = merchant_id or "platform"
    row = (
        platform
        if not merchant_id
        else await session.scalar(
            select(ReminderPolicy)
            .where(ReminderPolicy.scope == scope, ReminderPolicy.kind == kind)
            .with_for_update()
        )
    )
    if config is None:
        if not merchant_id:
            raise ApiError("INVALID_REMINDER_POLICY", 422, "Platform rules cannot be removed.")
        if row:
            await session.delete(row)
    else:
        if row is None:
            row = ReminderPolicy(id=str(uuid4()), scope=scope, kind=kind)
            session.add(row)
        row.config = config.model_dump_json()
        row.updated_by, row.updated_at = actor.user_id, datetime.now(UTC)
    audit(
        session,
        actor.user_id,
        platform.id,
        f"{kind} policy saved for {scope}; enabled={config.enabled if config else 'inherit'}",
    )
    await session.commit()
    return await policy_view(session, merchant_id)
