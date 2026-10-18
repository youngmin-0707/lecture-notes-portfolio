"""create sessions transcripts summaries glossary_terms tables

Revision ID: 95fe71ea472f
Revises:
Create Date: 2026-08-22 11:58:33.296771

dialect 중립 규칙 (§2.3): postgresql.UUID/JSONB/네이티브 ENUM/TIMESTAMPTZ 의존을 쓰지 않고
String(36)/JSON/String(20)/DateTime(timezone=True)만 사용한다. SQLite와 PostgreSQL 양쪽에서
`alembic upgrade head` / `alembic downgrade base`가 성공해야 한다 (T-04 DoD).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95fe71ea472f"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("course", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("audio_path", sa.String(512), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_recorded_at", "sessions", ["recorded_at"])
    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_course", "sessions", ["course"])

    op.create_table(
        "transcripts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("text_raw", sa.Text, nullable=False),
        sa.Column("text_corrected", sa.Text, nullable=True),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_model", sa.String(100), nullable=False),
        sa.Column("elapsed_seconds", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "transcript_id",
            sa.String(36),
            sa.ForeignKey("transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("start_seconds", sa.Float, nullable=False),
        sa.Column("end_seconds", sa.Float, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.UniqueConstraint("transcript_id", "seq", name="uq_transcript_segment_seq"),
    )

    op.create_table(
        "summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_markdown", sa.Text, nullable=False),
        sa.Column("key_points", sa.JSON, nullable=False),
        sa.Column("concepts", sa.JSON, nullable=False),
        sa.Column("code_snippets", sa.JSON, nullable=False),
        sa.Column("action_items", sa.JSON, nullable=False),
        sa.Column("keywords", sa.JSON, nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("term", sa.String(100), nullable=False),
        sa.Column("aliases", sa.JSON, nullable=False),
        sa.Column("course", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("glossary_terms")
    op.drop_table("summaries")
    op.drop_table("transcript_segments")
    op.drop_table("transcripts")
    op.drop_index("ix_sessions_course", table_name="sessions")
    op.drop_index("ix_sessions_status", table_name="sessions")
    op.drop_index("ix_sessions_recorded_at", table_name="sessions")
    op.drop_table("sessions")
