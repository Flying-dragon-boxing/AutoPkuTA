#!/usr/bin/env python3
"""Write a grade + feedback to a Blackboard gradebook column (WRITE operation).

Default is dry-run: it prints exactly what would change and exits.
Pass --yes to actually perform the write. A rollback command is printed after
every successful write.

Mechanism: PKU's Blackboard (Learn 3900) rejects cookie-auth REST writes
(PUT/PATCH -> 405/403), so this script drives the Original Grade Center's own
DWR endpoints, exactly like the browser grid does:

  getJSONData?course_id=..           -> fresh gradebook version (optimistic lock)
  GradebookDWRFacade.updateGrade     -> score  (user identified by course-membership pk)
  GradebookDWRFacade.setComments     -> feedback-to-learner comment

A submission (attempt) is NOT required: grades exist independently of attempts.
The student-visible feedback goes to the gradebook comment (studentComment);
the instructor-only note field is left untouched.

Default behavior: the score and feedback attach to the student's LATEST attempt
on that column via the Grade Center reconcile endpoint (a single POST; write
paths borrowed from pku3b's upstream ta implementation). Only when the student
has NO submission does it fall back to a grade-level write (DWR updateGrade +
setComments). Pass --attempt-id to force a specific attempt instead of the
latest one. The instructor-only note field is never touched.

Examples:
  # grade a student's latest attempt on an assignment (dry-run first)
  python3 publish_grades.py --course-id _98497_1 --column-id _424122_1 \
      --user <学号> --score 95 --feedback "..."
  # same student without any submission -> falls back to grade-level write
  python3 publish_grades.py --course-id _98497_1 --column-id _423373_1 \
      --user <学号> --score 95 --feedback "..."
  # TEST ONLY: copy score and feedback from another student
  python3 publish_grades.py --course-id _98497_1 --column-id _423373_1 \
      --user <学号> --copy-from <源学号> --yes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

import requests

from inspect_courses import api_get, column_attempts, get_session, plain_feedback, strip_tags
from pku3b_session import BASE_URL, ca_bundle, pku3b_cache_dir


USERID_RE = re.compile(r"^_\d+_1$")
WS_RE = re.compile(r"\s+")


def pk(bb_id: str) -> str:
    """'_98497_1' -> '98497' (Blackboard pk used by the Grade Center internals)."""
    return re.sub(r"^_|_1$", "", bb_id)


def clean(text: str | None) -> str:
    return WS_RE.sub(" ", text or "").strip()


def resolve_user(s: requests.Session, cache_dir, ident: str) -> dict[str, Any]:
    """Accept a Blackboard userId (_123_1) or a student id (学号)."""
    if USERID_RE.match(ident):
        return api_get(s, cache_dir, f"/learn/api/public/v1/users/{ident}")
    results = api_get(s, cache_dir, "/learn/api/public/v1/users", {"userName": ident}).get("results", [])
    if not results:
        raise SystemExit(f"user not found: {ident}")
    if len(results) > 1:
        raise SystemExit(f"multiple users match {ident}: {[u.get('id') for u in results]}")
    return results[0]


def get_grade(s: requests.Session, cache_dir, course_id: str, column_id: str, user_id: str) -> dict[str, Any]:
    return api_get(
        s,
        cache_dir,
        f"/learn/api/public/v1/courses/{course_id}/gradebook/columns/{column_id}/users/{user_id}",
    )


def current_feedback(s: requests.Session, cache_dir, course_id: str, column_id: str, user_id: str, grade: dict[str, Any]) -> str:
    """Student-visible feedback: latest attempt feedback, else gradebook comment."""
    attempts = [a for a in column_attempts(s, cache_dir, course_id, column_id) if a.get("userId") == user_id]
    if attempts:
        latest = max(attempts, key=lambda a: a.get("attemptDate") or "")
        text = plain_feedback(latest)
        if text:
            return text
    return clean(strip_tags(grade.get("feedback") or ""))


def dwr_call(s: requests.Session, cache_dir, course_bb_id: str, method: str, params: list[tuple[str, str]], batch_id: int) -> str:
    body = {
        "callCount": "1",
        "batchId": str(batch_id),
        "page": f"/webapps/gradebook/do/instructor/enterGradeCenter?course_id={course_bb_id}",
        "scriptSessionId": "A1B2C3D4E5F60718293A4B5C6D7E8F901",
        "c0-scriptName": "GradebookDWRFacade",
        "c0-methodName": method,
        "c0-id": "c0",
    }
    for i, (typ, val) in enumerate(params):
        body[f"c0-param{i}"] = f"{typ}:{val}"
    r = s.post(
        f"{BASE_URL}/webapps/gradebook/dwr/call/plaincall/GradebookDWRFacade.{method}.dwr",
        data=body,
        headers={
            "Content-Type": "text/plain; charset=UTF-8",
            "Referer": f"{BASE_URL}/webapps/gradebook/do/instructor/enterGradeCenter?course_id={course_bb_id}",
        },
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    if not r.ok:
        raise RuntimeError(f"DWR {method} HTTP {r.status_code}: {r.text[:200]}")
    if "_remoteHandleException" in r.text:
        raise RuntimeError(f"DWR {method} failed: {r.text[:300]}")
    return r.text


def gradebook_version(s: requests.Session, cache_dir, course_bb_id: str) -> int:
    data = s.get(
        f"{BASE_URL}/webapps/gradebook/do/instructor/getJSONData",
        params={"course_id": course_bb_id},
        timeout=60,
        verify=ca_bundle(cache_dir),
    ).json()
    return int(data["version"])


def membership_uid(s: requests.Session, cache_dir, course_bb_id: str, user_pk: str) -> str:
    """The Grade Center write APIs key on the course-membership pk (row uid),
    not the user pk (iuid). Resolve it from the gradebook roster dump."""
    data = s.get(
        f"{BASE_URL}/webapps/gradebook/do/instructor/getJSONData",
        params={"course_id": course_bb_id},
        timeout=60,
        verify=ca_bundle(cache_dir),
    ).json()
    for row in data.get("rows", []):
        first = row[0] if isinstance(row, list) else row
        if str(first.get("iuid")) == user_pk:
            return str(first["uid"])
    raise SystemExit(f"user pk {user_pk} not found in course {course_bb_id} roster")


def put_grade(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str, user_id: str, score: float, feedback: str | None) -> None:
    course_pk, column_pk, user_pk = pk(course_bb_id), pk(column_bb_id), pk(user_id)
    member_uid = membership_uid(s, cache_dir, course_bb_id, user_pk)
    version = gradebook_version(s, cache_dir, course_bb_id)
    dwr_call(
        s, cache_dir, course_bb_id, "updateGrade",
        [("number", course_pk), ("number", str(version)), ("number", f"{score:g}"),
         ("string", f"{score:g}"), ("number", member_uid), ("number", column_pk)],
        batch_id=1,
    )
    if feedback is not None:
        dwr_call(
            s, cache_dir, course_bb_id, "setComments",
            [("number", course_pk), ("string", member_uid), ("string", column_pk),
             ("string", feedback), ("string", ""), ("boolean", "true"), ("boolean", "false")],
            batch_id=2,
        )


def latest_attempt_id(s: requests.Session, cache_dir, course_id: str, column_id: str, user_id: str) -> str | None:
    """The user's most recent attempt on this column, or None if never submitted."""
    attempts = [a for a in column_attempts(s, cache_dir, course_id, column_id) if a.get("userId") == user_id]
    if not attempts:
        return None
    latest = max(attempts, key=lambda a: a.get("attemptDate") or a.get("created") or "")
    return latest["id"]


