import os
import pytest
from fastapi.testclient import TestClient
from api.main import app

@pytest.fixture(scope="session", autouse=True)
def clean_db():
    if os.path.exists("api_test.db"):
        os.remove("api_test.db")
    yield
    if os.path.exists("api_test.db"):
        os.remove("api_test.db")

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
