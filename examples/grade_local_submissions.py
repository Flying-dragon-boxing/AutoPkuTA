#!/usr/bin/env python3
"""Demo heuristic grader for Blackboard submission manifests.

This script is not the default AutoPkuTA grading path. For real assignments,
fetch the assignment context, run assignment-specific checks, prepare LLM
grading packets, and let the grader reason from those artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path


SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".py", ".md", ".txt"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}


def safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", str(name)).strip("_") or "unnamed"


def parse_time(value: str) -> str:
    return value or ""


def user_display_name(user: dict) -> str:
    name = user.get("name", {})
    return str(name.get("given") or name.get("family") or user.get("userName") or user.get("id") or "")


def student_key(user: dict, fallback_user_id: str) -> str:
    return safe_name(f"{user.get('userName', fallback_user_id)}_{user_display_name(user)}")


def read_text(path: Path, limit: int = 300_000) -> tuple[str, list[str]]:
    notes: list[str] = []
    ext = path.suffix.lower()
    if ext in SOURCE_EXTS:
        return path.read_text(errors="replace")[:limit], notes

    if ext == ".zip":
        parts = []
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                notes.append(f"zip_entries={len(names)}")
                for name in names:
                    if Path(name).suffix.lower() in SOURCE_EXTS:
                        with zf.open(name) as f:
                            parts.append(f"\n--- {name} ---\n" + f.read(limit).decode(errors="replace"))
                    if sum(len(p) for p in parts) > limit:
                        break
        except Exception as exc:
            notes.append(f"zip_read_error={type(exc).__name__}: {exc}")
        return "\n".join(parts)[:limit], notes

    if ext in ARCHIVE_EXTS:
        notes.append(f"archive_not_extracted={ext}")
        return "", notes

    notes.append(f"unsupported_ext={ext or 'none'}")
    return "", notes


def score_submission(files: list[Path], assignment_kind: str) -> dict:
    notes: list[str] = []
    evidence: list[str] = []
    all_text = []
    file_names = [p.name for p in files]

    for path in files:
        text, file_notes = read_text(path)
        notes.extend([f"{path.name}: {n}" for n in file_notes])
        if text.strip():
            all_text.append(text)
            evidence.append(path.name)

    text = "\n".join(all_text)
    lower = text.lower()
    score = 0
    rubric = []

    has_source_file = any(p.suffix.lower() in SOURCE_EXTS | ARCHIVE_EXTS for p in files)
    has_readable_code = bool(text.strip())
    has_main_or_test = bool(re.search(r"\bmain\s*\(|TEST\s*\(|EXPECT_", text))
    has_cpp_structure = any(tok in text for tok in ["#include", "using namespace", "std::", "class ", "void "])

    score_file = 20 if files and has_source_file else (10 if files else 0)
    score += score_file
    rubric.append({"id": "submission_files", "points": score_file, "max_points": 20, "comments": f"files={file_names}"})

    if assignment_kind == "timer":
        relevance_hits = [
            "timer::start",
            "timer::end",
            "print_all",
            "write_to_json",
            "print_until_now",
            "disable",
            "enable",
            "finish",
        ]
        hit_count = sum(1 for h in relevance_hits if h.lower() in lower)
        score_rel = min(30, hit_count * 4)
        if "timer" in lower:
            score_rel = max(score_rel, 10)
        score += score_rel
        rubric.append({"id": "timer_relevance", "points": score_rel, "max_points": 30, "comments": f"timer feature hits={hit_count}/8"})

        task_mentions = len(set(re.findall(r"\btask\s*([1-9]|10)\b|任务\s*([1-9]|10)", lower)))
        numeric_mentions = len(set(re.findall(r"\b([1-9]|10)\.", text)))
        coverage = max(task_mentions, numeric_mentions)
        score_cov = min(30, coverage * 3)
        score += score_cov
        rubric.append({"id": "test_coverage", "points": score_cov, "max_points": 30, "comments": f"estimated covered cases={coverage}/10"})
    else:
        keywords = ["mpi", "openmp", "timer", "array", "matrix", "test", "benchmark", "parallel", "gtest", "expect"]
        hit_count = sum(1 for h in keywords if h in lower)
        score_rel = min(30, hit_count * 4)
        score += score_rel
        rubric.append({"id": "relevance", "points": score_rel, "max_points": 30, "comments": f"keyword hits={hit_count}"})

        score_cov = 30 if has_main_or_test else (15 if has_readable_code else 0)
        score += score_cov
        rubric.append({"id": "test_or_entrypoint", "points": score_cov, "max_points": 30, "comments": f"main_or_test={has_main_or_test}"})

    score_quality = 0
    if has_readable_code:
        score_quality += 8
    if has_main_or_test:
        score_quality += 5
    if has_cpp_structure:
        score_quality += 5
    if len(text.splitlines()) >= 50:
        score_quality += 2
    score += score_quality
    rubric.append({"id": "readability_structure", "points": score_quality, "max_points": 20, "comments": f"readable={has_readable_code}, main_or_test={has_main_or_test}, lines={len(text.splitlines())}"})

    needs_review = bool(notes) or score < 60 or score > 95 or not has_readable_code
    return {
        "score": min(score, 100),
        "max_score": 100,
        "rubric_items": rubric,
        "needs_review": needs_review,
        "review_reasons": notes + ([] if has_readable_code else ["no_readable_source_extracted"]),
        "evidence_files": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--submissions-dir", required=True, help="Directory containing files/<student_key>/...")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--assignment-kind", default="auto", choices=["auto", "timer", "generic-code"])
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    submissions_dir = Path(args.submissions_dir) / "files"
    outdir = Path(args.outdir)
    grading_dir = outdir / "grading"
    reports_dir = outdir / "reports"
    grading_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    attempts_by_user = defaultdict(list)
    for entry in manifest["attempts"]:
        attempts_by_user[entry["attempt"].get("userId", "")].append(entry)

    assignment_kind = args.assignment_kind
    if assignment_kind == "auto":
        assignment_kind = "timer" if "第6" in manifest["column"].get("name", "") else "generic-code"

    rows = []
    for user_id, entries in attempts_by_user.items():
        entries.sort(key=lambda e: e["attempt"].get("attemptDate", ""))
        entry = entries[-1]
        attempt = entry["attempt"]
        user = entry["user"]
        name = user_display_name(user)
        sid = user.get("userName", user_id)
        key = student_key(user, user_id)
        student_dir = submissions_dir / key
        files = sorted([p for p in student_dir.iterdir() if p.is_file()]) if student_dir.exists() else []
        result = score_submission(files, assignment_kind)

        grading = {
            "student_id": sid,
            "student_name": name,
            "user_id": user_id,
            "course": manifest["course_id"],
            "assignment": manifest["column"].get("name", ""),
            "attempt_id": attempt.get("id", ""),
            "submitted_at": attempt.get("attemptDate", ""),
            "status": "draft",
            "score": result["score"],
            "max_score": result["max_score"],
            "rubric_items": result["rubric_items"],
            "feedback_for_student": "本地草稿评分：已按提交文件、可读代码、相关功能覆盖和结构完整性进行自动检查；最终成绩需助教复核。",
            "private_notes": "Generated by grade_local_submissions.py; do not publish without review.",
            "needs_review": result["needs_review"],
            "review_reasons": result["review_reasons"],
            "evidence_files": result["evidence_files"],
            "all_attempts": [e["attempt"].get("id", "") for e in entries],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        gpath = grading_dir / f"{safe_name(str(sid) + '_' + name)}.grading.json"
        gpath.write_text(json.dumps(grading, ensure_ascii=False, indent=2))

        rows.append(
            {
                "student_id": sid,
                "student_name": name,
                "user_id": user_id,
                "score": result["score"],
                "max_score": result["max_score"],
                "needs_review": result["needs_review"],
                "review_reasons": "; ".join(result["review_reasons"]),
                "attempt_id": attempt.get("id", ""),
                "submitted_at": attempt.get("attemptDate", ""),
                "file_count": len(files),
                "files": " | ".join(p.name for p in files),
                "grading_json": str(gpath),
            }
        )

    report = reports_dir / "grades_draft.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: str(r["student_id"])))

    review = [r for r in rows if r["needs_review"]]
    (reports_dir / "review_queue.json").write_text(json.dumps(review, ensure_ascii=False, indent=2))
    print(json.dumps({"students": len(rows), "needs_review": len(review), "grades": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
