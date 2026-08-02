from engine.src.version.engine import VersionEngine

async def get_engine():
    engine = VersionEngine(db_path="api_test.db")
    try:
        yield engine
    finally:
        engine.close()
