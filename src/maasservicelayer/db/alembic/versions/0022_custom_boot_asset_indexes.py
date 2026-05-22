# Copyright 2026 Canonical Ltd. This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""custom_boot_asset_indexes

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-22 00:00:00+00:00

"""

from typing import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_bootresource_bootloader_identity",
        "maasserver_bootresource",
        ["name", "architecture"],
        unique=True,
        postgresql_where=text("rtype = 2 AND bootloader_type IS NOT NULL"),
    )

    op.create_index(
        "uq_bootresource_kernel_identity",
        "maasserver_bootresource",
        ["name", "architecture", "kflavor"],
        unique=True,
        postgresql_where=text(
            "rtype = 2 AND kflavor IS NOT NULL AND bootloader_type IS NULL"
        ),
    )


def downgrade() -> None:
    # We do not support migration downgrade
    pass
