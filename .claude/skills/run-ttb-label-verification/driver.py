"""Driver for running and browser-driving the TTB Label Verification Streamlit app.

Windows-specific (this project has no Linux/xvfb/tmux available): server
lifecycle uses `netstat`/`taskkill` instead of a PID file, and the browser
is driven with Python Playwright (no `chromium-cli` on this machine).

Usage (run with the project's venv interpreter, from the project root):
    .venv\\Scripts\\python.exe .claude\\skills\\run-ttb-label-verification\\driver.py start
    .venv\\Scripts\\python.exe .claude\\skills\\run-ttb-label-verification\\driver.py batch
    .venv\\Scripts\\python.exe .claude\\skills\\run-ttb-label-verification\\driver.py single sample_data\\old-tom-bourbon.png "OLD TOM DISTILLERY" "Kentucky Straight Bourbon Whiskey" "45% Alc./Vol. (90 Proof)" "750 mL"
    .venv\\Scripts\\python.exe .claude\\skills\\run-ttb-label-verification\\driver.py stop
"""

import argparse
import glob
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PORT = 8501
BASE_URL = f"http://localhost:{PORT}"
LOG_PATH = PROJECT_ROOT / "streamlit_driver.log"
SHOT_DIR = PROJECT_ROOT / ".claude" / "skills" / "run-ttb-label-verification" / "shots"


def _python_exe() -> str:
    exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not exe.exists():
        raise SystemExit(f"venv python not found at {exe} -- run Setup first")
    return str(exe)


def _is_up() -> bool:
    try:
        urllib.request.urlopen(BASE_URL, timeout=2)
        return True
    except Exception:
        return False


def cmd_start(_args):
    if _is_up():
        print("already running at", BASE_URL)
        return
    log = open(LOG_PATH, "w")
    subprocess.Popen(
        [_python_exe(), "-m", "streamlit", "run", "app.py",
         "--server.headless=true", f"--server.port={PORT}"],
        cwd=str(PROJECT_ROOT),
        stdout=log, stderr=subprocess.STDOUT,
    )
    print("launching, polling", BASE_URL, "...")
    for _ in range(30):
        if _is_up():
            print("up.")
            return
        time.sleep(1)
    raise SystemExit(f"server did not come up in 30s -- check {LOG_PATH}")


def cmd_stop(_args):
    # No PID file by design (start/stop don't need to share a shell session).
    # Find whatever process is LISTENING on PORT via netstat, then taskkill it.
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines():
        if f":{PORT}" in line and "LISTENING" in line:
            pids.add(line.split()[-1])
    if not pids:
        print("nothing listening on", PORT)
        return
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        print("killed pid", pid)


def _find_file_inputs(page):
    """Returns (csv_input, images_input) locators on the Batch Upload tab."""
    inputs = page.locator('input[type="file"]')
    count = inputs.count()
    csv_input = images_input = None
    for i in range(count):
        el = inputs.nth(i)
        accept = (el.get_attribute("accept") or "").lower()
        multiple = el.get_attribute("multiple")
        if "csv" in accept:
            csv_input = el
        elif multiple is not None:
            images_input = el
    if csv_input is None or images_input is None:
        # Fallback: Batch Upload tab's inputs are the last two mounted.
        csv_input, images_input = inputs.nth(count - 2), inputs.nth(count - 1)
    return csv_input, images_input


