#!/usr/bin/env python3
"""Normalize varied grouping rosters into AutoPkuTA's canonical CSV.

Canonical columns:
topic, group_id, member_order, member_name

Supported inputs:
- Current wide format: 题目,多少组选,组员1,组员2,组员3...
- English wide format: topic,group/group_id,member1,member2,...
- Long format: topic,group_id,member_name
- Simple rows: group_id,member_name[,topic]
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pandas as pd


TOPIC_ALIASES = ["topic", "题目", "项目", "任务", "方向", "课题", "problem"]
GROUP_ALIASES = ["group_id", "group", "组别", "组号", "多少组选", "分组", "小组"]
MEMBER_ALIASES = ["member_name", "member", "姓名", "组员", "学生", "student", "name"]
MEMBER_WIDE_PATTERNS = [
    re.compile(r"^组员\s*\d+$"),
    re.compile(r"^member\s*\d+$", re.I),
    re.compile(r"^student\s*\d+$", re.I),
    re.compile(r"^name\s*\d+$", re.I),
]


def find_col(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {str(c).strip(): c for c in columns}
    lower = {str(c).strip().lower(): c for c in columns}
    for a in aliases:
        if a in normalized:
            return normalized[a]
        if a.lower() in lower:
            return lower[a.lower()]
    return None


def is_member_wide_col(col: str) -> bool:
    col = str(col).strip()
    if col in MEMBER_ALIASES:
        return False
    return any(p.match(col) for p in MEMBER_WIDE_PATTERNS) or col.startswith("组员")


def clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def read_input(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8-sig")


def normalize(path: Path) -> list[dict[str, str]]:
    df = read_input(path)
    columns = [str(c).strip() for c in df.columns]
    df.columns = columns

    topic_col = find_col(columns, TOPIC_ALIASES)
    group_col = find_col(columns, GROUP_ALIASES)
    member_col = find_col(columns, MEMBER_ALIASES)
    wide_member_cols = [c for c in columns if is_member_wide_col(c)]

    if not group_col:
        raise SystemExit(f"Cannot identify group column. Columns: {columns}")

    records: list[dict[str, str]] = []
    current_topic = ""

    if member_col and not wide_member_cols:
        for _, row in df.iterrows():
            topic = clean(row.get(topic_col)) if topic_col else ""
            if topic:
                current_topic = topic
            group_id = clean(row.get(group_col))
            member = clean(row.get(member_col))
            if group_id and member:
                records.append(
                    {
                        "topic": current_topic,
                        "group_id": group_id,
                        "member_order": "1",
                        "member_name": member,
                    }
                )
        return records

    if not wide_member_cols:
        # Fallback: any non-topic/group column containing non-empty names is a member column.
        wide_member_cols = [c for c in columns if c not in {topic_col, group_col}]

    for _, row in df.iterrows():
        topic = clean(row.get(topic_col)) if topic_col else ""
        if topic:
            current_topic = topic
        group_id = clean(row.get(group_col))
        if not group_id:
            continue
        for idx, col in enumerate(wide_member_cols, start=1):
            member = clean(row.get(col))
            if member:
                records.append(
                    {
                        "topic": current_topic,
                        "group_id": group_id,
                        "member_order": str(idx),
                        "member_name": member,
                    }
                )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    records = normalize(Path(args.input))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["topic", "group_id", "member_order", "member_name"])
        writer.writeheader()
        writer.writerows(records)
    print(f"normalized {len(records)} members -> {out}")


if __name__ == "__main__":
    main()
