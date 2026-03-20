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
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

JUPYTERLAB_URL = os.environ.get("JUPYTERLAB_URL", "http://localhost:8888")


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
