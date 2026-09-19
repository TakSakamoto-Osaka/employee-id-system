import time

from .conftest import auth_headers


def test_batch_create_and_process(client, seed_companies):
    headers = {**auth_headers(roles=["CENTRAL_ADMIN"]), "Idempotency-Key": "batch-1"}
    payload = {
        "employees": [
            {
                "client_record_id": "row-0001",
                "english_name": "TARO YAMADA",
                "date_of_birth": "1990-04-15",
                "existing_employee_number": "000123",
                "company_code": "JP001",
                "organization_code": "SALES01",
                "job_title": "Manager",
            },
            {
                "client_record_id": "row-0002",
                "english_name": "JANE SMITH",
                "date_of_birth": "1985-11-02",
                "company_code": "JP001",
            },
        ]
    }
    resp = client.post("/api/v1/employee-batches", json=payload, headers=headers)
    assert resp.status_code == 202
    batch_id = resp.json()["batch_id"]
    assert resp.json()["total_count"] == 2

    # BackgroundTasks in TestClient run synchronously within the request/response
    # cycle (Starlette executes them after the response is built, before it's
    # sent back through TestClient), so results should already be available.
    for _ in range(20):
        status = client.get(f"/api/v1/employee-batches/{batch_id}", headers=headers).json()
        if status["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED"
    assert status["created_count"] == 2

    results = client.get(f"/api/v1/employee-batches/{batch_id}/results", headers=headers).json()
    statuses = {item["client_record_id"]: item["status"] for item in results["items"]}
    assert statuses["row-0001"] == "CREATED"
    assert statuses["row-0002"] == "CREATED"


def test_batch_duplicate_client_record_id_rejected(client, seed_companies):
    headers = {**auth_headers(roles=["CENTRAL_ADMIN"]), "Idempotency-Key": "batch-dup"}
    payload = {
        "employees": [
            {"client_record_id": "row-1", "english_name": "A", "date_of_birth": "1990-01-01", "company_code": "JP001"},
            {"client_record_id": "row-1", "english_name": "B", "date_of_birth": "1991-01-01", "company_code": "JP001"},
        ]
    }
    resp = client.post("/api/v1/employee-batches", json=payload, headers=headers)
    assert resp.status_code == 422
