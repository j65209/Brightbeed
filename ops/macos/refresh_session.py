"""One bounded login attempt using the server's existing credentials/selectors."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys

from job_runtime import atomic_write


def refresh(platform, brand="6a"):
    collector = Path.home() / "projects" / (platform + "-collector")
    sys.path.insert(0, str(collector / "src"))
    spec = importlib.util.spec_from_file_location("existing_login", collector / "src" / "auto_login.py")
    login = importlib.util.module_from_spec(spec)
    saved_argv = sys.argv
    try:
        sys.argv = [str(collector / "src" / "auto_login.py"), brand]
        spec.loader.exec_module(login)
    finally:
        sys.argv = saved_argv
    if platform == "ably":
        suffix = "_" + brand.upper() if brand != "6a" else ""
        login.EMAIL = os.environ.get("ABLY_EMAIL" + suffix, "")
        login.PASSWORD = os.environ.get("ABLY_PASSWORD" + suffix, "")
    if platform == "zigzag":
        # kop·apt 는 coferryworld 계정 하나 공용
        if brand in ("kop", "apt"):
            login.EMAIL = os.environ.get("KAKAOSTYLE_EMAIL_COP", "")
            login.PASSWORD = os.environ.get("KAKAOSTYLE_PASSWORD_COP", "")
        else:
            login.EMAIL = os.environ.get("KAKAOSTYLE_EMAIL", "")
            login.PASSWORD = os.environ.get("KAKAOSTYLE_PASSWORD", "")
    if not login.EMAIL or not login.PASSWORD:
        return 1
    state = collector / "data" / ("ably-state.json" if platform == "ably" else "kakaostyle-state.json")
    if platform == "ably" and brand != "6a":
        state = collector / "data" / ("ably-state-" + brand + ".json")
    if platform == "zigzag" and brand != "6a":
        state = collector / "data" / ("kakaostyle-state-" + brand + ".json")
    state.parent.mkdir(parents=True, exist_ok=True)
    with open(str(state) + ".lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 1
        with login.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul")
                page = ctx.new_page()
                page.set_default_timeout(10000)
                page.goto(login.LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                if not login.try_fill(page, login.EMAIL_SELECTORS, login.EMAIL):
                    return 1
                if not login.try_fill(page, login.PASSWORD_SELECTORS, login.PASSWORD):
                    return 1
                if not login.try_click(page, login.SUBMIT_SELECTORS):
                    return 1
                page.wait_for_url(lambda u: "login" not in u.lower() and "signin" not in u.lower(), timeout=15000)
                page.goto(login.HOME_URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2500)
                if "login" in page.url.lower() or "signin" in page.url.lower():
                    return 1
                value = ctx.storage_state()
                if not value.get("cookies"):
                    return 1
                if state.exists():
                    atomic_write(str(state) + ".last-good", state.read_bytes())
                atomic_write(state, json.dumps(value).encode())
                return 0
            finally:
                browser.close()


if __name__ == "__main__":
    try:
        platform = sys.argv[1]
        if platform not in ("ably", "zigzag"):
            raise ValueError("unknown platform")
        brand = sys.argv[2] if len(sys.argv) > 2 else "6a"
        if brand not in ("6a", "kop", "apt"):
            raise ValueError("unknown brand")
        code = refresh(platform, brand)
    except Exception:
        # Never echo browser diagnostics, cookies, form data, or credentials.
        code = 1
    print("session_refreshed" if code == 0 else "session_login_required")
    raise SystemExit(code)
