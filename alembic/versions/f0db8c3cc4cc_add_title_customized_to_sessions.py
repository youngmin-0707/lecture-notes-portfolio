"""add title_customized to sessions

Revision ID: f0db8c3cc4cc
Revises: c6691b026114
Create Date: 2026-08-30 17:17:26.284229

기존 세션이 이미 있는 상태에서 NOT NULL 컬럼을 추가하는 것이라 `server_default`가 필요하다
(그렇지 않으면 SQLite가 거부한다). 기존 세션은 전부 제목을 수동으로 바꾼 적이 없다고 보는
게 안전하므로(실제로는 몰라도, False로 잡아야 다음 재요약 때 자동 제목 갱신 혜택을 받는다)
`False`로 채운다. 이후 신규 삽입은 ORM 레벨 기본값이 맡으므로 server_default는 이
마이그레이션 한 번만 필요하고, 업그레이드 직후 제거한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0db8c3cc4cc"
down_revision: str | Sequence[str] | None = "c6691b026114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("title_customized", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.alter_column("title_customized", server_default=None)


def downgrade() -> None:
    op.drop_column("sessions", "title_customized")
