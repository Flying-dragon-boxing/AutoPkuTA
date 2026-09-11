#!/usr/bin/env python3
"""Group downloaded Blackboard submissions by a CSV group roster.

Reads submission_manifest.json produced by collect_blackboard_submissions.py.
Downloads files through Blackboard's classic assignment/download endpoint and
writes group folders with attempt ids preserved in filenames.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import unquote

import requests

from pku3b_session import BASE_URL, blackboard_session, ca_bundle, pku3b_cache_dir

def safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", unquote(str(name))).strip("_") or "unnamed"


def load_groups(path: Path) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    if rows and {"topic", "group_id", "member_name"}.issubset(rows[0].keys()):
        groups_by_key: dict[tuple[str, str], dict[str, str]] = {}
        by_name: dict[str, dict[str, str]] = {}
        for row in rows:
            topic = row.get("topic", "").strip()
            group_id = row.get("group_id", "").strip()
            member = row.get("member_name", "").strip()
            if not group_id or not member:
                continue
            key = (topic, group_id)
            group = groups_by_key.setdefault(key, {"topic": topic, "group_id": group_id, "members": ""})
            members = [m for m in group["members"].split("、") if m]
            if member not in members:
                members.append(member)
            group["members"] = "、".join(members)
            by_name[member] = group
        return list(groups_by_key.values()), by_name

    groups: list[dict[str, str]] = []
    by_name: dict[str, dict[str, str]] = {}
    current_topic = ""
    for row in rows:
        if row.get("题目", "").strip():
            current_topic = row["题目"].strip()
        group_id = row.get("多少组选", "").strip()
        if not group_id:
            continue
        members = [row.get(k, "").strip() for k in ["组员1", "组员2", "组员3"]]
        members = [m for m in members if m]
        group = {"topic": current_topic, "group_id": group_id, "members": "、".join(members)}
        groups.append(group)
        for member in members:
            by_name[member] = group
    return groups, by_name


def user_display_name(user: dict) -> str:
    name = user.get("name", {})
    return str(name.get("given") or name.get("family") or user.get("userName") or user.get("id") or "")


def download_file(
    s: requests.Session,
    cache_dir: Path,
    course_id: str,
    column_id: str,
    attempt_id: str,
    file_id: str,
    file_name: str,
) -> bytes:
    r = s.get(
        BASE_URL + "/webapps/assignment/download",
        params={
            "course_id": course_id,
            "attempt_id": attempt_id,
            "file_id": file_id,
            "fileName": file_name,
        },
        headers={
            "Referer": (
                BASE_URL
                + "/webapps/assignment/gradeAssignmentRedirector"
                + f"?outcomeDefinitionId={column_id}&course_id={course_id}&attempt_id={attempt_id}"
            )
        },
        timeout=120,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )
    if not r.ok or not r.content or r.content.lstrip().startswith(b"<!DOCTYPE"):
        raise RuntimeError(f"download failed attempt={attempt_id} file={file_id}: {r.status_code}")
    return r.content


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--groups", required=True)
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    groups, by_name = load_groups(Path(args.groups))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cache_dir = pku3b_cache_dir()
    try:
        s = blackboard_session(cache_dir, accept="*/*")
    except RuntimeError as exc:
        raise SystemExit(f"{exc}. Run `python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh`.") from exc
    course_id = manifest["course_id"]
    column_id = manifest["column"]["id"]

    summary_rows = []
    for entry in manifest["attempts"]:
        attempt = entry["attempt"]
        user = entry["user"]
        student_name = user_display_name(user)
        student_no = user.get("userName", "")
        group = by_name.get(student_name)
        group_folder = (
            f"{safe_name(group['topic'])}__{safe_name(group['group_id'])}"
            if group
            else "_未匹配"
        )
        dest_dir = outdir / group_folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        for f in entry["files"]:
            dest_name = safe_name(f"{student_no}_{student_name}_{attempt['id']}_{f['name']}")
            dest = dest_dir / dest_name
            content = download_file(
                s,
                cache_dir,
                course_id,
                column_id,
                attempt["id"],
                f["id"],
                f["name"],
            )
            dest.write_bytes(content)
            summary_rows.append(
                {
                    "topic": group["topic"] if group else "",
                    "group_id": group["group_id"] if group else "",
                    "members": group["members"] if group else "",
                    "student_no": student_no,
                    "student_name": student_name,
                    "attempt_id": attempt["id"],
                    "submitted_at": attempt.get("attemptDate", ""),
                    "status": attempt.get("status", ""),
                    "file_name": f["name"],
                    "saved_path": str(dest),
                }
            )

    report = outdir / "分组下载清单.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()) if summary_rows else [])
        writer.writeheader()
        writer.writerows(summary_rows)

    unmatched = sorted({r["student_name"] for r in summary_rows if not r["group_id"]})
    print(json.dumps({"files": len(summary_rows), "groups": len(groups), "unmatched": unmatched, "out": str(outdir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
