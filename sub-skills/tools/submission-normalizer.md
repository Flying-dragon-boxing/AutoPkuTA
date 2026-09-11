---
name: autopku-ta-tool-submission-normalizer
description: 助教批改前的提交物解压、重命名、格式识别、manifest 生成和异常检测
---

# 提交物标准化

## 目标

把教学网下载的混合提交物整理成稳定、可追溯、可并行批改的目录结构。

## 目录规范

```
normalized/
└── {student_id}_{safe_name}/
    ├── original/       # 原始文件副本或软链接
    ├── work/           # 解压后的工作目录
    ├── metadata.json
    └── checks.json
```

## manifest.json

在作业目录生成：

```json
{
  "course": "",
  "assignment": "",
  "generated_at": "",
  "students": [
    {
      "student_id": "",
      "name": "",
      "status": "submitted|missing|late|invalid",
      "submitted_at": "",
      "raw_files": [],
      "normalized_dir": "",
      "late": false,
      "attempt": 1,
      "notes": []
    }
  ]
}
```

## 处理规则

- 保留原始提交，不删除、不覆盖。
- 文件名安全化只用于工作副本；原始文件名写入 metadata。
- 解压 zip/rar/7z/tar 后记录解压命令和文件列表。
- 如果压缩包内又包含压缩包，只解一层并标记 `nested_archive=true`，除非用户要求继续。
- 同一学生多次提交时默认选择最后一次，同时保留其他 attempt 的索引。

## 分组表规范化

分组表来源可能是截图整理、Excel 宽表、长表、中文列名或英文列名。归档前先转成统一中间格式：

```csv
topic,group_id,member_order,member_name
02 对角化 6,7a,1,黄留鑫
02 对角化 6,7a,2,覃文献
```

优先运行：

```bash
python3 AutoPkuTA/scripts/normalize_group_roster.py 分组.csv \
  -o normalized_groups.csv
```

支持的常见输入：

- 当前宽表：`题目,多少组选,组员1,组员2,组员3`
- 英文宽表：`topic,group_id,member1,member2`
- 长表：`topic,group_id,member_name`
- 简表：`group_id,member_name`

转换后再执行按组归档：

```bash
python3 AutoPkuTA/scripts/group_blackboard_submissions.py \
  --manifest <assignment_dir>/submission_manifest.json \
  --groups normalized_groups.csv \
  --outdir <assignment_dir>_按组
```

如果学生姓名不完全一致，先不要人工猜测大规模替换；生成未匹配清单，优先用教学网 `userName`、邮箱或名单文件核对。

## 异常标记

- `missing`: 名单有学生但无提交。
- `late`: 提交时间晚于截止时间。
- `invalid_format`: 文件类型不符合要求。
- `empty_or_tiny`: 文件为空或明显异常小。
- `unreadable`: PDF/压缩包/代码无法读取。
- `multiple_candidates`: 无法判断应批改哪个文件。

异常不等于零分；只进入复核队列或按 rubric 处理。
