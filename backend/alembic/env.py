from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: E402,F401  # 모든 모델을 Base.metadata에 등록
from alembic import context

# app 패키지를 import하기 위해 필요 (pyproject.toml의 pythonpath=["."]와 동일하게,
# alembic 실행 시에도 backend/ 디렉토리가 sys.path에 포함되도록 prepend_sys_path=. 설정됨).
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# DATABASE_URL 환경변수 값으로 sqlalchemy.url을 덮어쓴다 (하드코딩 금지, A-2).
# 단, 호출부(alembic.ini 또는 프로그래밍 방식 Config)가 이미 명시적으로 url을 지정했다면
# 그 값을 존중한다 (예: 테스트에서 SQLite/PostgreSQL 양쪽을 각각 검증할 때).
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
#
# `disable_existing_loggers=False`가 중요하다 — 기본값(True)이면 이 ini에 명시되지 않은
# 모든 기존 로거(예: 이미 만들어진 `app.pipeline.*` 로거들)를 영구적으로 비활성화한다.
# 테스트 스위트에서 alembic 커맨드(예: `tests/test_migrations.py`)를 실행하면 이 프로세스
# 전역 상태가 남아서, 그 이후 실행되는 다른 테스트의 `app.*` 로그가 전부 사라지는 걸
# 실측으로 확인했다 (T-28, "본문 없이 길이·소요시간은 로깅된다"는 걸 검증하려다 발견).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
