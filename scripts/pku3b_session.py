"""Shared helpers for reusing pku3b's Blackboard session."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import requests


BASE_URL = "https://course.pku.edu.cn"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)


def pku3b_cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pku3b"


def ca_bundle(cache_dir: Path | None = None) -> str | bool:
    cache_dir = cache_dir or pku3b_cache_dir()
    path = cache_dir / "combined-ca-bundle.pem"
    return str(path) if path.exists() else True


def find_pku3b() -> str | None:
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        os.environ.get("PKU3B_BIN"),
        shutil.which("pku3b"),
        repo_root.parent / "pku3b" / "target" / "release" / "pku3b",
        repo_root.parent / "pku3b" / "target" / "debug" / "pku3b",
    ]
    return next((str(c) for c in candidates if c and Path(c).exists()), None)


def load_cookie_header(cache_dir: Path | None = None) -> str:
    cache_dir = cache_dir or pku3b_cache_dir()
    path = cache_dir / "ua.json"
    if not path.exists():
        raise RuntimeError(f"pku3b cookie store not found: {path}")

    data = json.loads(path.read_text())
    cookies = []
    for item in data:
        domain = item.get("domain")
        if isinstance(domain, dict) and domain.get("HostOnly") == "course.pku.edu.cn":
            cookies.append(item["raw_cookie"])
    if not cookies:
        raise RuntimeError("No course.pku.edu.cn cookie found in pku3b cookie store")
    return "; ".join(cookies)


def blackboard_session(cache_dir: Path | None = None, accept: str = "application/json,text/html,*/*") -> requests.Session:
    cache_dir = cache_dir or pku3b_cache_dir()
    s = requests.Session()
    s.trust_env = False
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Cookie": load_cookie_header(cache_dir),
            "Accept": accept,
        }
    )
    return s


def check_session(cache_dir: Path | None = None, timeout: int = 20) -> tuple[bool, str]:
    cache_dir = cache_dir or pku3b_cache_dir()
    try:
        s = blackboard_session(cache_dir)
        r = s.get(
            BASE_URL + "/webapps/portal/execute/tabs/tabAction",
            params={"tab_tab_group_id": "_1_1"},
            timeout=timeout,
            allow_redirects=False,
            verify=ca_bundle(cache_dir),
        )
    except Exception as exc:
        return False, f"session check failed: {type(exc).__name__}: {exc}"

    location = r.headers.get("location", "")
    if r.status_code == 200 and "webapps/login" not in location:
        return True, "pku3b Blackboard session is valid"
    return False, f"Blackboard session invalid: status={r.status_code}, location={location}"


def refresh_session_with_pku3b(args: list[str] | None = None, timeout: int = 120) -> tuple[bool, str]:
    bin_path = find_pku3b()
    if not bin_path:
        return False, "pku3b binary not found; set PKU3B_BIN or install pku3b"

    cmd = [bin_path] + (args or ["a", "ls", "--all-term"])
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        return False, f"failed to run pku3b: {type(exc).__name__}: {exc}"

    if run.returncode == 0:
        return True, "pku3b command completed and session should be refreshed"
    msg = (run.stderr or run.stdout or "").strip().splitlines()
    return False, "pku3b command failed: " + (msg[-1] if msg else f"exit {run.returncode}")
