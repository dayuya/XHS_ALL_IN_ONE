"""Store per-account note snapshots and synchronization results."""
from alembic import op
import sqlalchemy as sa

revision = "ab30a1100030"
down_revision = "60cd5c95fde1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_key", sa.String(160), nullable=False),
        sa.Column("note_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=False),
        sa.Column("note_url", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("platform_status", sa.String(256), nullable=False),
        sa.Column("platform_status_code", sa.String(32), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("collects", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("in_latest_sync", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "account_key", "note_id", name="uq_account_note_owner"),
    )
    op.create_index("ix_account_notes_user_id", "account_notes", ["user_id"])
    op.create_index("ix_account_notes_account_key", "account_notes", ["account_key"])
    op.create_table(
        "account_note_syncs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("message", sa.String(512), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "account_key", name="uq_account_note_sync_owner"),
    )
    op.create_index("ix_account_note_syncs_user_id", "account_note_syncs", ["user_id"])
    op.create_index("ix_account_note_syncs_account_key", "account_note_syncs", ["account_key"])


def downgrade():
    op.drop_table("account_note_syncs")
    op.drop_table("account_notes")
