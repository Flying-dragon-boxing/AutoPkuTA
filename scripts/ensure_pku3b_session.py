#!/usr/bin/env python3
"""Check or refresh pku3b's saved Blackboard session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pku3b_session import check_session, find_pku3b, pku3b_cache_dir, refresh_session_with_pku3b


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Run pku3b to refresh session if the cookie is invalid")
    parser.add_argument("--json", action="store_true", help="Print JSON status")
    args = parser.parse_args()

    ok, msg = check_session()
    refreshed = False
    refresh_msg = ""
    if not ok and args.refresh:
        refreshed, refresh_msg = refresh_session_with_pku3b()
        ok, msg = check_session()

    data = {
        "ok": ok,
        "message": msg,
        "cache_dir": str(pku3b_cache_dir()),
        "cookie_store": str(pku3b_cache_dir() / "ua.json"),
        "pku3b_bin": find_pku3b(),
        "refreshed": refreshed,
        "refresh_message": refresh_msg,
    }

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(("OK: " if ok else "ERROR: ") + msg)
        print(f"cookie_store: {data['cookie_store']}")
        print(f"pku3b_bin: {data['pku3b_bin']}")
        if refresh_msg:
            print(f"refresh: {refresh_msg}")

    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
