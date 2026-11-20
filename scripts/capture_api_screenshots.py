#!/usr/bin/env python
"""Screenshot the running Django REST API serving the published research run.

    python scripts/capture_api_screenshots.py

The pages are real: everything runs in a temporary directory, where a fresh SQLite
database is migrated, a demo user is created, the showcase report (docs/reports/showcase)
is stored with `manage.py import_backtest_report`, and the development server starts on
a free local port. A headless Chromium browser (Edge or Chrome; SCREENSHOT_BROWSER picks
another executable) is driven over the DevTools protocol and signed in with a Django
session created for the demo user, which has no password. Each page is saved to
docs/assets/screenshots/. The run fails if a page answers with an error status or the
browser logs an error. Server, browser and database are removed afterwards.

Needs requirements_dev.txt and a Chromium-based browser. The pages show a fresh record
id and creation time on every run, so the images are not byte-for-byte reproducible.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WIDTH = 1180  # CSS pixels; captured at device scale 2
USERNAME = "demo"
BROWSER_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
BROWSER_NAMES = ["chromium", "chromium-browser", "google-chrome", "chrome", "msedge", "microsoft-edge"]

SESSION_SNIPPET = """
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
user, _ = get_user_model().objects.get_or_create(username=%r)
user.set_unusable_password()
user.save()
client = Client()
client.force_login(user)
print('SESSION', settings.SESSION_COOKIE_NAME, client.cookies[settings.SESSION_COOKIE_NAME].value)
"""


def find_browser() -> str:
    explicit = os.environ.get("SCREENSHOT_BROWSER")
    if explicit:
        return explicit
    for name in BROWSER_NAMES:
        if shutil.which(name):
            return shutil.which(name)
    for path in BROWSER_PATHS:
        if Path(path).exists():
            return path
    raise SystemExit("error: no Chromium-based browser found; set SCREENSHOT_BROWSER to its executable")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_http(url: str, timeout: float = 40.0) -> bytes:
    """Body of the first answer from url (an error status also proves the server is up)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            return error.read()
        except OSError:
            if time.monotonic() > deadline:
                raise SystemExit(f"error: {url} did not answer within {timeout:.0f} s")
            time.sleep(0.25)


def manage(env: dict, *args: str) -> str:
    result = subprocess.run([sys.executable, str(ROOT / "manage.py"), *args], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"error: manage.py {args[0]} failed\n{result.stdout}{result.stderr}")
    return result.stdout


