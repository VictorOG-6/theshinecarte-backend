"""append _bundle suffix to bundle slugs

Revision ID: a1b2c3d4e5f6
Revises: 9c2f6d7a1b40
Create Date: 2026-10-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9c2f6d7a1b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute(
        """
        UPDATE bundle
        SET slug = slug || '_bundle'
        WHERE slug !~ '_bundle$'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE bundle
        SET slug = regexp_replace(slug, '_bundle$', '')
        WHERE slug ~ '_bundle$'
        """
    )
