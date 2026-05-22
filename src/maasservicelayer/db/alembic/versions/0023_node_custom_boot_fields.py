# Copyright 2026 Canonical Ltd. This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""node_custom_boot_fields

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-22 00:00:00+00:00

"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "maasserver_node",
        sa.Column("custom_bootloader", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "maasserver_node",
        sa.Column("custom_kernel", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "maasserver_node",
        sa.Column(
            "custom_kernel_kflavor",
            sa.String(length=32),
            nullable=True,
            server_default="generic",
        ),
    )


def downgrade() -> None:
    # We do not support migration downgrade
    pass
