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
on that column (via the instructor grading form,
/webapps/assignment/gradeAssignment/submit; it renders a 500 even on success,
so the script verifies by reading the attempt back). Only when the student has
NO submission does it fall back to a grade-level write (DWR updateGrade +
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
    return clean(strip_tags(grade.get("feedback")))


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


def put_grade_attempt(s: requests.Session, cache_dir, course_bb_id: str, column_bb_id: str, attempt_bb_id: str, user_id: str, score: float, feedback: str | None) -> None:
    """Grade a SPECIFIC attempt: score + feedback attach to that attempt via the
    instructor grading form, then the gradebook cell score is synced via DWR.

    The form endpoint renders a 500 even on success (observed on Learn 3900);
    correctness is enforced by reading the attempt back afterwards."""
    member_uid = membership_uid(s, cache_dir, course_bb_id, pk(user_id))
    page = s.get(
        BASE_URL + "/webapps/assignment/gradeAssignmentRedirector",
        params={"outcomeDefinitionId": column_bb_id.strip("_"), "course_id": course_bb_id, "attempt_id": attempt_bb_id},
        timeout=30,
        allow_redirects=True,
        verify=ca_bundle(cache_dir),
    )
    nonce_m = re.search(r"name=['\"]blackboard\.platform\.security\.NonceUtil\.nonce['\"][^>]*?value=['\"]([^'\"]+)['\"]", page.text)
    if not nonce_m:
        raise RuntimeError("grading form nonce not found")
    fields = {
        "blackboard.platform.security.NonceUtil.nonce": nonce_m.group(1),
        "course_id": course_bb_id,
        "attempt_id": attempt_bb_id,
        "courseMembershipId": member_uid,
        "grade": f"{score:g}",
        "feedbacktext": feedback or "",
        "feedbacktype": "P",
        "gradingNotestext": "",
        "gradingNotestype": "P",
    }
    r = s.post(
        BASE_URL + "/webapps/assignment/gradeAssignment/submit",
        data=fields,
        headers={"Referer": page.url},
        timeout=30,
        allow_redirects=False,
        verify=ca_bundle(cache_dir),
    )
    # 500-on-success is expected; verify by reading the attempt back
    attempt = api_get(s, cache_dir, f"/learn/api/public/v2/courses/{course_bb_id}/gradebook/columns/{column_bb_id}/attempts/{attempt_bb_id}")
    if attempt.get("status") not in ("Completed", "Graded") or float(attempt.get("score") or -1) != float(score):
        raise RuntimeError(f"attempt write not confirmed: status={attempt.get('status')} score={attempt.get('score')} (HTTP {r.status_code})")
    if feedback and clean(plain_feedback({"feedback": attempt.get("feedback")})) != clean(feedback):
        raise RuntimeError("attempt feedback not confirmed after submit")
    put_grade(s, cache_dir, course_bb_id, column_bb_id, user_id, score, None)


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
        put_grade_attempt(s, cache_dir, args.course_id, args.column_id, attempt_id, tgt_id, new_score, new_feedback)
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
