"""Reversible policy correction; all existing reminder and notification history is preserved."""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261103_0070"
down_revision = "20261102_0069"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "reminder_policies", sa.Column("pre_customer_routing_config", sa.Text(), nullable=True)
    )
    policies = sa.table(
        "reminder_policies",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("config", sa.Text),
        sa.column("updated_at", sa.DateTime),
        sa.column("pre_customer_routing_config", sa.Text),
    )
    bind = op.get_bind()
    rows = (
        bind.execute(sa.select(policies.c.id, policies.c.kind, policies.c.config)).mappings().all()
    )
    for row in rows:
        config = json.loads(row["config"])
        if row["kind"] == "VISIT":
            config["enabled"] = False
        else:
            for field in (
                "maxNearbyResults",
                "notifyCustomer",
                "deliveryCountsAsVisit",
                "activityBasis",
                "orderStatuses",
            ):
                config.pop(field, None)
            if row["kind"] == "PROXIMITY":
                config["days"] = 0
                config["staffUserIds"] = []
                config["title"] = "Delivery partner nearby"
                config["customerTemplate"] = (
                    "Hello {customer_name}, a delivery partner from {merchant_name} is near your location. Need a refill? Open the app to place an order."
                )
            elif row["kind"] == "INACTIVE" and config.get("customerTemplate", "").startswith(
                "Hello {customer_name}, ready for your next refill?"
            ):
                config["customerTemplate"] = (
                    "Hello {customer_name}, you have not placed an order for {days} days. Open the app whenever you need your next refill."
                )
        bind.execute(
            policies.update()
            .where(policies.c.id == row["id"])
            .values(
                config=json.dumps(config),
                pre_customer_routing_config=row["config"],
                updated_at=datetime.now(UTC),
            )
        )


def downgrade():
    policies = sa.table(
        "reminder_policies",
        sa.column("id", sa.String),
        sa.column("config", sa.Text),
        sa.column("pre_customer_routing_config", sa.Text),
    )
    bind = op.get_bind()
    for row in (
        bind.execute(
            sa.select(policies.c.id, policies.c.pre_customer_routing_config).where(
                policies.c.pre_customer_routing_config.is_not(None)
            )
        )
        .mappings()
        .all()
    ):
        bind.execute(
            policies.update()
            .where(policies.c.id == row["id"])
            .values(config=row["pre_customer_routing_config"])
        )
    op.drop_column("reminder_policies", "pre_customer_routing_config")
