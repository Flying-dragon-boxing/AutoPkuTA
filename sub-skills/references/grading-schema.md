# 批改数据结构规范

## grading.json

每名学生一个文件：`grading/{student_id}_{safe_name}/grading.json`。

```json
{
  "student_id": "",
  "student_name": "",
  "course": "",
  "assignment": "",
  "max_score": 100,
  "score": 0,
  "late_penalty": 0,
  "status": "draft|reviewed|final",
  "rubric_items": [
    {
      "id": "correctness",
      "title": "Correctness",
      "max_points": 60,
      "points": 0,
      "evidence": [
        {
          "file": "",
          "location": "page 1 | line 20 | test case name",
          "note": ""
        }
      ],
      "comments": ""
    }
  ],
  "feedback_for_student": "",
  "private_notes": "",
  "needs_review": false,
  "review_reasons": [],
  "review_history": [
    {
      "time": "",
      "reviewer": "",
      "change": "",
      "reason": ""
    }
  ],
  "generated_at": ""
}
```

## grades CSV

最小字段：

```csv
student_id,name,score,max_score,status,late,needs_review,feedback_file
```

发布到教学网前，根据成绩中心导出文件添加系统要求的列名，不直接猜测隐藏 ID。

`scripts/grade_local_submissions.py` 的草稿 CSV 还会保留 `attempt_id`、`attempt_date`、`student_key`、`files`、`review_reasons` 和 `grading_file` 等审计字段。发布或汇总时可以从这些字段裁剪出教学网需要的列，但不要丢弃原始草稿表。

## feedback.md

面向学生，语气专业、具体、可行动：

```markdown
# {assignment} Feedback

Score: {score}/{max_score}

## Strengths
- ...

## Deductions
- ...

## Suggestions
- ...
```

避免出现其他学生信息、内部复核备注、模型置信度等不应公开内容。
