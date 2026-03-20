"""Selenium test configuration for JupySQL JupyterLab extension.

Known issues
------------
jupysql-plugin v0.4.5 (the latest) has a frontend bug where `this.panel` is
undefined in `_onSettingsChanged` when no notebook is open.  This shows up as
a TypeError in the browser console and affects the notebook toolbar buttons,
but does NOT affect the database-browser sidebar or our REST API.  There is no
newer version to upgrade to; treat it as a known upstream issue.
"""

import os
import time

import pytest
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

JUPYTERLAB_URL = os.environ.get("JUPYTERLAB_URL", "http://localhost:8888")

# PostgreSQL coordinates injected by docker-compose (or env overrides for local runs)
POSTGRES_HOST = os.environ.get("POSTGRES_TEST_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_TEST_PORT", "5432")
POSTGRES_USER = os.environ.get("POSTGRES_TEST_USER", "postgres")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_TEST_PASSWORD", "postgres")
POSTGRES_DB = os.environ.get("POSTGRES_TEST_DB", "testdb")

POSTGRES_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)


def wait_for_jupyterlab(driver, timeout=60):
    """Wait until JupyterLab shell is rendered."""
    driver.get(JUPYTERLAB_URL)
    # JupyterLab 4 renders its main shell as #main with class jp-LabShell
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main, .jp-LabShell"))
    )
    # Give extensions a moment to activate
    time.sleep(3)


@pytest.fixture(scope="session")
def jupyterlab_url():
    return JUPYTERLAB_URL


@pytest.fixture(scope="module")
def running_kernel():
    """Start a Jupyter kernel, yield its ID, then shut it down.

    Tests that need to execute code in a kernel (connection error tests)
    use this fixture to ensure at least one kernel is available.
    """
    resp = requests.post(f"{JUPYTERLAB_URL}/api/kernels", json={}, timeout=15)
    assert resp.status_code == 201, (
        f"Failed to start kernel: {resp.status_code} {resp.text}"
    )
    kernel_id = resp.json()["id"]
    # Brief warm-up so the kernel is ready to execute code
    time.sleep(2)
    yield kernel_id
    requests.delete(f"{JUPYTERLAB_URL}/api/kernels/{kernel_id}", timeout=5)


@pytest.fixture(scope="session")
def driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Enable browser logging so tests can inspect console errors
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(10)

    wait_for_jupyterlab(driver)

    yield driver
    driver.quit()
