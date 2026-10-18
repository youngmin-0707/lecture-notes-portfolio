"""add detailed_notes_markdown to summaries

Revision ID: c6691b026114
Revises: 0d2fdadd5067
Create Date: 2026-08-29 16:07:16.404005

기존 `summaries` 행이 이미 있는 상태에서 NOT NULL 컬럼을 추가하는 것이라, 기존 행을 채울
`server_default=''`를 같이 준다(그렇지 않으면 SQLite가 거부한다). 이후 신규 삽입은
ORM 레벨 기본값(`app.models.summary.Summary.detailed_notes_markdown`의 `default=""`)이
맡으므로 server_default는 이 마이그레이션 한 번만 필요하고, 업그레이드 직후 제거한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6691b026114"
down_revision: str | Sequence[str] | None = "0d2fdadd5067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "summaries",
        sa.Column("detailed_notes_markdown", sa.Text(), nullable=False, server_default=""),
    )
    with op.batch_alter_table("summaries") as batch_op:
        batch_op.alter_column("detailed_notes_markdown", server_default=None)


def downgrade() -> None:
    op.drop_column("summaries", "detailed_notes_markdown")
