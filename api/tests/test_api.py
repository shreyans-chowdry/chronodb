import os
import pytest
from fastapi.testclient import TestClient
from api.main import app

@pytest.fixture(scope="session", autouse=True)
def clean_db():
    for f in ("api_test.db", "api_test.db.wal"):
        if os.path.exists(f):
            os.remove(f)
    yield
    from api.dependencies import reset_engine
    reset_engine()
    for f in ("api_test.db", "api_test.db.wal"):
        if os.path.exists(f):
            os.remove(f)

client = TestClient(app)

def test_create_branch():
    response = client.post("/branches", json={"name": "test-branch", "source_branch": "main"})
    assert response.status_code == 200
    assert response.json()["name"] == "test-branch"
    
def test_create_branch_failure():
    response = client.post("/branches", json={"source_branch": "main"})
    assert response.status_code == 422
    assert "error" in response.json()

def test_list_branches():
    response = client.get("/branches")
    assert response.status_code == 200
    assert "branches" in response.json()

def test_checkout_branch():
    response = client.post("/branches/main/checkout")
    assert response.status_code == 200
    assert "checked_out_branch" in response.json()

def test_checkout_branch_failure():
    response = client.post("/branches/non-existent/checkout")
    assert response.status_code == 404
    assert "error" in response.json()

def test_create_commit():
    response = client.post("/commits", json={
        "branch_name": "main",
        "message": "Initial commit",
        "author": "Test Author",
        "changes": [{"action": "insert", "table_name": "users", "row_id": "1", "data": {"id": 1, "name": "Alice"}}]
    })
    if response.status_code != 200:
        print("CREATE COMMIT FAILED:", response.json())
    assert response.status_code == 200
    assert "hash" in response.json()
    
def test_create_commit_failure():
    response = client.post("/commits", json={
        "branch_name": "main"
    })
    assert response.status_code == 422
    assert "error" in response.json()

def test_get_commits():
    response = client.get("/commits")
    assert response.status_code == 200
    assert "commits" in response.json()

def test_rollback_commit_failure():
    response = client.post("/rollback/abc", json={
        "branch_name": "main",
        "target_commit_hash": "def",
        "author": "Test Author"
    })
    assert response.status_code == 400
    assert "error" in response.json()

def test_query():
    response = client.post("/query", json={
        "query": "SELECT * FROM users",
        "branch_name": "main"
    })
    if response.status_code != 400:
        print("QUERY FAILED:", response.json())
    assert response.status_code == 400
    assert "error" in response.json()

def test_get_table_failure():
    response = client.get("/tables/users")
    assert response.status_code == 422
    assert "error" in response.json()


# ── Tests for new dashboard endpoints ──

def test_list_tables():
    """GET /tables should return a list of table names on the given branch."""
    response = client.get("/tables", params={"branch_name": "main"})
    assert response.status_code == 200
    data = response.json()
    assert "tables" in data
    assert isinstance(data["tables"], list)
    # We inserted a row into 'users' in test_create_commit
    assert "users" in data["tables"]

def test_list_tables_default_branch():
    """GET /tables without branch_name should default to main."""
    response = client.get("/tables")
    assert response.status_code == 200
    assert "tables" in response.json()

def test_list_tables_nonexistent_branch():
    """GET /tables with non-existent branch should return 404."""
    response = client.get("/tables", params={"branch_name": "no-such-branch"})
    assert response.status_code == 404
    assert "error" in response.json()

def test_get_data():
    """GET /data/{table} should return rows for the table on the branch."""
    response = client.get("/data/users", params={"branch_name": "main"})
    assert response.status_code == 200
    data = response.json()
    assert "rows" in data
    assert isinstance(data["rows"], list)
    assert len(data["rows"]) >= 1
    # Verify the data matches what we inserted
    row = data["rows"][0]
    assert row["name"] == "Alice"

def test_get_data_empty_table():
    """GET /data/{table} for a non-existent table should return empty rows."""
    response = client.get("/data/nonexistent", params={"branch_name": "main"})
    assert response.status_code == 200
    data = response.json()
    assert "rows" in data
    assert data["rows"] == []

def test_get_data_nonexistent_branch():
    """GET /data/{table} with non-existent branch should return 404."""
    response = client.get("/data/users", params={"branch_name": "no-such-branch"})
    assert response.status_code == 404
    assert "error" in response.json()


# ── Endpoints added in the 2.0 API ──

def test_sql_endpoint_commits_once():
    r = client.post("/api/sql", json={"sql": "INSERT INTO pets (id, name) VALUES (1, 'Rex'), (2, 'Tom'); SELECT COUNT(*) AS n FROM pets",
                                      "branch_name": "main", "author": "tester"})
    assert r.status_code == 200
    body = r.json()
    assert body["commit"] is not None and body["changes"] == 2
    assert body["results"][1]["rows"] == [{"n": 2}]


def test_sql_syntax_error_is_400():
    r = client.post("/api/sql", json={"sql": "SELEC * FROM pets"})
    assert r.status_code == 400
    assert "Syntax error" in r.json()["error"]["message"]


def test_compare_and_merge_preview():
    client.post("/api/branches", json={"name": "cmp-branch", "source_branch": "main"})
    client.post("/api/sql", json={"sql": "UPDATE pets SET name = 'Max' WHERE id = 1", "branch_name": "cmp-branch"})
    r = client.get("/api/compare", params={"base": "main", "head": "cmp-branch"})
    assert r.status_code == 200
    body = r.json()
    assert body["merge_preview"]["strategy"] == "fast-forward"
    assert body["diff"]["tables"]["pets"]["rows"][0]["changed_fields"] == ["name"]


def test_commit_detail_row_history_and_stats():
    log = client.get("/api/commits", params={"branch_name": "main", "mode": "log", "limit": 5}).json()
    head = log["commits"][0]["hash"]
    detail = client.get(f"/api/commits/{head}").json()
    assert "changes" in detail and detail["hash"] == head
    hist = client.get("/api/rows/pets/1/history", params={"ref": "cmp-branch"}).json()["history"]
    assert [h["data"]["name"] for h in hist] == ["Max", "Rex"]
    stats = client.get("/api/stats").json()
    assert stats["commits"] >= 3 and "storage" in stats


def test_maintenance_endpoints():
    assert client.post("/api/maintenance/optimize", json={"cold_threshold": 1}).status_code == 200
    assert client.delete("/api/branches/cmp-branch").status_code == 200
    gc = client.post("/api/maintenance/gc").json()
    assert "commits_removed" in gc
