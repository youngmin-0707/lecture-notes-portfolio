"""seed default glossary terms

Revision ID: 0d2fdadd5067
Revises: 95fe71ea472f
Create Date: 2026-08-22 18:35:19.072168

빈 용어집은 아무도 채우지 않아 기능이 죽는다 (§3.3, T-22 DoD "초기 마이그레이션 시 기본
용어집이 채워짐"). `app.glossary.default_terms`의 100개 시드를 `glossary_terms`에 삽입한다.

ORM 모델(`app.models.glossary.GlossaryTerm`)을 직접 쓰지 않고 얕은 `sa.table` 정의로
`bulk_insert`한다 — 마이그레이션이 미래 시점의 모델 변경에 영향받지 않게 하는 Alembic 관용
패턴이다. 시드 "데이터" 자체(`DEFAULT_GLOSSARY_TERMS`)는 정적 상수이므로 애플리케이션 코드와
공유해도 안전하다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.glossary.default_terms import DEFAULT_GLOSSARY_TERMS

# revision identifiers, used by Alembic.
revision: str = "0d2fdadd5067"
down_revision: str | Sequence[str] | None = "95fe71ea472f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

glossary_terms_table = sa.table(
    "glossary_terms",
    sa.column("term", sa.String),
    sa.column("aliases", sa.JSON),
    sa.column("course", sa.String),
)


def upgrade() -> None:
    op.bulk_insert(
        glossary_terms_table,
        [
            {"term": row["term"], "aliases": row["aliases"], "course": row["course"]}
            for row in DEFAULT_GLOSSARY_TERMS
        ],
    )


def downgrade() -> None:
    seed_terms = [row["term"] for row in DEFAULT_GLOSSARY_TERMS]
    conn = op.get_bind()
    conn.execute(glossary_terms_table.delete().where(glossary_terms_table.c.term.in_(seed_terms)))
