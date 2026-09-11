---
name: autopku-ta-tool-data-parser
description: 解析教学网/Blackboard 助教侧数据，包括 ANSI 输出、名单、成绩中心、提交状态和成绩表
---

# 教学网/Blackboard 数据解析

## ANSI 颜色码清理

```python
import re

def strip_ansi(text):
    """移除 ANSI 颜色码"""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)
```

## pku3b 作业列表解析

```python
import re
import json

def parse_assignments(raw_text):
    """
    解析 pku3b a ls --all-term 输出
    
    Returns:
        [{"course": "课程名", "assignment": "作业名", "status": "状态"}]
    """
    pattern = r'\x1b\[36m\x1b\[1m([^\x1b]+?)\x1b\[0m\x1b\[0m\s+\x1b\[2m>\x1b\[0m\s+\x1b\[36m\x1b\[1m([^\x1b]+?)\x1b\[0m\x1b\[0m\s+\(([^)]+)\)'
    matches = re.findall(pattern, raw_text)
    
    return [
        {"course": c.strip(), "assignment": a.strip(), "status": s.strip()}
        for c, a, s in matches
    ]
```

## 课程列表解析

```python
def parse_courses(raw_text):
    """
    解析 pku3b s -d major show 输出
    提取"已选上"的课程
    """
    pattern = r'已选上.*?\x1b\[32m([^\x1b]+)\x1b\[0m'
    return re.findall(pattern, raw_text)
```

## 公告解析

```python
def parse_announcements(raw_text):
    """
    解析 pku3b ann ls 输出
    
    Returns:
        [{"course": "课程名", "title": "公告标题", "id": "公告ID"}]
    """
    pattern = r'\x1b\[36m([^\x1b]+?)\x1b\[0m\s+>\s+\x1b\[1m([^\x1b]+?)\x1b\[0m\s+\(ID:\s+([^)]+)\)'
    matches = re.findall(pattern, raw_text)
    
    return [
        {"course": c.strip(), "title": t.strip(), "id": i.strip()}
        for c, t, i in matches
    ]
```

## 名单/成绩中心字段归一

```python
FIELD_ALIASES = {
    "student_id": ["学号", "Student ID", "Username", "用户", "用户名", "User ID"],
    "name": ["姓名", "Name", "Full Name", "Student Name"],
    "email": ["邮箱", "Email", "E-mail"],
    "submitted_at": ["提交时间", "Submission Time", "Last Submitted", "Submitted"],
    "status": ["状态", "Status", "Submission Status"],
    "score": ["分数", "Score", "Grade", "成绩"],
    "feedback": ["评语", "Feedback", "Comments", "反馈"],
}

def normalize_headers(headers):
    mapping = {}
    for standard, aliases in FIELD_ALIASES.items():
        for h in headers:
            if h.strip() in aliases:
                mapping[standard] = h
                break
    return mapping
```

## CSV/XLSX 读取

```python
from pathlib import Path
import pandas as pd

def read_table(path):
    path = Path(path)
    if path.suffix.lower() in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8-sig")

def parse_roster(path):
    df = read_table(path)
    mapping = normalize_headers(list(df.columns))
    required = ["student_id", "name"]
    missing = [k for k in required if k not in mapping]
    if missing:
        raise ValueError(f"名单缺少必要字段: {missing}; columns={list(df.columns)}")
    return [
        {
            "student_id": str(row[mapping["student_id"]]).strip(),
            "name": str(row[mapping["name"]]).strip(),
            "email": str(row[mapping["email"]]).strip() if "email" in mapping else "",
        }
        for _, row in df.iterrows()
    ]
```

## 提交状态解析

```python
def parse_submission_rows(path):
    df = read_table(path)
    mapping = normalize_headers(list(df.columns))
    if "student_id" not in mapping:
        raise ValueError("无法定位 student_id 字段，停止解析")

    rows = []
    for _, row in df.iterrows():
        item = {
            "student_id": str(row[mapping["student_id"]]).strip(),
            "name": str(row[mapping["name"]]).strip() if "name" in mapping else "",
            "submitted_at": str(row[mapping["submitted_at"]]).strip() if "submitted_at" in mapping else "",
            "status": str(row[mapping["status"]]).strip() if "status" in mapping else "",
            "score": row[mapping["score"]] if "score" in mapping else None,
            "feedback": str(row[mapping["feedback"]]).strip() if "feedback" in mapping else "",
        }
        rows.append(item)
    return rows
```

## 名单与提交物对齐

```python
def reconcile_roster_and_submissions(roster, submissions):
    roster_ids = {r["student_id"] for r in roster}
    by_id = {s["student_id"]: s for s in submissions}
    result = []
    missing = []
    for student in roster:
        sid = student["student_id"]
        merged = {**student, **by_id.get(sid, {})}
        if sid not in by_id:
            merged["status"] = "missing"
            missing.append(student)
        result.append(merged)
    unmatched = [s for s in submissions if s["student_id"] not in roster_ids]
    return result, missing, unmatched
```

## 成绩合法性检查

```python
def validate_scores(rows, max_score):
    errors = []
    for row in rows:
        score = row.get("score")
        if score is None or score == "":
            continue
        try:
            value = float(score)
        except Exception:
            errors.append((row.get("student_id"), "score_not_numeric", score))
            continue
        if value < 0 or value > max_score:
            errors.append((row.get("student_id"), "score_out_of_range", value))
    return errors
```
