"""add_in_progress_and_paused_status

Revision ID: b52b2f413952
Revises: de52bd0bd934
Create Date: 2026-05-07 21:43:48.201969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b52b2f413952'
down_revision: Union[str, Sequence[str], None] = 'de52bd0bd934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавляем новые статусы в enum taskstatus"""
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'in_progress'")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'paused'")


def downgrade() -> None:
    """PostgreSQL не поддерживает удаление значений из ENUM.
    Для отката миграции потребуется ручное вмешательство или пересоздание типа."""
    pass