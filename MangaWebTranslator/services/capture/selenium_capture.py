"""Interactive Selenium capture service (Firefox version).

Responsibilities implemented:
    - Launch a visible (non-headless) Selenium Firefox session and keep it alive.
    - Navigate to a URL on demand.
    - Capture full-page screenshots for region selection in the UI.
    - Scrape <img> elements, download their image data and return local file paths.

Persistence / manga metadata (chapter ordering, title, etc.) is deliberately
left for a later phase — this service focuses solely on interactive capture.

Note: Requires a working `geckodriver` accessible on PATH. If not present,
download from: https://github.com/mozilla/geckodriver/releases and place it
in a directory on PATH or alongside the Python executable.
"""
from __future__ import annotations

from typing import List, Optional
import os
import time
import uuid
import requests

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.common.by import By


class SeleniumPanelCapture:
    """Manage a persistent Selenium Firefox driver for interactive use."""

    def __init__(self) -> None:
        self._driver: Optional[webdriver.Firefox] = None

    # ---------------------- Driver Lifecycle ----------------------
    def ensure_driver(self) -> webdriver.Firefox:
        """Ensure a visible (non-headless) Firefox driver is running.

        Returns
        -------
        webdriver.Firefox
            Live Firefox driver instance.
        """
        if self._driver is not None:
            return self._driver
        opts = FirefoxOptions()
        # Visible browser (do not set headless). Set optional preferences later.
        opts.set_preference("dom.disable_beforeunload", True)
        # Create driver
        self._driver = webdriver.Firefox(options=opts)
        try:
            self._driver.maximize_window()
        except Exception:
            pass
        return self._driver

    def close(self) -> None:
        """Close the driver if active."""
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None

    # ---------------------- Navigation ----------------------
    def navigate(self, url: str) -> None:
        """Navigate the browser to a URL."""
        driver = self.ensure_driver()
        driver.get(url)

    # ---------------------- Screenshot Capture ----------------------
    def screenshot_fullpage(self, output_dir: str) -> str:
        """Capture a full-page screenshot.

        Returns path to PNG file. Uses window resizing and scroll to attempt
        full height capture; falls back to current viewport if full capture fails.
        """
        driver = self.ensure_driver()
        os.makedirs(output_dir, exist_ok=True)
        # Attempt full height sizing via JS.
        try:
            total_height = driver.execute_script("return document.body.parentNode.scrollHeight")
            driver.set_window_size(1920, total_height)
            time.sleep(0.2)
        except Exception:
            pass
        path = os.path.join(output_dir, f"screenshot_{uuid.uuid4().hex}.png")
        driver.save_screenshot(path)
        return path

    # ---------------------- Image Scraping ----------------------
    def scrape_images(self, output_dir: str, limit: int | None = None) -> List[str]:
        """Scrape <img> elements, download their src content.

        Parameters
        ----------
        output_dir : str
            Directory to store downloaded images.
        limit : int | None
            Optional maximum number of images.
        Returns
        -------
        list[str]
            Local file paths of saved images.
        """
        driver = self.ensure_driver()
        os.makedirs(output_dir, exist_ok=True)
        imgs = driver.find_elements(By.TAG_NAME, "img")
        results: List[str] = []
        for el in imgs:
            if limit is not None and len(results) >= limit:
                break
            src = el.get_attribute("src")
            if not src or src.startswith("data:"):
                # Skip embedded data URIs for now.
                continue
            try:
                resp = requests.get(src, timeout=10)
                if resp.status_code != 200:
                    continue
                ext = ".png"
                ctype = resp.headers.get("Content-Type", "").lower()
                if "jpeg" in ctype or "jpg" in ctype:
                    ext = ".jpg"
                elif "webp" in ctype:
                    ext = ".webp"
                fname = f"scrape_{uuid.uuid4().hex}{ext}"
                fpath = os.path.join(output_dir, fname)
                with open(fpath, "wb") as fh:
                    fh.write(resp.content)
                results.append(fpath)
            except Exception:
                continue
        return results

    # ---------------------- Utility ----------------------
    def is_active(self) -> bool:
        """Return whether a driver session is active."""
        return self._driver is not None

    def current_url(self) -> Optional[str]:
        if self._driver is None:
            return None
        try:
            return self._driver.current_url
        except Exception:
            return None

