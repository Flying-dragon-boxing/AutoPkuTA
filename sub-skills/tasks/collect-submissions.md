---
name: autopku-ta-task-collect-submissions
description: 助教侧收取 Blackboard/教学网作业提交物，整理名单、迟交状态、附件和 manifest
---

# 任务：收取并整理提交物

## 输入

- 课程名或课程 ID
- 作业名或作业 ID
- 目标目录 `{course}/作业/{assignment}/`
- 可选：名单文件、教学网导出的成绩中心 CSV/XLSX、作业说明附件

## 流程

### 1. 确认目标

列出匹配课程和作业，只在用户确认后开始批量下载。若只有唯一匹配项，可以继续但在摘要中写明匹配依据。

### 2. 获取数据

优先使用 `sub-skills/tools/blackboard-ta.md` 的 API-first 策略：

1. 复用 pku3b 的 IAAA/Blackboard 登录与 cookie store。
2. 根据课程列表和 content tree 定位作业 content_id。
3. 探测 Blackboard public REST gradebook/attempt endpoints。
4. 若 public REST 因 OAuth app/entitlement 不可用，退回到当前登录会话可访问的教师/成绩中心页面接口。
5. 只有 REST 和页面接口都失败时，才建议用户人工导出 ZIP/CSV。

PKU 实例已验证的直接路径见 `sub-skills/tools/blackboard-ta.md` 的“PKU 实测提交物链路”。有 `course_id` 和 `content_id` 时，优先运行：

```bash
python3 AutoPkuTA/scripts/ensure_pku3b_session.py --json

python3 AutoPkuTA/scripts/fetch_assignment_context.py \
  --course-id <course_id> \
  --content-id <content_id> \
  --outdir <assignment_dir> \
  --download-attachments

python3 AutoPkuTA/scripts/collect_blackboard_submissions.py \
  --course-id <course_id> \
  --content-id <content_id> \
  --outdir <assignment_dir>/submissions_api
```

确认清单无误后，如需下载提交附件，再加 `--download`。若会话失效，先运行：

```bash
python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh
```

需要收集：

- 作业标题、截止时间、满分
- 学生名单：姓名、学号、教学网用户名
- 提交状态：已交、未交、迟交、重交次数
- 提交文件及提交时间
- 作业说明、rubric 或教师备注

记录 `reports/acquisition_trace.json`，包含尝试过的 endpoint、HTTP 状态、是否使用官方 REST OAuth、是否退回页面接口。不要记录密码、OAuth secret、完整 cookie。

`fetch_assignment_context.py` 生成 `assignment_context.md/json/html`，并可下载作业说明附件到 `attachments/`，作为后续 rubric 推断和 LLM 批改的首要依据。`collect_blackboard_submissions.py` 生成的 `submission_manifest.json` 至少包含课程、作业、gradebook column、attempts、附件、下载路径和用户查询错误。个别用户信息接口 404 时，不应丢弃其提交；先保留 `userId`，后续用名单或人工映射补全。

### 3. 目录初始化

```
{assignment_dir}/
├── submissions/
├── normalized/
├── grading/
├── review_queue/
├── reports/
└── rubric.md
```

不要删除已有文件。若目录已存在，写入 `reports/collect_rerun_{timestamp}.md` 记录本次新增/覆盖建议。

### 4. 标准化提交物

引用 `sub-skills/tools/submission-normalizer.md`：

- 每名学生一个目录：`{student_id}_{safe_name}/`
- 保留原始文件名，同时建立安全文件名副本或索引。
- 解压 zip/rar/7z/tar，识别嵌套目录。
- 生成 `manifest.json`。

### 5. 异常清单

生成：

- `reports/missing_submissions.csv`
- `reports/late_submissions.csv`
- `reports/invalid_files.csv`
- `reports/manifest_summary.md`

### 6. 可选：按分组归档

若用户提供分组表，不直接假设表格格式。先规范化为中间格式：

```bash
python3 AutoPkuTA/scripts/normalize_group_roster.py <group_roster.xlsx|csv> \
  -o <assignment_dir>/normalized_groups.csv
```

再按组归档：

```bash
python3 AutoPkuTA/scripts/group_blackboard_submissions.py \
  --manifest <assignment_dir>/submission_manifest.json \
  --groups <assignment_dir>/normalized_groups.csv \
  --outdir <assignment_dir>_按组
```

输出 `分组下载清单.csv`。若存在未匹配姓名，报告未匹配项并等待用户确认映射；只在有可靠证据时自动修正常见错字。

## 输出

- 标准化提交目录
- `manifest.json`
- 缺交/迟交/异常清单
- 可选：按组归档目录和 `分组下载清单.csv`
- 下一步建议：是否进入批改、是否需要用户补充 rubric
