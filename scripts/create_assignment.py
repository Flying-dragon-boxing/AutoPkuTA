#!/usr/bin/env python3
"""Create an assignment on Blackboard in a course content area (WRITE operation).

Default is dry-run: it resolves the target content area and prints the plan,
but does NOT create anything. Pass --yes to actually submit the form.

Examples:
  # list content areas of a course
  python3 create_assignment.py --course-id _98497_1 --list-areas

  # dry-run, then create
  python3 create_assignment.py --course-id _98497_1 --area 课程作业 \
      --name "第11次作业" --points 100 --instructions "见附件" --due "2026-09-25 23:59"
  python3 create_assignment.py ... --yes

Cleanup of a created assignment: open the content area and delete it in the UI
(或 GET /webapps/assignment/execute/manageAssignment?method=remove&content_id=<id>&course_id=<id>)。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

from inspect_courses import get_session
from pku3b_session import BASE_URL, ca_bundle, pku3b_cache_dir


def get_page(s: requests.Session, cache_dir, path: str, params: dict[str, Any]) -> requests.Response:
    return s.get(
        BASE_URL + path,
        params=params,
        timeout=30,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )


def list_content_areas(s: requests.Session, cache_dir, course_bb_id: str) -> list[dict[str, str]]:
    """Course menu entries that point to content areas (listContentEditable)."""
    page = get_page(s, cache_dir, "/webapps/blackboard/execute/courseMain", {"course_id": course_bb_id}).text
    areas = []
    for href, text in re.findall(
        r'<a[^>]*href="(/webapps/blackboard/content/listContentEditable\.jsp\?[^"]+)"[^>]*>(.*?)</a>', page, re.S
    ):
        m = re.search(r"content_id=([^&]+)", href)
        name = re.sub(r"<[^>]+>", "", text).strip()
        if m and name:
            areas.append({"content_id": m.group(1), "name": name})
    seen, out = set(), []
    for a in areas:
        if a["content_id"] not in seen:
            seen.add(a["content_id"])
            out.append(a)
    return out


def resolve_area(s, cache_dir, course_bb_id: str, area: str) -> dict[str, str]:
    areas = list_content_areas(s, cache_dir, course_bb_id)
    if not areas:
        raise SystemExit("no content areas found on the course main page")
    if area.startswith("_"):
        hit = next((a for a in areas if a["content_id"] == area), None)
    else:
        hits = [a for a in areas if area in a["name"]]
        if len(hits) > 1:
            raise SystemExit(f"area name {area!r} is ambiguous: {[(a['name'], a['content_id']) for a in hits]}")
        hit = hits[0] if hits else None
    if not hit:
        raise SystemExit(f"area {area!r} not found; available: {[(a['name'], a['content_id']) for a in areas]}")
    return hit


def fetch_create_form(s, cache_dir, course_bb_id: str, area_id: str) -> tuple[str, str, str]:
    page = get_page(
        s,
        cache_dir,
        "/webapps/assignment/execute/manageAssignment",
        {"method": "showadd", "content_id": area_id, "course_id": course_bb_id},
    )
    # 表单 nonce（单引号属性，每次渲染不同）与 ajax nonce 是两个值，都要带
    form_m = re.search(r"name='blackboard\.platform\.security\.NonceUtil\.nonce' value='([^']+)'", page.text)
    ajax_m = re.search(r'name="blackboard\.platform\.security\.NonceUtil\.nonce\.ajax"[^>]*value="([^"]+)"', page.text)
    if not form_m or not ajax_m:
        raise RuntimeError("nonce not found on the create-assignment form")
    return page.text, form_m.group(1), ajax_m.group(1)


def create_assignment(
    s: requests.Session,
    cache_dir,
    course_bb_id: str,
    area_id: str,
    name: str,
    points: float,
    instructions: str,
    due: str | None,
    form_nonce: str,
    ajax_nonce: str,
    attachments: list[tuple[str, bytes]],
) -> None:
    fields: dict[str, Any] = {
        "method": (None, "add"),
        "course_id": (None, course_bb_id),
        "content_id": (None, area_id),
        "parent_id": (None, area_id),
        "remove_file_id": (None, ""),
        "temp_content_id": (None, ""),
        "isSinglePopupPage": (None, ""),
        "pageId": (None, ""),
        "contentName": (None, name),
        "name": (None, ""),
        "content_color_title_color": (None, "000000"),
        "content_color": (None, "#000000"),
        "content_desc_text": (None, instructions),
        "textbox_prefix": (None, "content_desc_text"),
        "possible": (None, f"{points:g}"),
        "attemptType": (None, "SINGLE_ATTEMPT"),
        "multipleAttempts": (None, ""),
        "gradingOptions_showToStudentsInMyGrades": (None, "true"),
        "gradingOptions_showToStudentsInMyGradesValue": (None, ""),
        "isAvailable": (None, "true"),
        "blackboard.platform.security.NonceUtil.nonce": (None, form_nonce),
        "blackboard.platform.security.NonceUtil.nonce.ajax": (None, ajax_nonce),
        "bottom_提交": (None, "提交"),
    }
    if due:
        date_part, _, time_part = due.partition(" ")
        fields["due_date_in_use"] = (None, "1")
        fields["dueDate_date"] = (None, date_part)
        fields["dueDate_time"] = (None, time_part or "23:59")
        fields["dueDate_datetime"] = (None, "")
    # 本地附件：FilePicker 行内隐藏域 newFile_attachmentType=L 标记本地文件，文件体命名为 newFile_LocalFile<N>
    for i, (fname, content) in enumerate(attachments):
        fields.setdefault("newFile_attachmentType", (None, "L"))
        fields[f"newFile_LocalFile{i}"] = (fname, content, "application/octet-stream")
    r = s.post(
        BASE_URL + "/webapps/assignment/execute/manageAssignment",
        files=fields,
        headers={
            # 该端点按 X-Requested-With 路由 ajax 提交，缺了 404
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE_URL}/webapps/assignment/execute/manageAssignment?method=showadd&content_id={area_id}&course_id={course_bb_id}",
        },
        timeout=60,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    if not r.ok:
        raise RuntimeError(f"create failed: {r.status_code} {r.text[:200]}")
    try:
        result = r.json()
    except ValueError:
        raise RuntimeError(f"unexpected response: {r.text[:200]}")
    if not any(k in result for k in ("destinationUrl", "htmlOutput", "JSCallBack")):
        raise RuntimeError(f"create not accepted: {r.text[:300]}")


def find_assignment(s, cache_dir, course_bb_id: str, area_id: str, name: str) -> dict[str, Any]:
    page = get_page(
        s, cache_dir, "/webapps/blackboard/content/listContentEditable.jsp",
        {"content_id": area_id, "course_id": course_bb_id, "mode": "reset"},
    ).text
    for m in re.finditer(r'href="/webapps/assignment/uploadAssignment\?content_id=([^&"]+)[^"]*"[^>]*>\s*<span[^>]*>([^<]+)</span>', page):
        if m.group(2).strip() == name:
            return {"content_id": m.group(1), "name": m.group(2).strip()}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course-id", required=True, help="Blackboard course id, e.g. _98497_1")
    parser.add_argument("--area", help="content area name substring, or its content_id (_xxx_1)")
    parser.add_argument("--list-areas", action="store_true", help="list content areas and exit")
    parser.add_argument("--name", help="assignment title")
    parser.add_argument("--points", type=float, help="points possible (满分)")
    parser.add_argument("--instructions", default="", help="assignment instructions (plain text)")
    parser.add_argument("--due", metavar='"YYYY-MM-DD HH:MM"', help="optional due date; omit for no due date")
    parser.add_argument("--attachment", action="append", default=[], metavar="PATH", help="file to attach; repeatable")
    parser.add_argument("--yes", action="store_true", help="actually create (default is dry-run)")
    args = parser.parse_args()

    if not args.list_areas and not (args.area and args.name and args.points is not None):
        raise SystemExit("pass --area/--name/--points (or --list-areas)")

    cache_dir = pku3b_cache_dir()
    s = get_session(cache_dir, auto_refresh=True)

    if args.list_areas:
        for a in list_content_areas(s, cache_dir, args.course_id):
            print(f"{a['content_id']:>14}  {a['name']}")
        return

    area = resolve_area(s, cache_dir, args.course_id, args.area)
    form_html, form_nonce, ajax_nonce = fetch_create_form(s, cache_dir, args.course_id, area["content_id"])
    attachments = []
    for path in args.attachment:
        p = Path(path)
        attachments.append((p.name, p.read_bytes()))

    plan = {
        "course_id": args.course_id,
        "area": area,
        "name": args.name,
        "points": args.points,
        "instructions": args.instructions or "(空)",
        "due": args.due or "(无截止时间)",
        "attachments": [a[0] for a in attachments] or [],
        "write": args.yes,
    }
    if not args.yes:
        plan["result"] = "dry-run (pass --yes to create)"
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    create_assignment(s, cache_dir, args.course_id, area["content_id"],
                      args.name, args.points, args.instructions, args.due,
                      form_nonce, ajax_nonce, attachments)
    found = find_assignment(s, cache_dir, args.course_id, area["content_id"], args.name)
    plan["result"] = "created" if found else "create NOT confirmed — check the content area"
    plan["created"] = found
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if found:
        print(
            f"\n删除：{BASE_URL}/webapps/assignment/execute/manageAssignment"
            f"?method=remove&content_id={found['content_id']}&course_id={args.course_id}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
