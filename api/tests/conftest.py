"""
Test isolation for the API suite.

The running app reads its database from CHRONODB_PATH (default: api_test.db,
the seeded demo database the dashboard uses). Tests must never touch that
file, so CHRONODB_PATH is pointed at a throwaway file in a temp directory
before api.main is imported by any test module.
"""

import os
import shutil
import tempfile

import pytest

_TEST_DIR = tempfile.mkdtemp(prefix="chronodb-api-tests-")
TEST_DB_PATH = os.path.join(_TEST_DIR, "api_tests.db")
os.environ["CHRONODB_PATH"] = TEST_DB_PATH


@pytest.fixture(scope="session", autouse=True)
def isolated_db():
    from api.dependencies import reset_engine

    reset_engine()
    yield TEST_DB_PATH
    reset_engine()
    shutil.rmtree(_TEST_DIR, ignore_errors=True)
