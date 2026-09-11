#!/usr/bin/env python3
"""Inspect Blackboard courses by name using pku3b's saved session.

Modes:
  inspect_courses.py                 list my enrolled courses (current/previous semester)
  inspect_courses.py <keyword>       fuzzy-search MY courses by name (fast)
  inspect_courses.py <keyword> --contents
                                     list gradebook columns (content_id, title, due date)
                                     of the uniquely matched course
  inspect_courses.py <keyword> --catalog
                                     search the whole course catalog instead (slow)
  inspect_courses.py --course-id _98497_1 --contents
                                     skip name search, inspect a course directly
  inspect_courses.py <keyword> --grades
                                     per-assignment grade summary (graded/pending/avg)
  inspect_courses.py <keyword> --grades 第2次作业
                                     per-student scores and feedback comments
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from typing import Any

import requests

from pku3b_session import (
    BASE_URL,
    blackboard_session,
    ca_bundle,
    check_session,
    pku3b_cache_dir,
    refresh_session_with_pku3b,
)


COURSE_KEY_RE = re.compile(r"key=([\d_]+)")
MODULE_TITLE_RE = re.compile(r'<span[^>]*class="[^"]*moduleTitle[^"]*"[^>]*>(.*?)</span>', re.S)
COURSE_LISTING_RE = re.compile(r'<ul[^>]*class="[^"]*courseListing[^"]*"[^>]*>(.*?)</ul>', re.S)
ANCHOR_RE = re.compile(r"<a\b[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(text: str) -> str:
    return html.unescape(TAG_RE.sub("", text)).strip()


def api_get(s: requests.Session, cache_dir, path: str, params: dict[str, Any] | None = None) -> Any:
    r = s.get(BASE_URL + path, params=params, timeout=30, allow_redirects=False, verify=ca_bundle(cache_dir))
    if not r.ok:
        raise RuntimeError(f"GET {path} failed: {r.status_code} {r.text[:200]}")
    return r.json()


def paged_get(s: requests.Session, cache_dir, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """GET a list endpoint, following offset paging until exhaustion."""
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        p = dict(params or {})
        p.update({"limit": 100, "offset": offset})
        results = api_get(s, cache_dir, path, p).get("results", [])
        items.extend(results)
        if len(results) < 100:
            return items
        offset += 100


def get_session(cache_dir, auto_refresh: bool) -> requests.Session:
    try:
        s = blackboard_session(cache_dir)
    except RuntimeError as exc:
        raise SystemExit(f"{exc}. Run `python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh`.") from exc
    ok, _ = check_session(cache_dir)
    if not ok:
        if not auto_refresh:
            raise SystemExit("Blackboard session invalid. Run `python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh`.")
        print("session invalid, refreshing via pku3b ...", file=sys.stderr)
        refreshed, msg = refresh_session_with_pku3b()
        if not refreshed:
            raise SystemExit(f"session refresh failed: {msg}")
        s = blackboard_session(cache_dir)
    return s


def list_my_courses(s: requests.Session, cache_dir) -> list[dict[str, Any]]:
    """Scrape the portal home page like pku3b does (courseListing portlets)."""
    r = s.get(
        BASE_URL + "/webapps/portal/execute/tabs/tabAction",
        params={"tab_tab_group_id": "_1_1"},
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    if not r.ok:
        raise RuntimeError(f"portal page failed: {r.status_code}")

    page = r.text
    titles = [(m.start(), strip_tags(m.group(1))) for m in MODULE_TITLE_RE.finditer(page)]
    courses = []
    for ul in COURSE_LISTING_RE.finditer(page):
        portlet_title = next((t for pos, t in reversed(titles) if pos < ul.start()), "")
        if "课程" not in portlet_title and "Courses" not in portlet_title:
            continue
        semester = "当前" if ("当前" in portlet_title or "Current" in portlet_title) else "往期"
        for href, text in ANCHOR_RE.findall(ul.group(1)):
            m = COURSE_KEY_RE.search(href)
            if m:
                courses.append({"id": m.group(1), "name": strip_tags(text), "semester": semester})
    if not courses:
        raise RuntimeError("no courses found on portal page; layout may have changed")
    return courses


def search_catalog(s: requests.Session, cache_dir, page_size: int) -> list[dict[str, Any]]:
    """Page through the public REST course catalog (limit is capped at 100 by Learn)."""
    page_size = max(1, min(page_size, 100))
    courses = []
    offset = 0
    while True:
        data = api_get(
            s,
            cache_dir,
            "/learn/api/public/v1/courses",
            {"limit": page_size, "offset": offset, "fields": "id,courseId,name"},
        )
        results = data.get("results", [])
        courses.extend(results)
        if len(results) < page_size:
            break
        offset += page_size
    return courses


def list_assignments(s: requests.Session, cache_dir, course_id: str) -> list[dict[str, Any]]:
    data = api_get(
        s,
        cache_dir,
        f"/learn/api/public/v1/courses/{course_id}/gradebook/columns",
        {"limit": 200, "fields": "id,name,contentId,dueDate"},
    )
    return data.get("results", [])


def column_grades(s: requests.Session, cache_dir, course_id: str, column_id: str) -> list[dict[str, Any]]:
    return paged_get(
        s,
        cache_dir,
        f"/learn/api/public/v1/courses/{course_id}/gradebook/columns/{column_id}/users",
    )


def column_attempts(s: requests.Session, cache_dir, course_id: str, column_id: str) -> list[dict[str, Any]]:
    return paged_get(
        s,
        cache_dir,
        f"/learn/api/public/v2/courses/{course_id}/gradebook/columns/{column_id}/attempts",
    )


def lookup_users(s: requests.Session, cache_dir, user_ids: list[str]) -> dict[str, dict[str, Any]]:
    users = {}
    for uid in user_ids:
        try:
            users[uid] = api_get(s, cache_dir, f"/learn/api/public/v1/users/{uid}")
        except RuntimeError as exc:
            users[uid] = {"id": uid, "userName": uid, "lookup_error": str(exc)}
    return users


def plain_feedback(attempt: dict[str, Any]) -> str:
    fb = attempt.get("feedback") or ""
    return re.sub(r"\s+", " ", strip_tags(fb)).strip()


def grade_summary_rows(s: requests.Session, cache_dir, course_id: str, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for c in columns:
        grades = column_grades(s, cache_dir, course_id, c["id"])
        scores = [g["score"] for g in grades if g.get("status") == "Graded" and g.get("score") is not None]
        rows.append(
            {
                "column_id": c["id"],
                "content_id": c.get("contentId"),
                "name": c.get("name", ""),
                "graded": len(scores),
                "pending": sum(1 for g in grades if g.get("status") != "Graded"),
                "avg": round(sum(scores) / len(scores), 1) if scores else None,
                "min": min(scores) if scores else None,
                "max": max(scores) if scores else None,
            }
        )
    return rows


def print_grade_summary(course_id: str, rows: list[dict[str, Any]]) -> None:
    print(f"course_id: {course_id}")
    print(f"{'column_id':>12}  {'graded':>6} {'pending':>7} {'avg':>6} {'min':>6} {'max':>6}  title")
    for r in rows:
        stats = f"{r['avg']:6.1f} {r['min']:6.1f} {r['max']:6.1f}" if r["graded"] else f"{'-':>6} {'-':>6} {'-':>6}"
        print(f"{r['column_id']:>12}  {r['graded']:>6} {r['pending']:>7} {stats}  {r['name']}")
    print("\n说明：graded=已评分人数，pending=已提交未评分；加 `--grades <作业关键词>` 看明细与评语", file=sys.stderr)


def print_grade_detail(
    s: requests.Session,
    cache_dir,
    course_id: str,
    column: dict[str, Any],
    as_json: bool,
) -> None:
    column_id = column["id"]
    grades = {g["userId"]: g for g in column_grades(s, cache_dir, course_id, column_id)}
    attempts = column_attempts(s, cache_dir, course_id, column_id)
    latest: dict[str, dict[str, Any]] = {}
    for a in attempts:
        uid = a.get("userId")
        if uid and (uid not in latest or (a.get("attemptDate") or "") > (latest[uid].get("attemptDate") or "")):
            latest[uid] = a

    user_ids = sorted(set(grades) | set(latest))
    names = lookup_users(s, cache_dir, user_ids)

    rows = []
    for uid in user_ids:
        g, a = grades.get(uid), latest.get(uid)
        score = g.get("score") if g and g.get("score") is not None else (a or {}).get("score")
        status = (g or {}).get("status") or ("已提交未评分" if a else "-")
        user = names.get(uid, {})
        feedback = plain_feedback(a) if a else ""
        if not feedback and g:
            feedback = re.sub(r"\s+", " ", strip_tags(g.get("feedback") or "")).strip()
        rows.append(
            {
                "user_id": uid,
                "userName": user.get("userName", uid),
                "name": " ".join(filter(None, [user.get("name", {}).get("family", ""), user.get("name", {}).get("given", "")])),
                "score": score,
                "status": status,
                "feedback": feedback,
                "attemptDate": (a or {}).get("attemptDate"),
                "attempts": sum(1 for x in attempts if x.get("userId") == uid),
            }
        )
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["userName"]))

    if as_json:
        print(json.dumps({"course_id": course_id, "column": column, "grades": rows}, ensure_ascii=False, indent=2))
        return

    scores = [r["score"] for r in rows if r["score"] is not None]
    print(f"# {column.get('name', '')} ({column_id})")
    print(f"{'学号':<14} {'姓名':<10} {'分数':>6}  {'状态':<10} {'提交次数':>4}  评语")
    for r in rows:
        score = f"{r['score']:g}" if r["score"] is not None else "-"
        print(f"{r['userName']:<14} {r['name']:<10} {score:>6}  {r['status']:<10} {r['attempts']:>4}  {r['feedback']}")
    if scores:
        print(f"\n共 {len(rows)} 人，已评分 {len(scores)} 人：avg={sum(scores)/len(scores):.1f} min={min(scores):g} max={max(scores):g}")


def print_my_courses(courses: list[dict[str, Any]]) -> None:
    for c in courses:
        print(f"{c['id']:>12}  [{c['semester']}]  {c['name']}")
    print(f"\n共 {len(courses)} 门；用 `inspect_courses.py <关键词> --contents` 查看作业列表", file=sys.stderr)


def print_matches(matches: list[dict[str, Any]], mine_ids: set[str]) -> None:
    for c in matches:
        star = "★" if c["id"] in mine_ids else " "
        print(f"{c['id']:>12} {star} {c.get('name', '')}")
    print(f"\n共 {len(matches)} 门匹配；★ = 在我的课程里", file=sys.stderr)


def print_contents(course_id: str, columns: list[dict[str, Any]]) -> None:
    gradable = [c for c in columns if c.get("contentId")]
    totals = [c for c in columns if not c.get("contentId")]
    print(f"course_id: {course_id}")
    print(f"{'content_id':>14}  {'column_id':>12}  {'due':<20}  title")
    for c in gradable:
        due = c.get("dueDate") or "-"
        print(f"{c['contentId']:>14}  {c['id']:>12}  {due:<20}  {c.get('name', '')}")
    if totals:
        print(f"\n（另有 {len(totals)} 个非作业成绩列：{'、'.join(c.get('name', '') for c in totals)}）")
    if gradable:
        first = gradable[0]
        print(
            f"\n收取提交示例：\n  python3 AutoPkuTA/scripts/collect_blackboard_submissions.py "
            f"--course-id {course_id} --content-id {first['contentId']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("keyword", nargs="?", help="course name substring (case-insensitive)")
    parser.add_argument("--contents", action="store_true", help="list gradebook columns of the matched course")
    parser.add_argument(
        "--grades",
        nargs="?",
        const="",
        metavar="ASSIGN_KW",
        help="inspect grades: without a value, summarize every assignment column; with a value, "
        "show per-student scores and feedback of the uniquely matched assignment",
    )
    parser.add_argument("--course-id", help="skip name search, inspect this course id directly")
    parser.add_argument("--mine", action="store_true", help=argparse.SUPPRESS)  # kept for compat, now default
    parser.add_argument("--catalog", action="store_true", help="search the whole course catalog instead of my courses (slow)")
    parser.add_argument("--json", action="store_true", help="raw JSON output")
    parser.add_argument("--limit", type=int, default=100, help="catalog page size, capped at 100 (default 100)")
    parser.add_argument("--no-refresh", action="store_true", help="fail instead of auto-refreshing an invalid session")
    args = parser.parse_args()

    cache_dir = pku3b_cache_dir()
    s = get_session(cache_dir, auto_refresh=not args.no_refresh)
    mine = list_my_courses(s, cache_dir)
    mine_ids = {c["id"] for c in mine}

    if args.json:
        out: dict[str, Any] = {"my_courses": mine}
    else:
        out = {}

    if not args.keyword and not args.course_id:
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print_my_courses(mine)
        return

    if args.course_id:
        target = {"id": args.course_id, "name": next((c["name"] for c in mine if c["id"] == args.course_id), "")}
        matches = [target]
    else:
        kw = args.keyword.casefold()
        if args.catalog:
            print("scanning full course catalog (this can take a while) ...", file=sys.stderr)
            pool = search_catalog(s, cache_dir, args.limit)
        else:
            pool = mine
        matches = [c for c in pool if kw in c.get("name", "").casefold()]
        if args.json:
            out["matches"] = matches
        elif not matches:
            print(f"no course matched {args.keyword!r}", file=sys.stderr)
            raise SystemExit(1)
        elif len(matches) > 1 and not (args.contents or args.grades is not None):
            print_matches(matches, mine_ids)
            return
        elif len(matches) > 1:
            print(f"keyword {args.keyword!r} matched {len(matches)} courses, refine it:", file=sys.stderr)
            print_matches(matches, mine_ids)
            raise SystemExit(2)

    course = matches[0]

    if args.grades is not None:
        try:
            gradable = [c for c in list_assignments(s, cache_dir, course["id"]) if c.get("contentId")]
        except RuntimeError as exc:
            raise SystemExit(f"{exc}\n(课程不存在，或当前账号对该课程无助教权限)") from exc
        if not args.grades:
            rows = grade_summary_rows(s, cache_dir, course["id"], gradable)
            if args.json:
                out["course"] = course
                out["grade_summary"] = rows
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                print_grade_summary(course["id"], rows)
            return
        akw = args.grades.casefold()
        cols = [c for c in gradable if akw in c.get("name", "").casefold()]
        if not cols:
            print(f"no assignment matched {args.grades!r}", file=sys.stderr)
            raise SystemExit(1)
        if len(cols) > 1:
            print(f"assignment keyword {args.grades!r} matched {len(cols)} columns, refine it:", file=sys.stderr)
            for c in cols:
                print(f"{c['id']:>12}  {c.get('name', '')}", file=sys.stderr)
            raise SystemExit(2)
        print_grade_detail(s, cache_dir, course["id"], cols[0], args.json)
        return

    if not args.contents:
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print_matches(matches, mine_ids)
        return

    try:
        columns = list_assignments(s, cache_dir, course["id"])
    except RuntimeError as exc:
        raise SystemExit(f"{exc}\n(课程不存在，或当前账号对该课程无助教权限)") from exc
    if args.json:
        out["course"] = course
        out["columns"] = columns
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        title = course.get("name", "")
        print(f"# {title}" if title else f"# {course['id']}")
        print_contents(course["id"], columns)


if __name__ == "__main__":
    main()
