"""Selenium tests for the JupySQL JupyterLab extension.

These tests run against a live JupyterLab instance. Set JUPYTERLAB_URL
environment variable to point to a running server (default: http://localhost:8888).

Run via Docker:
    docker compose run --rm selenium-tests

Run locally (requires Chrome/chromedriver and a running JupyterLab):
    JUPYTERLAB_URL=http://localhost:8888 pytest tests/selenium/ -v
"""

import time
import os

import requests
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from conftest import (
    JUPYTERLAB_URL,
    POSTGRES_URL,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_DB,
)


# ---------------------------------------------------------------------------
# HTTP-level API tests (no browser needed)
# ---------------------------------------------------------------------------


def test_server_is_reachable():
    """JupyterLab server must respond to HTTP requests."""
    resp = requests.get(JUPYTERLAB_URL, timeout=10)
    assert resp.status_code == 200


def test_jupysql_api_connections_endpoint_returns_200():
    """The /jupysql/connections REST endpoint must return HTTP 200 and valid JSON.

    When the extension is loaded (even with no running kernels), the endpoint
    always returns {"connections": []} rather than a 404.
    """
    resp = requests.get(f"{JUPYTERLAB_URL}/jupysql/connections", timeout=10)
    assert resp.status_code == 200, (
        f"Expected 200 but got {resp.status_code}. "
        "The JupySQL server extension (sql.labextension) is likely not loaded. "
        f"Body: {resp.text[:200]}"
    )
    data = resp.json()
    assert "connections" in data, (
        f"Response JSON is missing 'connections' key: {data}"
    )
    assert isinstance(data["connections"], list), (
        f"'connections' value should be a list, got: {type(data['connections'])}"
    )


def test_jupysql_api_init_endpoint():
    """POST /jupysql/init must succeed (returns success or no_kernel, never 4xx/5xx)."""
    resp = requests.post(
        f"{JUPYTERLAB_URL}/jupysql/init",
        json={},
        timeout=10,
    )
    assert resp.status_code == 200, (
        f"Expected 200 but got {resp.status_code}: {resp.text}"
    )
    data = resp.json()
    assert data.get("status") in ("success", "no_kernel"), (
        f"Unexpected status value: {data}"
    )


def test_jupysql_api_tables_requires_connection_key():
    """The /jupysql/tables endpoint returns 400 when connection_key is missing."""
    resp = requests.get(f"{JUPYTERLAB_URL}/jupysql/tables", timeout=10)
    assert resp.status_code == 400, (
        f"Expected 400 (missing params) but got {resp.status_code}"
    )
    data = resp.json()
    assert "error" in data


def test_jupysql_api_columns_requires_params():
    """The /jupysql/columns endpoint returns 400 when required params are missing."""
    resp = requests.get(f"{JUPYTERLAB_URL}/jupysql/columns", timeout=10)
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data


def test_jupysql_api_schemas_requires_connection_key():
    """The /jupysql/schemas endpoint returns 400 without connection_key."""
    resp = requests.get(f"{JUPYTERLAB_URL}/jupysql/schemas", timeout=10)
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data


# ---------------------------------------------------------------------------
# Browser (Selenium) tests
# ---------------------------------------------------------------------------


def test_jupyterlab_page_loads(driver):
    """JupyterLab HTML must load and contain the main shell element."""
    driver.get(JUPYTERLAB_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
    )
    assert driver.find_elements(By.CSS_SELECTOR, "#main"), (
        "#main element not found in DOM"
    )


def test_left_sidebar_is_present(driver):
    """JupyterLab left sidebar must be rendered."""
    driver.get(JUPYTERLAB_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
    )
    sidebar = driver.find_elements(By.CSS_SELECTOR, ".jp-SideBar")
    assert len(sidebar) > 0, "Left sidebar (.jp-SideBar) not found in DOM"


def test_database_browser_widget_registered(driver):
    """The database browser widget must exist in the left panel DOM."""
    driver.get(JUPYTERLAB_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
    )
    time.sleep(4)  # allow extensions to fully activate

    # Our extension adds a widget with id 'jupysql-database-browser'
    widget = driver.find_elements(By.ID, "jupysql-database-browser")
    assert len(widget) > 0, (
        "Database browser widget (#jupysql-database-browser) not found. "
        "The jupysql-labextension may not be installed correctly."
    )


def test_database_browser_sidebar_no_json_parse_error(driver):
    """Opening the database browser sidebar must NOT produce a JSON.parse error.

    Previously, /jupysql/connections returned 404 (extension not loaded),
    causing the frontend to fail with 'JSON.parse: unexpected character'.
    This test ensures the sidebar loads cleanly.
    """
    driver.get(JUPYTERLAB_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
    )
    time.sleep(4)

    # Collect any browser-console errors
    logs = driver.get_log("browser")
    json_parse_errors = [
        entry for entry in logs
        if "JSON.parse" in entry.get("message", "")
        and "unexpected character" in entry.get("message", "")
    ]
    assert len(json_parse_errors) == 0, (
        f"JSON.parse errors found in browser console — "
        f"likely a 404 on /jupysql/connections:\n"
        + "\n".join(e["message"] for e in json_parse_errors)
    )


