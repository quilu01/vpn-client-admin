from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260530_0002"
down_revision = "20260530_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vpn_clients", sa.Column("xui_inbound_ids", sa.Text(), nullable=True))
    op.execute("update vpn_clients set xui_inbound_ids = cast(xui_inbound_id as text)")


def downgrade() -> None:
    op.drop_column("vpn_clients", "xui_inbound_ids")

