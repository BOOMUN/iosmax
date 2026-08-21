from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables() -> None:
    Base.metadata.create_all(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("devices")}
    if "jailbreak_type" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE devices ADD COLUMN jailbreak_type "
                    "VARCHAR(20) NOT NULL DEFAULT 'rootless'"
                )
            )
    if "vnc_password_encrypted" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE devices ADD COLUMN vnc_password_encrypted TEXT")
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE devices SET jailbreak_type = 'rootless' "
                "WHERE jailbreak_type IS NULL "
                "OR jailbreak_type NOT IN ('rootless', 'roothide')"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_devices_jailbreak_type "
                "ON devices (jailbreak_type)"
            )
        )
