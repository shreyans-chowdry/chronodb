import os
import shutil
from engine.src.version.engine import VersionEngine

async def get_engine():
    db_path = os.environ.get("CHRONODB_PATH", "api_test.db")
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or not os.access(".", os.W_OK):
        tmp_db = "/tmp/api_test.db"
        if not os.path.exists(tmp_db):
            if os.path.exists("api_test.db"):
                shutil.copyfile("api_test.db", tmp_db)
                if os.path.exists("api_test.db.wal"):
                    shutil.copyfile("api_test.db.wal", tmp_db + ".wal")
        db_path = tmp_db

    engine = VersionEngine(db_path=db_path)
    try:
        yield engine
    finally:
        engine.close()
