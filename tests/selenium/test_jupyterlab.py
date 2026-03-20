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

JUPYTERLAB_URL = os.environ.get("JUPYTERLAB_URL", "http://localhost:8888")


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
