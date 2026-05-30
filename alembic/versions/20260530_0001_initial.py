from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260530_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vpn_clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("xui_inbound_id", sa.Integer(), nullable=False),
        sa.Column("xui_client_id", sa.String(length=64), nullable=False),
        sa.Column("xui_email", sa.String(length=160), nullable=False),
        sa.Column("xui_sub_id", sa.String(length=160), nullable=False),
        sa.Column("subscription_token_hash", sa.String(length=64), nullable=True),
        sa.Column("happ_link", sa.Text(), nullable=True),
        sa.Column("happ_encrypted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("traffic_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("traffic_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vpn_clients_display_name", "vpn_clients", ["display_name"])
    op.create_index("ix_vpn_clients_expires_at", "vpn_clients", ["expires_at"])
    op.create_index("ix_vpn_clients_status", "vpn_clients", ["status"])
    op.create_index("ix_vpn_clients_subscription_token_hash", "vpn_clients", ["subscription_token_hash"], unique=True)
    op.create_index("ix_vpn_clients_xui_client_id", "vpn_clients", ["xui_client_id"], unique=True)
    op.create_index("ix_vpn_clients_xui_email", "vpn_clients", ["xui_email"], unique=True)
    op.create_index("ix_vpn_clients_xui_sub_id", "vpn_clients", ["xui_sub_id"], unique=True)

    op.create_table(
        "traffic_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["vpn_clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_traffic_snapshots_captured_at", "traffic_snapshots", ["captured_at"])
    op.create_index("ix_traffic_snapshots_client_id", "traffic_snapshots", ["client_id"])

    op.create_table(
        "action_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["vpn_clients.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_audit_created_at", "action_audit", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_action_audit_created_at", table_name="action_audit")
    op.drop_table("action_audit")
    op.drop_index("ix_traffic_snapshots_client_id", table_name="traffic_snapshots")
    op.drop_index("ix_traffic_snapshots_captured_at", table_name="traffic_snapshots")
    op.drop_table("traffic_snapshots")
    op.drop_index("ix_vpn_clients_xui_sub_id", table_name="vpn_clients")
    op.drop_index("ix_vpn_clients_xui_email", table_name="vpn_clients")
    op.drop_index("ix_vpn_clients_xui_client_id", table_name="vpn_clients")
    op.drop_index("ix_vpn_clients_subscription_token_hash", table_name="vpn_clients")
    op.drop_index("ix_vpn_clients_status", table_name="vpn_clients")
    op.drop_index("ix_vpn_clients_expires_at", table_name="vpn_clients")
    op.drop_index("ix_vpn_clients_display_name", table_name="vpn_clients")
    op.drop_table("vpn_clients")

