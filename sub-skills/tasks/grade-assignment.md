---
name: autopku-ta-task-grade-assignment
description: 按 rubric 批量批改学生提交物，运行确定性检查，生成 grading.json、反馈和复核队列
---

# 任务：批量批改作业

## 前置条件

- 已执行 `collect-submissions.md`，或已有等价的 `manifest.json`
- 已抓取 `assignment_context.md`；若没有，先从教学网页面或作业附件提取
- 已有 `rubric.md`；若没有，先根据作业说明生成草案并请用户确认
- 明确总分、迟交政策、可接受文件格式

## 流程

### 1. 读取作业说明并生成本次 rubric

引用 `sub-skills/references/grading-schema.md`，使用统一 `grading.json` 结构。

先读 `assignment_context.md`、作业附件、教师备注和提交文件样例。不要复用上一回作业的硬编码标准；每次作业都要重新判断：

- 本次要求学生提交什么产物
- 是否是代码、报告、数据、实验结果或混合提交
- 可接受的文件格式和命名要求
- 是否存在明确测试任务、性能要求、输出格式或报告问题
- 教学网页面写明的满分、截止时间、重交策略

若没有正式 rubric，基于作业说明生成 `rubric.md` 草案，并在草稿评分中标记 `needs_review=true`。解析 rubric 时确认：

- 总分与各项分值之和一致
- 每项评分有可观察证据
- 迟交/缺交/格式错误扣分规则明确
- 是否允许部分分、重交、人工豁免

### 2. 代码作业先尝试跑起来

代码作业默认先建立本次作业专用 `checks_config.json`，把“怎么跑”从评分逻辑中分离出来。常见共性：

- 解压提交物，保留原始文件。
- 识别语言和构建方式：`Makefile`、`CMakeLists.txt`、单个 `.cpp`、Python 脚本、Jupyter/PDF 混合提交。
- 若作业提供样例输入、测试脚本或要求输出格式，优先使用这些测试。
- 若没有测试脚本，写最小 smoke test：能否编译/启动、核心接口是否存在、样例规模能否运行。
- 运行命令必须限时，保留 stdout/stderr，不把失败直接等同于 0 分，交给 LLM 结合源码判断部分分。

`checks_config.json` 示例：

```json
{
  "extract_zip": true,
  "commands": [
    {"name": "list", "cmd": "find . -maxdepth 3 -type f | sort", "timeout": 5},
    {"name": "compile", "cmd": "g++ -std=c++17 -O2 *.cpp -o main", "timeout": 20},
    {"name": "smoke", "cmd": "./main", "timeout": 10}
  ]
}
```

运行：

```bash
python3 AutoPkuTA/scripts/run_code_checks.py \
  --manifest <assignment_dir>/submission_manifest.json \
  --submissions-dir <assignment_dir> \
  --config <assignment_dir>/checks_config.json \
  --outdir <assignment_dir>_checks
```

对每份提交先执行可重复检查，并把结果作为证据：

- 文件存在性、格式、页数/字数/命名
- 代码作业：编译、测试、运行时间、输出 diff
- 文档作业：PDF 可读性、页数、图片/表格提取
- 数据作业：CSV/XLSX 字段、行数、缺失值
- 查重线索：文件 hash、相似文件名、可疑相同输出

检查结果写入 `grading/{student}/checks.json`。

### 3. 生成 LLM 批改包并逐份评分

引用 `sub-skills/runtime/create-agent.md` 和 `sub-skills/tools/grading-agent-helpers.md`。

先生成每名学生的批改包：

```bash
python3 AutoPkuTA/scripts/prepare_llm_grading_packets.py \
  --manifest <assignment_dir>/submission_manifest.json \
  --submissions-dir <assignment_dir> \
  --assignment-context <assignment_dir>/assignment_context.md \
  --extra-context <assignment_dir>/attachments/<assignment.pdf.txt> \
  --checks-dir <assignment_dir>_checks/checks \
  --outdir <assignment_dir>_llm_packets
```

为每名学生或每个提交创建 grader agent。Agent 只读取该学生提交、作业说明、rubric、checks，不读取其他学生分数；查重/横向比较由 reviewer 统一处理。LLM 可以根据本次作业要求自主判断评分点，但必须写出证据和不确定性。

Grader 输出：

- `grading/{student}/grading.json`
- `grading/{student}/feedback.md`
- 证据引用：文件名、页码/行号、测试名、输出片段
- `needs_review` 与原因

### 3a. 本地草稿批改 demo

`grade_local_submissions.py` 只是 demo，展示如何输出 `grading.json` 和 `grades_draft.csv`，不作为默认评分方式。只有在用户明确接受某个启发式标准时才运行：

```bash
python3 AutoPkuTA/scripts/grade_local_submissions.py \
  --manifest <assignment_dir>/submission_manifest.json \
  --submissions-dir <assignment_dir> \
  --outdir <assignment_dir>_本地批改 \
  --assignment-kind auto
```

脚本输出每名学生的 `grading/*.grading.json`、`reports/grades_draft.csv` 和 `reports/review_queue.json`。这是可追溯的草稿评分，不是最终成绩；不同作业不能直接套用同一个 `assignment-kind`。

### 4. 汇总与复核队列

生成：

- `reports/grades_draft.csv`
- `reports/score_distribution.md`
- `review_queue/high_risk.json`
- `review_queue/random_sample.json`

强制进入复核队列：

- 分数低于及格线或高于 95%
- `needs_review=true`
- 缺交/迟交/格式错误但有可读内容
- 测试失败但人工看起来可能有部分分
- 疑似抄袭或相似度异常

## 输出

批改结束后只生成草稿成绩，不发布教学网。向用户报告：已批改人数、缺交人数、复核队列大小、成绩表路径。
