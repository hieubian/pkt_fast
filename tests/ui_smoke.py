"""Browser smoke test for the core export flow.

Install Playwright and a Chromium browser separately, then run:
    python tests/ui_smoke.py
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
import sys
import shutil
from urllib.request import urlopen
from html.parser import HTMLParser

from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ContractParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(str(attributes["id"]))
        self.tags.append((tag, attributes))


def static_contract() -> None:
    source = (ROOT / "index.html").read_text(encoding="utf-8")
    parser = ContractParser()
    parser.feed(source)
    required = {
        "topology-canvas", "device-palette", "btn-export-pkt", "export-modal",
        "export-preview-rows", "export-confirm", "router-model", "studio-toast",
    }
    missing = sorted(required - parser.ids)
    assert not missing, "Required UI controls are missing: " + ", ".join(missing)
    for asset in ("assets/studio.css", "assets/studio.js"):
        assert (ROOT / asset).is_file(), f"Missing UI asset: {asset}"
    assert source.count('lang="vi"') == 1


def main() -> None:
    static_contract()
    from server import Handler

    local_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=local_server.serve_forever, daemon=True)
    thread.start()
    errors: list[str] = []
    try:
        base_url = f"http://127.0.0.1:{local_server.server_port}"
        with urlopen(base_url, timeout=3) as response:
            served_html = response.read().decode("utf-8")
            assert response.status == 200 and 'id="topology-canvas"' in served_html
        with sync_playwright() as playwright:
            chromium_path = shutil.which("chromium") or shutil.which("google-chrome")
            launch_options = {"headless": True}
            if chromium_path:
                launch_options["executable_path"] = chromium_path
                launch_options["args"] = ["--no-sandbox"]
            try:
                browser = playwright.chromium.launch(**launch_options)
            except Exception as error:
                print("Static UI contract passed.")
                detail = str(error)
                if "socket() failed" in detail or "Operation not permitted" in detail:
                    reason = "Chromium bị execution sandbox chặn socket nội bộ."
                else:
                    reason = detail.splitlines()[0] if detail else error.__class__.__name__
                print(f"Browser-level check skipped: {reason}")
                return
            page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            page.on("pageerror", lambda error: errors.append(str(error)))

            def fake_export(route):
                route.fulfill(
                    status=200,
                    content_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="topology.pkt"'},
                    body=b"MOCK-PKT",
                )

            page.route("**/api/export", fake_export)
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_function(
                "document.querySelector('#stat-devices')?.textContent === '4'",
                timeout=15000,
            )
            assert page.locator("#btn-export-pkt").is_visible()
            page.locator("#btn-export-pkt").click()
            page.get_by_role("dialog").wait_for(state="visible")
            assert "Sơ đồ đã sẵn sàng" in page.locator("#export-alert").inner_text()
            assert page.locator("#export-confirm").is_enabled()

            with tempfile.TemporaryDirectory(prefix="simulan-ui-test-") as temporary:
                with page.expect_download() as download_info:
                    page.locator("#export-confirm").click()
                download = download_info.value
                destination = Path(temporary) / download.suggested_filename
                download.save_as(destination)
                assert destination.name == "topology.pkt"
                assert destination.read_bytes() == b"MOCK-PKT"

            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("#topology-canvas").is_visible()
            assert not errors, "Browser reported errors: " + " | ".join(errors)
            browser.close()
        print("UI smoke test passed: startup lab, export preflight, download flow, mobile viewport.")
    finally:
        local_server.shutdown()
        local_server.server_close()


if __name__ == "__main__":
    main()