def reconcile_data(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str) -> dict[str, Any]:
    """Whole-column grading state in one call: attempts, reconciled scores, provisional grades."""
    return api_get(
        s,
        cache_dir,
        "/webapps/gradebook/controller/loadReconcileData",
        {"course_id": course_bb_id, "id": column_bb_id},
    )


def reconcile_nonce(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str) -> str:
    r = s.get(
        BASE_URL + "/webapps/gradebook/controller/reconcileGrades",
        params={"course_id": course_bb_id, "id": column_bb_id},
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    m = (
        re.search(r'name="blackboard\.platform\.security\.NonceUtil\.nonce\.ajax"[^>]*value="([^"]+)"', r.text)
        or re.search(r'value="([0-9a-f-]{36})"[^>]*name="blackboard\.platform\.security\.NonceUtil\.nonce\.ajax"', r.text)
    )
    if not m:
        raise RuntimeError("ajax nonce not found in reconcile page")
    return m.group(1)


def save_reconcile_grade(
    s: requests.Session,
    cache_dir,
    course_bb_id: str,
    column_bb_id: str,
    attempt_bb_id: str,
    score: float,
    feedback: str | None,
) -> None:
    """Write score (+ optional feedback) onto ONE attempt via the Grade Center
    reconcile endpoint. Single POST with sane HTTP semantics (borrowed from
    pku3b's upstream ta implementation)."""
    nonce = reconcile_nonce(s, cache_dir, course_bb_id, column_bb_id)
    params: list[tuple[str, str]] = [
        ("attemptId", attempt_bb_id),
        ("gradableItemId", column_bb_id),
        ("score", f"{score:.2f}"),
        ("hasFeedback", "true" if feedback else "false"),
        ("showStagedFeedbackToStu", "true"),
        ("isDetailPage", "false"),
        ("reconcileMode", "A"),
        ("course_id", course_bb_id),
        ("blackboard.platform.security.NonceUtil.nonce.ajax", nonce),
    ]
    if feedback:
        params.append(("myfeedbacktext", feedback))
    r = s.post(
        BASE_URL + "/webapps/gradebook/controller/saveReconcileGrade",
        data=params,
        headers={
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/webapps/gradebook/controller/reconcileGrades?course_id={course_bb_id}&id={column_bb_id}",
            "X-Requested-With": "XMLHttpRequest",
            "X-Prototype-Version": "1.7",
        },
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    if not r.ok:
        raise RuntimeError(f"saveReconcileGrade failed: {r.status_code} {r.text[:200]}")


def revert_override(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str, user_id: str) -> None:
    """Revert a manual cell override (aggregateGrade.OverrideControl 的 revert 端点)
    so the gradebook cell follows the attempt score instead of a typed-in value."""
    member_uid = membership_uid(s, cache_dir, course_bb_id, pk(user_id))
    attempts = [
        a for a in column_attempts(s, cache_dir, course_bb_id, column_bb_id)
        if a.get("userId") == user_id
    ]
    page_params = {"outcomeDefinitionId": column_bb_id.strip("_"), "course_id": course_bb_id}
    if attempts:
        latest = max(attempts, key=lambda a: a.get("attemptDate") or a.get("created") or "")
        page_params["attempt_id"] = latest["id"]
    page = s.get(
        BASE_URL + "/webapps/assignment/gradeAssignmentRedirector",
        params=page_params,
        timeout=30,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )
    m = re.search(r'id="ajaxNonceId"[^>]*value="([^"]+)"', page.text) or re.search(
        r'value="([0-9a-f-]{36})"[^>]*id="ajaxNonceId"', page.text
    )
    if not m:
        raise RuntimeError("ajaxNonceId not found on grading page")
    r = s.post(
        BASE_URL + "/webapps/assignment/gradeAssignment/revert",
        data={
            "course_id": course_bb_id,
            "courseMembershipId": f"_{member_uid}_1",
            "gradableItemId": column_bb_id,
            "blackboard.platform.security.NonceUtil.nonce.ajax": m.group(1),
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    if not r.ok:
        raise RuntimeError(f"override revert failed: {r.status_code} {r.text[:150]}")


def put_grade_attempt_form(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str, attempt_bb_id: str, user_id: str, score: float, feedback: str | None) -> None:
    """Fallback attempt grading via the instructor grading form
    (/webapps/assignment/gradeAssignment/submit). That endpoint renders a 500
    even on success on this Learn build, so correctness is enforced by reading
    the attempt back afterwards."""
    member_uid = membership_uid(s, cache_dir, course_bb_id, pk(user_id))
    page = s.get(
        BASE_URL + "/webapps/assignment/gradeAssignmentRedirector",
        params={"outcomeDefinitionId": column_bb_id.strip("_"), "course_id": course_bb_id, "attempt_id": attempt_bb_id},
        timeout=30,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )
    nonce_m = re.search(r"name=['\"]blackboard\.platform\.security\.NonceUtil\.nonce['\"][^>]*?value=['\"]([^'\"]*)['\"]", page.text)
    if not nonce_m:
        raise RuntimeError("grading form nonce not found")
    fields = {
        "blackboard.platform.security.NonceUtil.nonce": (None, nonce_m.group(1)),
        "course_id": (None, course_bb_id),
        "attempt_id": (None, attempt_bb_id),
        "courseMembershipId": (None, member_uid),
        "grade": (None, f"{score:g}"),
        "feedbacktext": (None, feedback or ""),
        "feedbacktype": (None, "P"),
        "gradingNotestext": (None, ""),
        "gradingNotestype": (None, "P"),
    }
    # 表单 enctype 是 multipart/form-data；实测 urlencoded 会被静默忽略
    s.post(
        BASE_URL + "/webapps/assignment/gradeAssignment/submit",
        files=fields,
        headers={"Referer": page.url},
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )


def put_grade_attempt(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str, user_id: str, score: float, feedback: str | None, attempt_bb_id: str | None = None) -> None:
    """Grade one attempt via the reconcile endpoint (single POST for score+feedback,
    unlike the grading form which 500s on success). Defaults to the user's LATEST
    attempt; pass attempt_bb_id to force another one. If the reconcile write leaves
    the gradebook cell stale, sync it via DWR."""
    attempts = sorted(
        [a for a in column_attempts(s, cache_dir, course_bb_id, column_bb_id) if a.get("userId") == user_id],
        key=lambda a: a.get("attemptDate") or a.get("created") or "",
    )
    if not attempts:
        raise SystemExit(f"user {user_id} has no attempt on {column_bb_id}; use the grade-level write instead")
    latest_id = attempt_bb_id or attempts[-1]["id"]
    try:
        save_reconcile_grade(s, cache_dir, course_bb_id, column_bb_id, latest_id, score, feedback)
    except RuntimeError as exc:
        print(f"reconcile path failed ({exc}); falling back to the grading form", file=sys.stderr)
        put_grade_attempt_form(s, cache_dir, course_bb_id, column_bb_id, latest_id, user_id, score, feedback)

    attempt = api_get(
        s,
        cache_dir,
        f"/learn/api/public/v2/courses/{course_bb_id}/gradebook/columns/{column_bb_id}/attempts/{latest_id}",
    )
    if float(attempt.get("score") or -1) != float(score):
        raise RuntimeError(f"attempt score not confirmed: {attempt.get('score')} != {score}")
    if feedback and clean(plain_feedback({"feedback": attempt.get("feedback")})) != clean(feedback):
        raise RuntimeError("attempt feedback not confirmed after reconcile write")

    # 有提交时不允许直接改成绩表：若单元格仍是旧的手动覆盖分，还原覆盖让它跟随 attempt
    cell = get_grade(s, cache_dir, course_bb_id, column_bb_id, user_id)
    if float(cell.get("score") or -1) != float(score):
        revert_override(s, cache_dir, course_bb_id, column_bb_id, latest_id)
        cell = get_grade(s, cache_dir, course_bb_id, column_bb_id, user_id)
        if float(cell.get("score") or -1) != float(score):
            raise RuntimeError(
                f"gradebook cell still shows {cell.get('score')} (likely a manual override); "
                "revert it in the Grade Center UI so it follows the attempt"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course-id", required=True, help="Blackboard course id, e.g. _98497_1")
    parser.add_argument("--column-id", required=True, help="gradebook column id, e.g. _423373_1")
    parser.add_argument("--user", required=True, help="target student id (学号) or Blackboard userId (_123_1)")
    parser.add_argument("--score", type=float, help="new score")
    parser.add_argument("--feedback", help="new feedback text (plain or HTML); omit to keep current")
    parser.add_argument("--attempt-id", help="force grading this attempt instead of the user's latest one")
    parser.add_argument("--copy-from", metavar="SRC", help="TEST ONLY: copy score and feedback from this student")
    parser.add_argument("--yes", action="store_true", help="actually perform the write (default is dry-run)")
    args = parser.parse_args()

    if not args.copy_from and args.score is None and args.feedback is None:
        raise SystemExit("nothing to do: pass --score/--feedback or --copy-from")
    if args.copy_from and (args.score is not None or args.feedback is not None):
        raise SystemExit("--copy-from cannot be combined with --score/--feedback")

    cache_dir = pku3b_cache_dir()
    s = get_session(cache_dir, auto_refresh=True)

    target = resolve_user(s, cache_dir, args.user)
    tgt_id = target["id"]
    before = get_grade(s, cache_dir, args.course_id, args.column_id, tgt_id)
    before_fb = current_feedback(s, cache_dir, args.course_id, args.column_id, tgt_id, before)

    if args.copy_from:
        source = resolve_user(s, cache_dir, args.copy_from)
        src_grade = get_grade(s, cache_dir, args.course_id, args.column_id, source["id"])
        new_score = src_grade.get("score")
        new_feedback = current_feedback(s, cache_dir, args.course_id, args.column_id, source["id"], src_grade)
        if new_score is None:
            raise SystemExit(f"source {args.copy_from} has no score to copy")
    else:
        new_score = args.score if args.score is not None else before.get("score")
        new_feedback = args.feedback if args.feedback is not None else before_fb

    attempt_id = args.attempt_id or latest_attempt_id(s, cache_dir, args.course_id, args.column_id, tgt_id)
    plan = {
        "course_id": args.course_id,
        "column_id": args.column_id,
        "target": {"id": tgt_id, "userName": target.get("userName"), "name": target.get("name")},
        "attempt_id": attempt_id or "(无提交，写 grade 层)",
        "before": {"score": before.get("score"), "feedback": before_fb},
        "after": {"score": new_score, "feedback": new_feedback},
    }

    if plan["before"] == plan["after"]:
        plan["result"] = "no-op (nothing would change)"
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if not args.yes:
        plan["result"] = "dry-run (pass --yes to write)"
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    if attempt_id:
        put_grade_attempt(s, cache_dir, args.course_id, args.column_id, tgt_id, new_score, new_feedback, attempt_id)
    else:
        put_grade(s, cache_dir, args.course_id, args.column_id, tgt_id, new_score, new_feedback)
    after = get_grade(s, cache_dir, args.course_id, args.column_id, tgt_id)
    plan["verified"] = {"score": after.get("score"), "feedback": clean(after.get("feedback"))}
    plan["result"] = "written"
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(
        "\n回滚：python3 AutoPkuTA/scripts/publish_grades.py "
        f"--course-id {args.course_id} --column-id {args.column_id} "
        f"--user {args.user} --score {before.get('score')} "
        f"--feedback {json.dumps(before_fb, ensure_ascii=False)} --yes",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
