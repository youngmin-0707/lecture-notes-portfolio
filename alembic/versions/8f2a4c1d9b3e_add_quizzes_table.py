"""add quizzes table

Revision ID: 8f2a4c1d9b3e
Revises: f0db8c3cc4cc
Create Date: 2026-09-01 00:00:00.000000

`summaries`와 동일한 "세션당 N건, 최신 1건만 API로 노출" 관례를 따른다 (2026-09-01,
복습 문제 자동 생성 기능). `status`는 세션 상태(§2.3 `sessions.status`)와 별개 축으로,
LLM 호출 1회를 수반하는 생성 자체의 진행 상태(GENERATING/DONE/FAILED)를 추적한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2a4c1d9b3e"
down_revision: str | Sequence[str] | None = "f0db8c3cc4cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quizzes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_model", sa.String(length=100), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quizzes_session_id", "quizzes", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_quizzes_session_id", table_name="quizzes")
    op.drop_table("quizzes")
