"""Dynamic reminder policies, follow-ups, customer visits and price reviews."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261102_0069"
down_revision = "20261102_0068"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reminder_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scope", "kind", name="uq_reminder_policy_scope_kind"),
    )
    op.create_table(
        "automated_reminders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=True
        ),
        sa.Column("site_id", sa.String(36), nullable=True),
        sa.Column("assigned_user_id", sa.String(36), nullable=True),
        sa.Column("subject", sa.String(180), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fingerprint", name="uq_automated_reminder_fingerprint"),
    )
    op.create_index(
        "ix_automated_reminder_scope_status",
        "automated_reminders",
        ["merchant_id", "status", "updated_at"],
    )
    op.create_table(
        "customer_visits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column(
            "customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False
        ),
        sa.Column("site_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=True),
        sa.Column("accuracy", sa.Numeric(10, 2), nullable=True),
        sa.Column("verification", sa.String(30), nullable=False),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "idempotency_key", name="uq_customer_visit_key"),
    )
    op.create_index(
        "ix_customer_visit_latest", "customer_visits", ["merchant_id", "customer_id", "visited_at"]
    )
    op.create_table(
        "pricing_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pricing_review_period", "pricing_reviews", ["merchant_id", "month", "reviewed_at"]
    )
    table = sa.table(
        "reminder_policies",
        sa.column("id", sa.String),
        sa.column("scope", sa.String),
        sa.column("kind", sa.String),
        sa.column("config", sa.Text),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(table, SEEDS)


def downgrade():
    for table in ["pricing_reviews", "customer_visits", "automated_reminders", "reminder_policies"]:
        op.drop_table(table)


SEEDS = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "scope": "platform",
        "kind": "PROXIMITY",
        "config": '{"enabled":false,"allowMerchantOverride":false,"days":30,"radiusMeters":5000,"maxLocationAgeSeconds":300,"maxAccuracyMeters":100,"maxNearbyResults":5,"intervalHours":24,"maxCount":3,"maxSnoozeHours":168,"notificationTtlHours":24,"weekdays":[0,1,2,3,4,5,6],"startHour":8,"endHour":21,"pushEnabled":true,"notifyCustomer":false,"includeNeverOrdered":false,"suppressActiveOrders":true,"deliveryCountsAsVisit":false,"activityBasis":"ORDER","orderStatuses":["CONFIRMED","DELIVERED"],"customerTypes":[],"groupIds":[],"staffUserIds":[],"upcomingDays":3,"missingRates":true,"staleReview":true,"title":"Nearby customer follow-up","staffTemplate":"{customer_name} is {distance_km} km away. {reason}","customerTemplate":"Hello {customer_name}, ready for your next refill? Open the app to order."}',
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "scope": "platform",
        "kind": "VISIT",
        "config": '{"enabled":false,"allowMerchantOverride":false,"days":30,"radiusMeters":5000,"maxLocationAgeSeconds":300,"maxAccuracyMeters":100,"maxNearbyResults":5,"intervalHours":24,"maxCount":3,"maxSnoozeHours":168,"notificationTtlHours":24,"weekdays":[0,1,2,3,4,5,6],"startHour":8,"endHour":21,"pushEnabled":true,"notifyCustomer":false,"includeNeverOrdered":false,"suppressActiveOrders":true,"deliveryCountsAsVisit":false,"activityBasis":"ORDER","orderStatuses":["CONFIRMED","DELIVERED"],"customerTypes":[],"groupIds":[],"staffUserIds":[],"upcomingDays":3,"missingRates":true,"staleReview":true,"title":"Customer visit due","staffTemplate":"{customer_name}: {reason}","customerTemplate":"Hello {customer_name}, ready for your next refill? Open the app to order."}',
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "scope": "platform",
        "kind": "INACTIVE",
        "config": '{"enabled":false,"allowMerchantOverride":false,"days":30,"radiusMeters":5000,"maxLocationAgeSeconds":300,"maxAccuracyMeters":100,"maxNearbyResults":5,"intervalHours":24,"maxCount":3,"maxSnoozeHours":168,"notificationTtlHours":24,"weekdays":[0,1,2,3,4,5,6],"startHour":8,"endHour":21,"pushEnabled":true,"notifyCustomer":false,"includeNeverOrdered":false,"suppressActiveOrders":true,"deliveryCountsAsVisit":false,"activityBasis":"ORDER","orderStatuses":["CONFIRMED","DELIVERED"],"customerTypes":[],"groupIds":[],"staffUserIds":[],"upcomingDays":3,"missingRates":true,"staleReview":true,"title":"Inactive customer follow-up","staffTemplate":"{customer_name}: {reason}","customerTemplate":"Hello {customer_name}, ready for your next refill? Open the app to order."}',
    },
    {
        "id": "00000000-0000-4000-8000-000000000004",
        "scope": "platform",
        "kind": "PRICING",
        "config": '{"enabled":false,"allowMerchantOverride":false,"days":30,"radiusMeters":5000,"maxLocationAgeSeconds":300,"maxAccuracyMeters":100,"maxNearbyResults":5,"intervalHours":24,"maxCount":3,"maxSnoozeHours":168,"notificationTtlHours":24,"weekdays":[0,1,2,3,4,5,6],"startHour":8,"endHour":21,"pushEnabled":true,"notifyCustomer":false,"includeNeverOrdered":false,"suppressActiveOrders":true,"deliveryCountsAsVisit":false,"activityBasis":"ORDER","orderStatuses":["CONFIRMED","DELIVERED"],"customerTypes":[],"groupIds":[],"staffUserIds":[],"upcomingDays":3,"missingRates":true,"staleReview":true,"title":"Pricing review due","staffTemplate":"{merchant_name}, {month}: {reason}","customerTemplate":"Hello {customer_name}, ready for your next refill? Open the app to order."}',
    },
]
for row in SEEDS:
    row["updated_at"] = datetime(2026, 11, 2, tzinfo=UTC)
