#!/usr/bin/env python3
"""Prepare per-student evidence packets for LLM-assisted grading."""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path


TEXT_EXTS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".py",
    ".java",
    ".rs",
    ".go",
    ".js",
    ".ts",
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".tex",
}


def safe_name(value: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", str(value)).strip("_") or "unnamed"


def user_name(user: dict) -> str:
    name = user.get("name", {})
    return str(name.get("given") or name.get("family") or user.get("userName") or user.get("id") or "")


def student_key(user: dict, fallback_user_id: str) -> str:
    return safe_name(f"{user.get('userName', fallback_user_id)}_{user_name(user)}")


def read_file_snippet(path: Path, limit: int) -> tuple[str, list[str]]:
    notes: list[str] = []
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        text = path.read_text(errors="replace")
        if len(text) > limit:
            notes.append(f"truncated_to_{limit}_chars")
        return text[:limit], notes

    if ext == ".zip":
        parts: list[str] = []
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                notes.append(f"zip_entries={len(names)}")
                for name in names:
                    suffix = Path(name).suffix.lower()
                    if suffix not in TEXT_EXTS:
                        continue
                    with zf.open(name) as f:
                        body = f.read(limit).decode(errors="replace")
                    parts.append(f"\n### zip:{name}\n\n```text\n{body[:limit]}\n```")
                    if sum(len(part) for part in parts) >= limit:
                        notes.append(f"zip_text_truncated_to_{limit}_chars")
                        break
        except Exception as exc:
            notes.append(f"zip_read_error={type(exc).__name__}: {exc}")
        return "\n".join(parts)[:limit], notes

    notes.append(f"binary_or_unsupported_ext={ext or 'none'}")
    return "", notes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--submissions-dir", required=True, help="Directory containing files/<student_key>/...")
    parser.add_argument("--assignment-context", required=True, help="assignment_context.md or rubric/spec file")
    parser.add_argument("--extra-context", action="append", default=[], help="Additional context file, e.g. extracted PDF text")
    parser.add_argument("--checks-dir", help="Optional directory containing *.checks.json from run_code_checks.py")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--chars-per-file", type=int, default=20000)
    parser.add_argument("--max-files", type=int, default=25)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    context_text = Path(args.assignment_context).read_text(encoding="utf-8", errors="replace")
    for extra in args.extra_context:
        extra_path = Path(extra)
        context_text += f"\n\n# Extra Context: {extra_path.name}\n\n"
        context_text += extra_path.read_text(encoding="utf-8", errors="replace")[:200000]
    submissions_dir = Path(args.submissions_dir) / "files"
    outdir = Path(args.outdir)
    packets_dir = outdir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)

    attempts_by_user: dict[str, list[dict]] = defaultdict(list)
    for entry in manifest["attempts"]:
        attempts_by_user[entry["attempt"].get("userId", "")].append(entry)

    rows: list[dict[str, str]] = []
    for user_id, entries in attempts_by_user.items():
        entries.sort(key=lambda e: e["attempt"].get("attemptDate", ""))
        entry = entries[-1]
        user = entry["user"]
        sid = str(user.get("userName") or user_id)
        name = user_name(user)
        key = student_key(user, user_id)
        student_dir = submissions_dir / key
        files = sorted([p for p in student_dir.iterdir() if p.is_file()]) if student_dir.exists() else []

        notes: list[str] = []
        sections: list[str] = []
        for path in files[: args.max_files]:
            snippet, file_notes = read_file_snippet(path, args.chars_per_file)
            notes.extend([f"{path.name}: {note}" for note in file_notes])
            if snippet:
                fence = "text"
                if path.suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}:
                    fence = "cpp"
                elif path.suffix.lower() == ".py":
                    fence = "python"
                sections.append(f"## File: {path.name}\n\n```{fence}\n{snippet}\n```")
        if len(files) > args.max_files:
            notes.append(f"only_first_{args.max_files}_files_included")
        checks_text = "(not run)"
        if args.checks_dir:
            check_path = Path(args.checks_dir) / f"{safe_name(sid + '_' + name)}.checks.json"
            if check_path.exists():
                checks_text = check_path.read_text(encoding="utf-8", errors="replace")[:50000]
            else:
                checks_text = f"(checks file not found: {check_path})"

        prompt = f"""# LLM Grading Packet

## Role

You are grading exactly one student's submission. Infer the grading criteria from the assignment context. If the assignment context is ambiguous, make a conservative rubric draft and mark `needs_review=true`.

## Required Output

Return JSON matching the AutoPkuTA grading schema:

- `student_id`, `student_name`, `score`, `max_score`, `status`
- `rubric_items`: each item has `id`, `title`, `max_points`, `points`, `evidence`, `comments`
- `feedback_for_student`
- `private_notes`
- `needs_review`
- `review_reasons`

Use only the assignment context and this student's files. Do not compare with other students. Do not invent execution results unless they are present in the evidence.

## Assignment Context

{context_text}

## Student

- student_id: `{sid}`
- student_name: {name}
- user_id: `{user_id}`
- attempt_id: `{entry['attempt'].get('id', '')}`
- submitted_at: `{entry['attempt'].get('attemptDate', '')}`
- all_attempts: `{', '.join(e['attempt'].get('id', '') for e in entries)}`

## File List

{chr(10).join('- ' + p.name for p in files) if files else '(no files found)'}

## Extraction Notes

{chr(10).join('- ' + n for n in notes) if notes else '(none)'}

## Deterministic Checks

```json
{checks_text}
```

## Submission Evidence

{chr(10).join(sections) if sections else '(no readable text extracted)'}
"""
        packet_path = packets_dir / f"{safe_name(sid + '_' + name)}.md"
        packet_path.write_text(prompt, encoding="utf-8")
        rows.append(
            {
                "student_id": sid,
                "student_name": name,
                "user_id": user_id,
                "attempt_id": entry["attempt"].get("id", ""),
                "packet": str(packet_path),
                "file_count": str(len(files)),
                "notes": "; ".join(notes),
            }
        )

    index_path = outdir / "grading_packets_index.csv"
    with index_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["student_id"]))

    print(json.dumps({"students": len(rows), "packets": str(packets_dir), "index": str(index_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
