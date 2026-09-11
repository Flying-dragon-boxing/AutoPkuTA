#!/usr/bin/env python3
"""Run assignment-specific build/test commands for each downloaded submission."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


ARCHIVE_EXTS = {".zip"}


def safe_name(value: str) -> str:
    return re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", str(value)).strip("_") or "unnamed"


def user_name(user: dict) -> str:
    name = user.get("name", {})
    return str(name.get("given") or name.get("family") or user.get("userName") or user.get("id") or "")


def student_key(user: dict, fallback_user_id: str) -> str:
    return safe_name(f"{user.get('userName', fallback_user_id)}_{user_name(user)}")


def copy_submission(src: Path, dst: Path, extract_zip: bool) -> list[str]:
    notes: list[str] = []
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return ["submission_dir_missing"]
    for item in sorted(src.iterdir()):
        if not item.is_file():
            continue
        target = dst / item.name
        shutil.copy2(item, target)
        if extract_zip and item.suffix.lower() in ARCHIVE_EXTS:
            try:
                with zipfile.ZipFile(item) as zf:
                    zf.extractall(dst / f"{item.stem}_extracted")
                notes.append(f"extracted={item.name}")
            except Exception as exc:
                notes.append(f"extract_failed={item.name}: {type(exc).__name__}: {exc}")
        elif item.suffix.lower() in {".rar", ".7z", ".tar", ".gz"}:
            notes.append(f"archive_not_extracted={item.name}")
    return notes


def render_command(cmd: str | list[str], variables: dict[str, str]) -> str | list[str]:
    def render(value: str) -> str:
        for key, replacement in variables.items():
            value = value.replace("{" + key + "}", replacement)
        return value

    if isinstance(cmd, list):
        return [render(str(part)) for part in cmd]
    return render(cmd)


def run_one_command(command: dict[str, Any], cwd: Path, variables: dict[str, str], default_timeout: int) -> dict[str, Any]:
    name = str(command.get("name") or "command")
    cmd = render_command(command.get("cmd", ""), variables)
    timeout = int(command.get("timeout", default_timeout))
    shell = isinstance(cmd, str)
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in command.get("env", {}).items()})

    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            shell=shell,
            check=False,
        )
        return {
            "name": name,
            "cmd": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-20000:],
            "stderr": completed.stderr[-20000:],
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "cmd": cmd,
            "returncode": None,
            "stdout": (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else "",
            "timeout": True,
        }
    except Exception as exc:
        return {
            "name": name,
            "cmd": cmd,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "timeout": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--submissions-dir", required=True, help="Directory containing files/<student_key>/...")
    parser.add_argument("--config", required=True, help="JSON file with assignment-specific build/test commands")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    commands = config.get("commands", [])
    if not commands:
        raise SystemExit("config must contain a non-empty commands array")

    submissions_dir = Path(args.submissions_dir) / "files"
    outdir = Path(args.outdir)
    checks_dir = outdir / "checks"
    work_root = outdir / "work"
    checks_dir.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

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
        source_dir = submissions_dir / key
        work_dir = work_root / safe_name(sid + "_" + name)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        notes = copy_submission(source_dir, work_dir, bool(config.get("extract_zip", True)))

        variables = {
            "student_id": sid,
            "student_name": name,
            "user_id": user_id,
            "work_dir": str(work_dir),
        }
        results = [run_one_command(command, work_dir, variables, args.timeout) for command in commands]
        ok = all(result.get("returncode") == 0 and not result.get("timeout") for result in results)
        checks = {
            "student_id": sid,
            "student_name": name,
            "user_id": user_id,
            "attempt_id": entry["attempt"].get("id", ""),
            "work_dir": str(work_dir),
            "notes": notes,
            "commands": results,
            "ok": ok,
        }
        check_path = checks_dir / f"{safe_name(sid + '_' + name)}.checks.json"
        check_path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(
            {
                "student_id": sid,
                "student_name": name,
                "user_id": user_id,
                "ok": str(ok),
                "failed_commands": "; ".join(r["name"] for r in results if r.get("returncode") != 0 or r.get("timeout")),
                "checks_json": str(check_path),
                "notes": "; ".join(notes),
            }
        )

    summary_path = outdir / "checks_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["student_id"]))

    print(json.dumps({"students": len(rows), "summary": str(summary_path), "checks": str(checks_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
