import os
from pathlib import Path

import pytest

os.environ["STORE_DB_PATH"] = str(Path(__file__).resolve().parents[1] / ".test_store_intelligence.db")

from app.database import get_db, init_db


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with get_db() as conn:
        conn.execute("DELETE FROM events")
        conn.commit()
    yield
    with get_db() as conn:
        conn.execute("DELETE FROM events")
        conn.commit()
