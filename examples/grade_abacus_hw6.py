#!/usr/bin/env python3
"""Draft grader for the ABACUS homework6 assignment.

This assignment-specific script compiles each submission in the corresponding
test directory selected by the last digit of the student id, then creates an
auditable draft grade. It is intentionally conservative and keeps review flags.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


TOPICS = {
    "1": {"name": "vector3", "test": "test_vector3", "exe": "vector3_test", "header": "vector3.h"},
    "2": {"name": "matrix", "test": "test_matrix", "exe": "matrix_test", "header": "matrix.h"},
    "3": {"name": "timer", "test": "test_timer", "exe": "timer_test", "header": "timer.h"},
    "4": {"name": "ndarray", "test": "test_ndarray", "exe": "ndarray_test", "header": "ndarray.h"},
    "5": {"name": "realarray", "test": "test_realarray", "exe": "realarray_test", "header": "realarray.h"},
    "6": {"name": "complexarray", "test": "test_complexarray", "exe": "complexarray_test", "header": "complexarray.h"},
    "7": {"name": "complexmatrix", "test": "test_complexmatrix", "exe": "complexmatrix_test", "header": "complexmatrix.h"},
    "8": {"name": "matrix3", "test": "test_matrix3", "exe": "matrix3_test", "header": "matrix3.h"},
    "9": {"name": "formatter", "test": "test_formatter", "exe": "formatter_test", "header": "formatter.h"},
    "0": {"name": "intarray", "test": "test_intarray", "exe": "intarray_test", "header": "intarray.h"},
}

FEATURES = {
    "vector3": [
        r"Vector3\s*<", r"Vector3\s*<[^>]+>\s*\w+\s*\([^)]*,[^)]*,[^)]*\)", r"\.set\s*\(",
        r"operator|[\w)]\s*\+\s*[\w(]|[\w)]\s*-\s*[\w(]", r"\+=|-=|\*=|/=", r"\.norm2\s*\(|\.norm\s*\(",
        r"\.normalize\s*\(", r"\.dot\s*\(|\*\s*\w+", r"\.cross\s*\(|\^", r"==|!=|<",
    ],
    "matrix": [
        r"\bmatrix\b", r"matrix\s+\w+\s*\([^)]*,[^)]*", r"\.create\s*\(", r"\([^)]*,[^)]*\)\s*=",
        r"\.zero_out\s*\(", r"\.fill_out\s*\(", r"\+|-|\*", r"\*\s*\w+", r"\.trace_on\s*\(", r"transpose\s*\(",
    ],
    "timer": [
        r"timer::start\s*\(", r"timer::end\s*\(", r"timer::print_all\s*\(", r"timer::write_to_json\s*\(",
        r"timer::print_until_now\s*\(", r"timer::disable\s*\(", r"timer::enable\s*\(", r"timer::finish\s*\(",
        r"for\s*\(|while\s*\(", r"json|\.dat|\.txt|ofstream",
    ],
    "ndarray": [
        r"NDArray\s*<", r"NDArray\s*<[^>]+>\s*\w+\s*\([^)]*,[^)]*\)", r"\([^)]*,[^)]*\)\s*=",
        r"NDArray\s*<[^>]+>\s*\w+\s*\([^)]*,[^)]*,[^)]*\)", r"copy|NDArray\s*<[^>]+>\s+\w+\s*\(\s*\w+\s*\)",
        r"=", r"==|!=", r"\.at\s*\(", r"\.front\s*\(|\.back\s*\(", r"\.begin\s*\(|\.end\s*\(|std::string",
    ],
    "realarray": [
        r"realArray", r"realArray\s+\w+\s*\([^)]*,[^)]*,[^)]*\)", r"realArray\s+\w+\s*\([^)]*,[^)]*,[^)]*,[^)]*\)",
        r"\.create\s*\([^)]*,[^)]*,[^)]*\)", r"\.create\s*\([^)]*,[^)]*,[^)]*,[^)]*\)", r"\([^)]*,[^)]*,[^)]*\)\s*=",
        r"=\s*[0-9.]+", r"\.zero_out\s*\(", r"realArray\s+\w+\s*[=(]\s*\w+", r"\([^)]*,[^)]*,[^)]*,[^)]*\)",
    ],
    "complexarray": [
        r"ComplexArray", r"ComplexArray\s+\w+\s*\([^)]*,[^)]*\)", r"\.create\s*\(",
        r"\([^)]*,[^)]*\)\s*=", r"\.zero_out\s*\(", r"\.negate\s*\(", r"\+|-|\*",
        r"\+=|-=|\*=", r"\.dot\s*\(|dot\s*\(", r"\.abs2\s*\(|abs2\s*\(",
    ],
    "complexmatrix": [
        r"ComplexMatrix", r"ComplexMatrix\s+\w+\s*\([^)]*,[^)]*", r"\.create\s*\(", r"\([^)]*,[^)]*\)\s*=",
        r"\.zero_out\s*\(", r"\.set_as_identity_matrix\s*\(", r"\+|-|\*", r"\*\s*\w+",
        r"trace\s*\(", r"transpose\s*\(|conj\s*\(",
    ],
    "matrix3": [
        r"Matrix3", r"Matrix3\s+\w+\s*\([^)]*,[^)]*,[^)]*,[^)]*,[^)]*,[^)]*,[^)]*,[^)]*,[^)]*\)",
        r"\.Identity\s*\(", r"\.Zero\s*\(", r"\.Det\s*\(", r"\.Transpose\s*\(", r"\.Inverse\s*\(",
        r"\+|-|\*", r"\*\s*\w+", r"Vector3\s*<",
    ],
    "formatter": [
        r"FmtCore::format\s*\(", r"FmtCore\s+\w+\s*\(", r"split\s*\(", r"startswith\s*\(|endswith\s*\(",
        r"strip\s*\(|center\s*\(", r"replace\s*\(", r"join\s*\(", r"upper\s*\(|lower\s*\(",
        r"FmtTable", r"<<",
    ],
    "intarray": [
        r"IntArray", r"IntArray\s+\w+\s*\([^)]*,[^)]*\)", r"IntArray\s+\w+\s*\([^)]*,[^)]*,[^)]*\)",
        r"\.create\s*\(", r"\([^)]*,[^)]*\)\s*=", r"=\s*[0-9]+", r"\.zero_out\s*\(",
        r"IntArray\s+\w+\s*[=(]\s*\w+", r"\([^)]*,[^)]*,[^)]*\)", r"\([^)]*,[^)]*,[^)]*,[^)]*\)",
    ],
}


def safe_name(value: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", str(value)).strip("_") or "unnamed"


def user_name(user: dict[str, Any]) -> str:
    name = user.get("name", {})
    return str(name.get("given") or name.get("family") or user.get("userName") or user.get("id") or "")


def student_key(user: dict[str, Any], fallback_user_id: str) -> str:
    return safe_name(f"{user.get('userName', fallback_user_id)}_{user_name(user)}")


def infer_student_id(user: dict[str, Any], files: list[Path], user_id: str) -> str:
    username = str(user.get("userName") or "")
    if re.fullmatch(r"\d{10}", username):
        return username
    for path in files:
        match = re.search(r"(\d{10})", path.name)
        if match:
            return match.group(1)
    return username or user_id


def extract_zip_files(student_dir: Path, work_input: Path) -> list[str]:
    notes = []
    work_input.mkdir(parents=True, exist_ok=True)
    if not student_dir.exists():
        return ["submission_dir_missing"]
    for path in sorted(student_dir.iterdir()):
        if not path.is_file():
            continue
        shutil.copy2(path, work_input / path.name)
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    zf.extractall(work_input / f"{path.stem}_extracted")
                notes.append(f"extracted={path.name}")
            except Exception as exc:
                notes.append(f"zip_extract_failed={path.name}: {type(exc).__name__}: {exc}")
        elif path.suffix.lower() in {".rar", ".7z", ".tar", ".gz"}:
            notes.append(f"archive_not_extracted={path.name}")
    return notes


def source_candidates(root: Path) -> list[Path]:
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in {".c", ".cpp", ".cc", ".cxx"} or re.match(r"main[_\-.]?\d*$", path.name):
            candidates.append(path)
            continue
        if not suffix:
            sample = path.read_text(errors="replace")[:4096]
            if re.search(r"\bint\s+main\s*\(", sample) and (
                "#include" in sample or "std::" in sample or "using namespace" in sample
            ):
                candidates.append(path)
    return sorted(candidates, key=lambda p: (0 if "main" in p.name.lower() else 1, len(str(p))))


def find_source_override(overrides_dir: Path | None, student_id: str, key: str, name: str) -> Path | None:
    if not overrides_dir or not overrides_dir.exists():
        return None
    needles = [safe_name(v) for v in [student_id, key, name] if v]
    matches = []
    for path in overrides_dir.rglob("*"):
        if not path.is_file():
            continue
        haystack = safe_name(str(path))
        if any(needle and needle in haystack for needle in needles):
            matches.append(path)
    candidates = []
    for path in sorted(matches):
        scratch = overrides_dir / ".candidate_probe"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        try:
            shutil.copy2(path, scratch / path.name)
            if source_candidates(scratch):
                candidates.append(path)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    return candidates[0] if candidates else None


def read_text(path: Path) -> str:
    return path.read_text(errors="replace")


def run(cmd: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "cmd": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "returncode": None,
            "stdout": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else "",
            "timeout": True,
        }


def compile_and_run(repo: Path, work: Path, topic: dict[str, str], source: Path | None) -> dict[str, Any]:
    base = work / "source_base"
    if base.exists():
        shutil.rmtree(base)
    shutil.copytree(repo / "source" / "source_base", base)
    if not source:
        return {"compile": {"returncode": None, "stderr": "no source candidate"}, "run": None}
    test_dir = base / topic["test"]
    shutil.copy2(source, test_dir / "main.cpp")
    compile_result = run(["bash", "compile.sh"], test_dir, 60)
    run_result = None
    exe = test_dir / topic["exe"]
    if compile_result["returncode"] == 0 and exe.exists():
        run_result = run([f"./{topic['exe']}"], test_dir, 10)
    return {"compile": compile_result, "run": run_result, "test_dir": str(test_dir)}


def feature_hits(topic_name: str, text: str) -> list[bool]:
    return [bool(re.search(pattern, text, re.I | re.S)) for pattern in FEATURES[topic_name]]


def one_line_comment(topic_name: str, hit_count: int, compile_ok: bool, run_ok: bool, notes: list[str]) -> str:
    if not notes and compile_ok and run_ok and hit_count >= 9:
        return f"{topic_name} 任务覆盖完整，编译运行通过。"
    if any(note == "submission_dir_missing" for note in notes):
        return "本地未下载到提交附件，需按教学网原始提交复核。"
    if any(note.startswith("manual_source_override=") for note in notes):
        return f"使用人工补录源码评分，{topic_name} 任务覆盖较完整且编译运行通过。"
    if any(note.startswith("archive_not_extracted=") for note in notes):
        return "提交为未解压压缩包，当前未能读取有效源码。"
    if not compile_ok:
        return f"{topic_name} 源码可读但编译未通过，需人工查看错误原因。"
    if not run_ok:
        return f"{topic_name} 编译通过但运行失败或超时。"
    if hit_count < 6:
        return f"{topic_name} 编译运行通过，但任务覆盖不足。"
    return f"{topic_name} 主要任务已完成，建议抽查输出正确性。"


def grade_one(student_id: str, name: str, user_id: str, attempt_id: str, files: list[Path], source: Path | None, text: str, topic: dict[str, str], check: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    topic_name = topic["name"]
    hits = feature_hits(topic_name, text)
    hit_count = sum(hits)
    includes_expected = topic["header"].lower() in text.lower() or topic_name.lower() in text.lower()
    has_main = bool(re.search(r"\bint\s+main\s*\(", text))
    wrong_topic = bool(text.strip()) and not includes_expected
    compile_ok = check.get("compile", {}).get("returncode") == 0
    run_info = check.get("run")
    run_ok = bool(run_info and run_info.get("returncode") == 0 and not run_info.get("timeout"))

    format_score = 10
    if not files:
        format_score = 0
    elif not source:
        format_score = 4
    elif not re.search(rf"{re.escape(student_id)}", source.name):
        format_score = 8

    target_score = 15 if includes_expected else (7 if not wrong_topic and source else 0)
    task_score = round(45 * hit_count / 10)
    if wrong_topic:
        task_score = min(task_score, 15)
    build_score = (15 if compile_ok else 0) + (5 if run_ok else 0)
    quality_score = 0
    if has_main:
        quality_score += 3
    if len(text.splitlines()) >= 40:
        quality_score += 2
    if re.search(r"cout|printf|ofstream|print", text, re.I):
        quality_score += 2
    if re.search(r"for\s*\(|while\s*\(", text):
        quality_score += 2
    if not re.search(r"TODO|your code|return 0;\s*}$", text, re.I):
        quality_score += 1
    quality_score = min(10, quality_score)

    score = min(100, format_score + target_score + task_score + build_score + quality_score)
    review_reasons = list(notes)
    if not source:
        review_reasons.append("no_source_candidate")
    if wrong_topic:
        review_reasons.append(f"expected_{topic['header']}_but_not_detected")
    if not compile_ok:
        review_reasons.append("compile_failed")
    if compile_ok and not run_ok:
        review_reasons.append("run_failed_or_timeout")
    if hit_count < 6:
        review_reasons.append(f"low_task_coverage={hit_count}/10")
    if score < 60 or score >= 95:
        review_reasons.append("boundary_score_review")

    comment = one_line_comment(topic_name, hit_count, compile_ok, run_ok, review_reasons)

    return {
        "student_id": student_id,
        "student_name": name,
        "user_id": user_id,
        "assignment": "第6次作业",
        "expected_topic": topic_name,
        "expected_header": topic["header"],
        "attempt_id": attempt_id,
        "status": "draft",
        "score": score,
        "max_score": 100,
        "rubric_items": [
            {"id": "submission_format", "title": "提交格式与可读源码", "max_points": 10, "points": format_score, "evidence": [{"file": str(source) if source else "", "note": "; ".join(notes)}], "comments": "按教学网要求提交 main_xxx.cpp；压缩包/无扩展名会增加复核风险。"},
            {"id": "assigned_class", "title": "按学号尾号完成对应基础类", "max_points": 15, "points": target_score, "evidence": [{"file": str(source) if source else "", "note": f"expected {topic['header']}"}], "comments": "根据学号末位映射到对应 ABACUS 类。"},
            {"id": "task_coverage", "title": "10 个任务覆盖度", "max_points": 45, "points": task_score, "evidence": [{"file": str(source) if source else "", "note": f"feature_hits={hit_count}/10"}], "comments": "用该类的关键接口、构造/访问/运算/输出等特征估计任务覆盖度。"},
            {"id": "build_and_run", "title": "编译和运行", "max_points": 20, "points": build_score, "evidence": [{"file": "compile/run log", "note": f"compile_ok={compile_ok}, run_ok={run_ok}"}], "comments": "在 abacus-for-study 对应 test 目录替换 main.cpp 后运行 compile.sh 和可执行文件。"},
            {"id": "code_quality", "title": "代码组织和演示清晰度", "max_points": 10, "points": quality_score, "evidence": [{"file": str(source) if source else "", "note": f"lines={len(text.splitlines())}, has_main={has_main}"}], "comments": "看主函数、输出、循环/辅助函数和整体可读性。"},
        ],
        "feedback_for_student": f"草稿评分：你应完成学号尾号对应的 {topic_name} 任务。本次检测到任务覆盖约 {hit_count}/10；编译 {'通过' if compile_ok else '未通过'}，运行 {'通过' if run_ok else '未通过或未执行'}。最终分数请以助教复核为准。",
        "one_line_comment": comment,
        "private_notes": "Generated by grade_abacus_hw6.py from assignment PDF, homework6 markdown, compile.sh logs, and static feature checks.",
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "checks": check,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--submissions-dir", required=True)
    parser.add_argument("--repo", default="../abacus-for-study")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--source-overrides-dir")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    submissions_dir = Path(args.submissions_dir) / "files"
    repo = Path(args.repo)
    overrides_dir = Path(args.source_overrides_dir) if args.source_overrides_dir else None
    outdir = Path(args.outdir)
    grading_dir = outdir / "grading"
    reports_dir = outdir / "reports"
    work_dir = outdir / "work"
    grading_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    attempts_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in manifest["attempts"]:
        attempts_by_user[entry["attempt"].get("userId", "")].append(entry)

    rows = []
    for user_id, entries in attempts_by_user.items():
        entries.sort(key=lambda e: e["attempt"].get("attemptDate", ""))
        entry = entries[-1]
        user = entry["user"]
        key = student_key(user, user_id)
        student_dir = submissions_dir / key
        student_work = work_dir / key
        if student_work.exists():
            shutil.rmtree(student_work)
        input_dir = student_work / "input"
        notes = extract_zip_files(student_dir, input_dir)
        files = sorted([p for p in student_dir.iterdir() if p.is_file()]) if student_dir.exists() else []
        student_id = infer_student_id(user, files, user_id)
        name = user_name(user)
        candidates = source_candidates(input_dir)
        if not candidates:
            override = find_source_override(overrides_dir, student_id, key, name)
            if override:
                copied = input_dir / override.name
                shutil.copy2(override, copied)
                files = [copied]
                notes = [note for note in notes if note != "submission_dir_missing"]
                notes.append(f"manual_source_override={override}")
                candidates = source_candidates(input_dir)
        source = candidates[0] if candidates else None
        text = read_text(source) if source else ""
        tail = student_id[-1] if student_id and student_id[-1].isdigit() else ""
        topic = TOPICS.get(tail, TOPICS["0"])
        if not tail:
            notes.append("student_id_not_numeric_tail_unknown")
        check = compile_and_run(repo, student_work, topic, source)
        grading = grade_one(student_id, name, user_id, entry["attempt"].get("id", ""), files, source, text, topic, check, notes)
        gpath = grading_dir / f"{safe_name(student_id + '_' + name)}.grading.json"
        gpath.write_text(json.dumps(grading, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(
            {
                "student_id": student_id,
                "student_name": name,
                "user_id": user_id,
                "expected_topic": topic["name"],
                "score": grading["score"],
                "max_score": 100,
                "needs_review": grading["needs_review"],
                "review_reasons": "; ".join(grading["review_reasons"]),
                "compile_ok": grading["checks"].get("compile", {}).get("returncode") == 0,
                "run_ok": bool(grading["checks"].get("run") and grading["checks"]["run"].get("returncode") == 0),
                "one_line_comment": grading["one_line_comment"],
                "source": str(source) if source else "",
                "grading_json": str(gpath),
            }
        )

    report = reports_dir / "grades_draft.csv"
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: str(r["student_id"])))
    review = [r for r in rows if str(r["needs_review"]) == "True"]
    (reports_dir / "review_queue.json").write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"students": len(rows), "needs_review": len(review), "grades": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
