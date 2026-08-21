import os
import tempfile

import pytest


os.environ["IOSMAX_DATA_DIR"] = tempfile.mkdtemp(prefix="iosmax-tests-")
os.environ["IOSMAX_ADMIN_USERNAME"] = "admin"
os.environ["IOSMAX_ADMIN_PASSWORD"] = "TestPassword123!"
os.environ["IOSMAX_INJECTION_DEMO"] = "true"


@pytest.fixture(autouse=True)
def reset_database():
    from app.database import Base, SessionLocal, engine
    from app.security import seed_admin

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_admin(db)
    yield
