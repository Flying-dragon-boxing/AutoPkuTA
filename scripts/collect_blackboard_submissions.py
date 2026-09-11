#!/usr/bin/env python3
"""Collect Blackboard assignment submission metadata using pku3b's saved session.

Default mode is metadata-only. Pass --download to download submitted files.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

from pku3b_session import BASE_URL, blackboard_session, ca_bundle, pku3b_cache_dir


def api_get(s: requests.Session, cache_dir: Path, path: str, params: dict[str, Any] | None = None) -> Any:
    r = s.get(BASE_URL + path, params=params, timeout=30, allow_redirects=False, verify=ca_bundle(cache_dir))
    if not r.ok:
        raise RuntimeError(f"GET {path} failed: {r.status_code} {r.text[:200]}")
    return r.json()


def safe_name(name: str) -> str:
    name = unquote(name)
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name).strip("_") or "submission"


def download_attempt_file(
    s: requests.Session,
    cache_dir: Path,
    course_id: str,
    content_id: str,
    column_id: str,
    attempt_id: str,
    file_id: str,
    file_name: str,
) -> bytes:
    classic = s.get(
        BASE_URL + "/webapps/assignment/download",
        params={
            "course_id": course_id,
            "attempt_id": attempt_id,
            "file_id": file_id,
            "fileName": file_name,
        },
        headers={
            "Accept": "*/*",
            "Referer": (
                BASE_URL
                + "/webapps/assignment/gradeAssignmentRedirector"
                + f"?outcomeDefinitionId={column_id}&course_id={course_id}&attempt_id={attempt_id}"
            ),
        },
        timeout=90,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )
    if classic.ok and classic.content and not classic.content.lstrip().startswith(b"<!DOCTYPE"):
        return classic.content

    rest = s.get(
        BASE_URL
        + f"/learn/api/public/v1/courses/{course_id}/gradebook/attempts/{attempt_id}/files/{file_id}/download",
        timeout=90,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )
    if rest.ok and rest.content and not rest.content.lstrip().startswith(b"<!DOCTYPE"):
        return rest.content

    raise RuntimeError(
        f"download failed attempt={attempt_id} file={file_id}: "
        f"classic={classic.status_code}, rest={rest.status_code}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-id", required=True, help="Blackboard course id, e.g. _98497_1")
    parser.add_argument("--content-id", required=True, help="Assignment content id, e.g. _1619008_1")
    parser.add_argument("--outdir", default="blackboard_submissions")
    parser.add_argument("--download", action="store_true", help="Download submitted files after collecting metadata")
    args = parser.parse_args()

    cache_dir = pku3b_cache_dir()
    try:
        s = blackboard_session(cache_dir)
    except RuntimeError as exc:
        raise SystemExit(f"{exc}. Run `python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh`.") from exc
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    columns = api_get(s, cache_dir, f"/learn/api/public/v1/courses/{args.course_id}/gradebook/columns")
    matches = [c for c in columns.get("results", []) if c.get("contentId") == args.content_id]
    if not matches:
        raise SystemExit(f"No gradebook column found for content_id={args.content_id}")
    if len(matches) > 1:
        raise SystemExit(f"Multiple columns found for content_id={args.content_id}: {[c.get('id') for c in matches]}")

    column = matches[0]
    column_id = column["id"]
    attempts = api_get(
        s,
        cache_dir,
        f"/learn/api/public/v2/courses/{args.course_id}/gradebook/columns/{column_id}/attempts",
    ).get("results", [])

    result = {
        "course_id": args.course_id,
        "content_id": args.content_id,
        "column": column,
        "attempt_count": len(attempts),
        "attempts": [],
    }

    for attempt in attempts:
        attempt_id = attempt["id"]
        user_id = attempt.get("userId")
        user = {}
        user_lookup_error = ""
        if user_id:
            try:
                user = api_get(s, cache_dir, f"/learn/api/public/v1/users/{user_id}")
            except Exception as exc:
                user_lookup_error = str(exc)
                user = {"id": user_id, "lookup_error": user_lookup_error}
        files = api_get(
            s,
            cache_dir,
            f"/learn/api/public/v1/courses/{args.course_id}/gradebook/attempts/{attempt_id}/files",
        ).get("results", [])

        entry = {"attempt": attempt, "user": user, "files": files}
        if user_lookup_error:
            entry["user_lookup_error"] = user_lookup_error
        result["attempts"].append(entry)

        if args.download:
            student_key = safe_name(f"{user.get('userName', user_id)}_{user.get('name', {}).get('given', '')}")
            student_dir = outdir / "files" / student_key
            student_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                file_id = f["id"]
                file_name = safe_name(f["name"])
                content = download_attempt_file(
                    s,
                    cache_dir,
                    args.course_id,
                    args.content_id,
                    column_id,
                    attempt_id,
                    file_id,
                    f["name"],
                )
                (student_dir / file_name).write_bytes(content)

    (outdir / "submission_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"column_id": column_id, "attempt_count": len(attempts), "out": str(outdir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
