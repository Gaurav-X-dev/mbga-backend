"""Mark the document a re-upload replaced, instead of leaving two live ones.

A rejected customer uploads a fresh scan. Until now both rows sat on the customer with nothing
saying which one was current: the review screen listed them side by side, approval marked both
`APPROVED` - including the scan the merchant had turned down - and a verification could be done
against either. The client's requirement is the obvious one: the newest upload is the document,
and the older ones are history.

Two columns rather than a flag, because "when" and "by what" are both worth keeping. A
superseded row is never deleted: it is the evidence of what was submitted and when, which is
the whole reason a document trail exists.

Backfilled: where a customer already has more than one finalized document of the same type,
every one but the newest is marked superseded by the newest, as though the rule had been in
place when they were uploaded. Nothing is thrown away, and a customer with one of each - which
is almost all of them - is untouched.

Revision ID: 20261008_0034
Revises: 20261008_0033
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0034"
down_revision = "20261008_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_documents",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "customer_documents", sa.Column("superseded_by_file_id", sa.String(80), nullable=True)
    )
    op.create_index(
        "ix_customer_documents_current",
        "customer_documents",
        ["customer_id", "document_type", "superseded_at"],
    )

    # The newest finalized upload per (customer, type) wins; everything older points at it.
    # `submitted_at` with `id` as the tiebreaker, so two uploads in the same second still
    # produce one winner rather than marking each other superseded.
    op.execute(
        sa.text(
            """
            UPDATE customer_documents d
              JOIN (
                    SELECT c.id AS winner_id, c.file_id AS winner_file_id,
                           c.customer_id, c.document_type
                      FROM customer_documents c
                      JOIN (
                            SELECT customer_id, document_type,
                                   MAX(CONCAT(UNIX_TIMESTAMP(submitted_at), '#', id)) AS newest
                              FROM customer_documents
                             WHERE customer_id IS NOT NULL AND finalized_at IS NOT NULL
                             GROUP BY customer_id, document_type
                           ) pick
                        ON pick.customer_id = c.customer_id
                       AND pick.document_type = c.document_type
                       AND CONCAT(UNIX_TIMESTAMP(c.submitted_at), '#', c.id) = pick.newest
                   ) w
                ON w.customer_id = d.customer_id
               AND w.document_type = d.document_type
               SET d.superseded_at = d.submitted_at,
                   d.superseded_by_file_id = w.winner_file_id
             WHERE d.customer_id IS NOT NULL
               AND d.finalized_at IS NOT NULL
               AND d.id <> w.winner_id
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_customer_documents_current", table_name="customer_documents")
    op.drop_column("customer_documents", "superseded_by_file_id")
    op.drop_column("customer_documents", "superseded_at")
