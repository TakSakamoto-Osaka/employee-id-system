import io
import time

from .conftest import auth_headers

CSV_CONTENT = (
    "english_name,date_of_birth,existing_employee_number,remarks,company_code,organization_code,job_title\n"
    "TARO YAMADA,1990-04-15,000123,,JP001,SALES01,Manager\n"
    "JANE SMITH,1985-11-02,A456,Initial import,JP001,,Specialist\n"
    "BAD ROW,not-a-date,,,JP001,,\n"
)


def test_csv_upload_validate_execute(client, seed_companies):
    headers = auth_headers(roles=["CENTRAL_ADMIN"])
    files = {"file": ("employees.csv", io.BytesIO(CSV_CONTENT.encode("utf-8")), "text/csv")}
    resp = client.post("/api/v1/employee-imports", files=files, headers=headers)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    status = None
    for _ in range(20):
        status = client.get(f"/api/v1/employee-imports/{job_id}", headers=headers).json()
        if status["status"] == "READY":
            break
        time.sleep(0.05)
    assert status["status"] == "READY"
    assert status["total_count"] == 3
    assert status["error_count"] == 1  # BAD ROW has an invalid date

    exec_resp = client.post(f"/api/v1/employee-imports/{job_id}/execute", headers=headers)
    assert exec_resp.status_code == 202

    for _ in range(20):
        status = client.get(f"/api/v1/employee-imports/{job_id}", headers=headers).json()
        if status["status"] == "COMPLETED":
            break
        time.sleep(0.05)
    assert status["status"] == "COMPLETED"
    assert status["created_count"] == 2
    assert status["error_count"] == 1

    results = client.get(f"/api/v1/employee-imports/{job_id}/results", headers=headers).json()
    by_row = {r["row_number"]: r for r in results["items"]}
    assert by_row[1]["status"] == "CREATED"
    assert by_row[2]["status"] == "CREATED"
    assert by_row[3]["status"] == "ERROR"