def test_launcher_is_accessible(driver):
    """The JupyterLab Launcher must appear in the main area on fresh load."""
    driver.get(JUPYTERLAB_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
    )
    launcher = driver.find_elements(
        By.CSS_SELECTOR, ".jp-LauncherCard, .jp-Launcher"
    )
    assert len(launcher) > 0, "JupyterLab Launcher not found in DOM"


def test_new_notebook_can_be_created(driver):
    """A new Python notebook must be creatable via the Launcher."""
    driver.get(JUPYTERLAB_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main"))
    )
    time.sleep(2)

    cards = driver.find_elements(By.CSS_SELECTOR, ".jp-LauncherCard")
    notebook_card = None
    for card in cards:
        category = card.get_attribute("data-category") or ""
        label = card.text.lower()
        if "notebook" in category.lower() or "python" in label:
            notebook_card = card
            break

    if notebook_card is None:
        pytest.skip("No Python notebook launcher card found — kernel may not be ready")

    notebook_card.click()
    time.sleep(3)

    notebook_tab = driver.find_elements(
        By.CSS_SELECTOR, ".jp-NotebookPanel, .lm-TabBar-tab"
    )
    assert len(notebook_tab) > 0, "Notebook panel did not open after clicking launcher"


# ---------------------------------------------------------------------------
# Connection error reporting tests (require a running kernel)
# ---------------------------------------------------------------------------


def _post_connection(connection_string, alias=None):
    """Helper: POST to /jupysql/connections and return (status_code, body_dict)."""
    payload = {"connection_string": connection_string}
    if alias:
        payload["alias"] = alias
    resp = requests.post(
        f"{JUPYTERLAB_URL}/jupysql/connections",
        json=payload,
        timeout=40,  # kernel execution may take up to 30 s
    )
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    return resp.status_code, body


def test_add_connection_missing_driver(running_kernel):
    """Attempting to use a DB dialect with no driver installed must return 400
    with a descriptive error — NOT a generic 500.

    'fakedb://' has no SQLAlchemy dialect so the error is thrown before any
    network call is made.
    """
    status, body = _post_connection("fakedb://localhost/mydb")
    assert status == 400, (
        f"Expected 400 for unknown driver, got {status}. Body: {body}"
    )
    assert "error" in body, f"Response missing 'error' key: {body}"
    error_text = body["error"].lower()
    assert any(kw in error_text for kw in ("could not load", "no module", "fakedb")), (
        f"Error message doesn't mention missing driver: {body['error']}"
    )


def test_add_connection_offline_db(running_kernel):
    """Connecting to a port with nothing listening must return 400 with a
    connection-refused / timeout error message."""
    # Port 19999 is extremely unlikely to be in use inside the container
    status, body = _post_connection(
        "postgresql://postgres:postgres@localhost:19999/testdb"
    )
    assert status == 400, (
        f"Expected 400 for offline DB, got {status}. Body: {body}"
    )
    assert "error" in body
    error_text = body["error"].lower()
    assert any(
        kw in error_text
        for kw in ("refused", "connect", "timeout", "operational", "could not")
    ), f"Error message doesn't describe a connection failure: {body['error']}"


def test_add_connection_wrong_credentials(running_kernel):
    """Wrong password must return 400 with an authentication error — not 500."""
    status, body = _post_connection(
        f"postgresql://wrong_user:wrong_pass@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )
    assert status == 400, (
        f"Expected 400 for wrong credentials, got {status}. Body: {body}"
    )
    assert "error" in body
    error_text = body["error"].lower()
    assert any(
        kw in error_text
        for kw in ("password", "authentication", "role", "access denied", "operational")
    ), f"Error message doesn't describe an auth failure: {body['error']}"


def test_add_connection_wrong_db_name(running_kernel):
    """Connecting to a non-existent database must return 400 with a
    'database does not exist' style error."""
    status, body = _post_connection(
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/nonexistent_db_xyz"
    )
    assert status == 400, (
        f"Expected 400 for wrong DB name, got {status}. Body: {body}"
    )
    assert "error" in body
    error_text = body["error"].lower()
    assert any(
        kw in error_text
        for kw in ("does not exist", "database", "operational", "not found")
    ), f"Error message doesn't describe a missing database: {body['error']}"


def test_add_connection_success_and_error_format(running_kernel):
    """A valid connection must return 200 with status=success; an invalid one
    must return 400 with an 'error' key containing a non-empty string.

    This test validates the overall contract: errors are never swallowed as
    HTTP 500 and always carry a human-readable message.
    """
    # Valid: in-memory SQLite (always available, no extra server needed)
    status, body = _post_connection("sqlite://")
    assert status == 200, f"sqlite:// should connect OK, got {status}: {body}"
    assert body.get("status") == "success", f"Expected status=success: {body}"

    # Invalid: will fail at driver lookup
    status, body = _post_connection("no_such_driver://host/db")
    assert status == 400, f"Invalid driver should return 400, got {status}: {body}"
    assert "error" in body and body["error"], (
        f"Error response must have a non-empty 'error' field: {body}"
    )
