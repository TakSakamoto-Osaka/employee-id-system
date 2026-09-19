from .conftest import auth_headers


def _payload(**overrides):
    base = {
        "english_name": "TARO YAMADA",
        "date_of_birth": "1990-04-15",
        "existing_employee_number": "000123",
        "remarks": "",
        "company_code": "JP001",
        "organization_code": "SALES01",
        "job_title": "Manager",
    }
    base.update(overrides)
    return base


def test_new_employee_is_created_with_valid_number(client, seed_companies):
    resp = client.post(
        "/api/v1/employees",
        json=_payload(),
        headers={**auth_headers(), "Idempotency-Key": "key-1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "CREATED"
    assert body["unified_employee_number"].startswith("E")
    assert len(body["unified_employee_number"]) == 9


def test_duplicate_registration_returns_existing_number(client, seed_companies):
    headers = auth_headers()
    r1 = client.post("/api/v1/employees", json=_payload(), headers={**headers, "Idempotency-Key": "key-a"})
    assert r1.status_code == 201
    number = r1.json()["unified_employee_number"]

    r2 = client.post("/api/v1/employees", json=_payload(), headers={**headers, "Idempotency-Key": "key-b"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "EXISTING"
    assert r2.json()["unified_employee_number"] == number


def test_same_idempotency_key_replays_response(client, seed_companies):
    headers = {**auth_headers(), "Idempotency-Key": "same-key"}
    r1 = client.post("/api/v1/employees", json=_payload(), headers=headers)
    r2 = client.post("/api/v1/employees", json=_payload(), headers=headers)
    assert r1.json() == r2.json()


def test_same_idempotency_key_different_body_conflicts(client, seed_companies):
    headers = {**auth_headers(), "Idempotency-Key": "same-key-2"}
    client.post("/api/v1/employees", json=_payload(), headers=headers)
    resp = client.post("/api/v1/employees", json=_payload(existing_employee_number="999999"), headers=headers)
    assert resp.status_code == 409


def test_name_dob_match_without_existing_number_requires_review(client, seed_companies):
    headers = auth_headers()
    r1 = client.post(
        "/api/v1/employees",
        json=_payload(existing_employee_number="000123"),
        headers={**headers, "Idempotency-Key": "k1"},
    )
    assert r1.status_code == 201

    # Same name & DOB but a different existing_employee_number -> no reliable
    # mapping, but a name/DOB candidate exists -> must go to review, not
    # silently merge or silently create a duplicate (spec 4.2 step 7).
    r2 = client.post(
        "/api/v1/employees",
        json=_payload(existing_employee_number="ZZZ999"),
        headers={**headers, "Idempotency-Key": "k2"},
    )
    assert r2.status_code == 202
    assert r2.json()["status"] == "REVIEW_REQUIRED"


def test_resolve_review_as_new_number(client, seed_companies):
    headers = auth_headers()
    client.post("/api/v1/employees", json=_payload(existing_employee_number="000123"), headers={**headers, "Idempotency-Key": "k1"})
    r2 = client.post(
        "/api/v1/employees",
        json=_payload(existing_employee_number="ZZZ999"),
        headers={**headers, "Idempotency-Key": "k2"},
    )
    review_id = r2.json()["review_id"]

    resolve = client.post(
        f"/api/v1/identity-reviews/{review_id}/resolve",
        json={"action": "NEW_NUMBER"},
        headers=headers,
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "NEW_NUMBER"
    assert resolve.json()["unified_employee_number"] is not None


def test_missing_idempotency_key_is_rejected(client, seed_companies):
    resp = client.post("/api/v1/employees", json=_payload(), headers=auth_headers())
    assert resp.status_code == 400


def test_invalid_company_code_returns_422(client, seed_companies):
    resp = client.post(
        "/api/v1/employees",
        json=_payload(company_code="NOPE"),
        headers={**auth_headers(), "Idempotency-Key": "k-bad"},
    )
    assert resp.status_code == 422
    assert resp.json()["field_errors"][0]["field"] == "company_code"