class DevTools:
    """Minimal Chrome DevTools Protocol client attached to one page."""

    def __init__(self, websocket_url: str):
        from websockets.sync.client import connect

        self.socket = connect(websocket_url, max_size=None, open_timeout=15)
        self.last_id = 0
        self.events: list = []

    def call(self, method: str, **params) -> dict:
        self.last_id += 1
        self.socket.send(json.dumps({"id": self.last_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.socket.recv(timeout=60))
            if message.get("id") == self.last_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})
            self.events.append(message)

    def wait_for_event(self, method: str, timeout: float = 30.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            for i, event in enumerate(self.events):
                if event.get("method") == method:
                    return self.events.pop(i)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no {method} within {timeout:.0f} s")
            self.events.append(json.loads(self.socket.recv(timeout=remaining)))

    def close(self) -> None:
        """Close the connection; its receive thread would otherwise keep Python running."""
        self.socket.close()

    def problems(self, url: str) -> list:
        """Error status of the page itself and errors the browser logged."""
        found = []
        for event in self.events:
            method, params = event.get("method"), event.get("params", {})
            if method == "Network.responseReceived" and params.get("type") == "Document":
                status = params["response"]["status"]
                if status >= 400:
                    found.append(f"HTTP {status} for {params['response']['url']}")
            elif method == "Runtime.exceptionThrown":
                found.append(params["exceptionDetails"].get("text", "exception"))
            elif (method == "Log.entryAdded" and params["entry"]["level"] == "error"
                  and not params["entry"].get("url", "").endswith("/favicon.ico")):  # requested by the browser itself
                found.append(f"{params['entry'].get('text')} ({params['entry'].get('url', url)})")
            elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                found.append(" ".join(str(a.get("value", a.get("description", ""))) for a in params["args"]))
        return found


def save_png(data: bytes, path: Path) -> tuple:
    """256-color palette without dithering, as for the report figures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)
    return image.size


def capture(tools: DevTools, url: str, path: Path, max_height: int) -> tuple:
    tools.events.clear()
    tools.call("Page.navigate", url=url)
    tools.wait_for_event("Page.loadEventFired")
    time.sleep(0.4)  # web fonts and late layout
    # Keep the page's content column (DRF centres it in a .container) and drop the empty margins.
    left, width, height = tools.call("Runtime.evaluate", returnByValue=True, expression=(
        "(() => { const r = document.querySelector('.container').getBoundingClientRect();"
        " return [r.left, r.width, document.documentElement.scrollHeight]; })()"))["result"]["value"]
    x = max(0, int(left) - 12)
    clip = {"x": x, "y": 0, "width": min(WIDTH - x, int(width) + 24), "height": min(int(height), max_height),
            "scale": 1}
    shot = tools.call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=clip)
    problems = tools.problems(url)
    if problems:
        raise SystemExit(f"error: {url}:\n  " + "\n  ".join(problems))
    return save_png(base64.b64decode(shot["data"]), path)


def shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_until_closed(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).close()
        except OSError:
            return
        time.sleep(0.25)


def remove_tree(path: Path) -> None:
    """The browser can hold profile files for a moment after it exits."""
    for _ in range(40):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.25)
    print(f"note: could not remove {path}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "reports" / "showcase")
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "assets" / "screenshots")
    parser.add_argument("--max-height", type=int, default=1500, help="CSS pixels kept from the top of a page")
    args = parser.parse_args(argv)
    browser = find_browser()

    tmp = Path(tempfile.mkdtemp(prefix="api-screenshots-"))
    processes, tools, debug_port = [], None, None
    try:
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{(tmp / 'demo.sqlite3').as_posix()}",
                   CACHE_BACKEND="locmem", DEBUG="True", SECRET_KEY=secrets.token_urlsafe(48),
                   ALLOWED_HOSTS="127.0.0.1,localhost", LOG_DIR=str(tmp / "logs"),
                   DJANGO_SETTINGS_MODULE="quantcore.settings", PYTHONIOENCODING="utf-8")
        manage(env, "migrate", "--noinput")
        session = re.search(r"^SESSION (\S+) (\S+)$", manage(env, "shell", "-c", SESSION_SNIPPET % USERNAME), re.M)
        cookie_name, session_key = session.groups()
        imported = manage(env, "import_backtest_report", str(args.report), "--username", USERNAME).strip()
        print(imported, flush=True)
        backtest_id = re.search(r"as backtest ([0-9a-f-]{36})", imported).group(1)

        port, debug_port = free_port(), free_port()
        with (tmp / "server.log").open("w", encoding="utf-8") as server_log:
            processes.append(subprocess.Popen(
                [sys.executable, str(ROOT / "manage.py"), "runserver", f"127.0.0.1:{port}", "--noreload"],
                cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT))
        base = f"http://127.0.0.1:{port}"
        wait_for_http(f"{base}/admin/login/")
        processes.append(subprocess.Popen(
            [browser, "--headless=new", f"--remote-debugging-port={debug_port}",
             f"--user-data-dir={tmp / 'profile'}", "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", "--hide-scrollbars", f"--window-size={WIDTH},900", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        page = None
        for _ in range(100):
            targets = json.loads(wait_for_http(f"http://127.0.0.1:{debug_port}/json/list"))
            page = next((t for t in targets if t.get("type") == "page"), None)
            if page:
                break
            time.sleep(0.2)
        if page is None:
            raise SystemExit("error: the browser opened no page")
        tools = DevTools(page["webSocketDebuggerUrl"])
        for domain in ("Network", "Page", "Runtime", "Log"):
            tools.call(f"{domain}.enable")
        tools.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=900, deviceScaleFactor=2, mobile=False)
        tools.call("Network.setCookie", name=cookie_name, value=session_key, domain="127.0.0.1", path="/",
                   httpOnly=True)
        pages = {"api-backtest-detail.png": f"{base}/api/v1/backtests/{backtest_id}/"}
        for name, url in pages.items():
            size = capture(tools, url, args.output / name, args.max_height)
            print(f"captured {url.replace(base, '')} -> {shown(args.output / name)} ({size[0]}x{size[1]} px)",
                  flush=True)
    finally:
        if tools is not None:
            # Edge and Chrome may relaunch under another process id, so the browser is
            # closed through DevTools rather than through the process started here.
            try:
                tools.call("Browser.close")
            except Exception:  # the browser may drop the connection before answering
                pass
            tools.close()
            wait_until_closed(debug_port)
        for process in reversed(processes):
            stop(process)
        remove_tree(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