def cmd_batch(args):
    from playwright.sync_api import sync_playwright

    target_url = args.url or BASE_URL
    if not args.url and not _is_up():
        raise SystemExit("server not running -- run `start` first (or pass --url for a remote target)")

    csv_path = Path(args.csv or PROJECT_ROOT / "sample_data" / "applications_template.csv")
    if args.images:
        image_paths = [str(Path(p)) for p in args.images]
    else:
        image_paths = sorted(glob.glob(str(PROJECT_ROOT / "sample_data" / "*.png")))

    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(target_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("text=TTB Alcohol Label Verification", timeout=20000)
        page.get_by_role("tab", name="Batch Upload").click()
        page.wait_for_selector("text=Applications CSV", timeout=10000)

        csv_input, images_input = _find_file_inputs(page)
        csv_input.set_input_files(str(csv_path))
        page.wait_for_timeout(800)
        images_input.set_input_files(image_paths)
        page.wait_for_timeout(1200)

        run_button = page.get_by_role("button", name="Run Batch Verification")
        run_button.wait_for(state="visible", timeout=10000)
        if run_button.is_disabled():
            page.screenshot(path=str(SHOT_DIR / "batch-error-disabled.png"))
            raise SystemExit("Run Batch Verification is disabled -- see batch-error-disabled.png")
        run_button.click()

        print("running batch (real API calls, can take up to ~90s)...")
        page.wait_for_selector("text=Download full report", timeout=90000)
        page.wait_for_timeout(500)

        shot = SHOT_DIR / "batch-results.png"
        page.screenshot(path=str(shot), full_page=True)
        print("screenshot:", shot)

        body = page.inner_text("body")
        idx = body.find("Pass")
        print(body[max(0, idx - 20): idx + 200])

        browser.close()


def cmd_single(args):
    from playwright.sync_api import sync_playwright

    target_url = args.url or BASE_URL
    if not args.url and not _is_up():
        raise SystemExit("server not running -- run `start` first (or pass --url for a remote target)")

    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(target_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("text=TTB Alcohol Label Verification", timeout=20000)
        page.get_by_role("tab", name="Single Label").click()
        page.wait_for_selector("text=Submitted application data", timeout=10000)

        # Streamlit text_input widgets don't commit to session state on
        # .fill() alone -- they need a blur/Enter, or the value sits as
        # "Press Enter to apply" and never reaches the server. Press Tab
        # after each fill so it actually commits.
        for label, value in [
            ("Brand Name", args.brand),
            ("Class / Type", args.class_type),
            ("Alcohol Content", args.abv),
            ("Net Contents", args.net_contents),
        ]:
            field = page.get_by_label(label)
            field.fill(value)
            field.press("Tab")

        image_path = Path(args.image)
        page.locator('input[type="file"]').first.set_input_files(str(image_path))
        # The upload round-trips over Streamlit's websocket before the button's
        # disabled state flips on rerun -- a fixed short sleep here is flaky, and
        # the upload chip's filename text is truncated ("old-tom...bourbon.png")
        # so matching on the full filename doesn't work either. Poll the button
        # itself instead.
        verify_button = page.get_by_role("button", name="Verify Label")
        verify_button.wait_for(state="visible", timeout=5000)
        for _ in range(75):  # up to ~15s
            if verify_button.is_enabled():
                break
            page.wait_for_timeout(200)
        else:
            page.screenshot(path=str(SHOT_DIR / "single-error-disabled.png"))
            raise SystemExit("Verify Label never became enabled -- see single-error-disabled.png")

        verify_button.click()
        print("verifying (real API call)...")
        page.wait_for_selector("text=Processed in", timeout=30000)
        page.wait_for_timeout(300)

        shot = SHOT_DIR / "single-result.png"
        page.screenshot(path=str(shot), full_page=True)
        print("screenshot:", shot)
        print(page.inner_text("body")[-1500:])

        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("start", help="launch Streamlit in the background, wait until it serves")
    sub.add_parser("stop", help="kill whatever is listening on :8501")

    p_batch = sub.add_parser("batch", help="drive the Batch Upload tab")
    p_batch.add_argument("--csv", help="defaults to sample_data/applications_template.csv")
    p_batch.add_argument("--images", nargs="*", help="defaults to all sample_data/*.png")
    p_batch.add_argument("--url", help="target a remote deployment instead of localhost:8501 (skips the local `start` check)")

    p_single = sub.add_parser("single", help="drive the Single Label tab")
    p_single.add_argument("image")
    p_single.add_argument("brand")
    p_single.add_argument("class_type")
    p_single.add_argument("abv")
    p_single.add_argument("net_contents")
    p_single.add_argument("--url", help="target a remote deployment instead of localhost:8501 (skips the local `start` check)")

    args = parser.parse_args()
    {"start": cmd_start, "stop": cmd_stop, "batch": cmd_batch, "single": cmd_single}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
