---
name: autopku-ta
description: AutoPkuTA - 面向北大教学网/Blackboard 助教的作业收取、批改、复核、反馈生成和成绩导出/发布技能
---

# AutoPkuTA

面向助教批改作业的 PKU 教学网/Blackboard 工作流。它复用 AutoPku 的运行时适配、pku3b/PDF/数据解析基础设施，但目标从“学生完成并提交作业”改为“助教收取提交物、按 rubric 批改、复核并生成反馈、导出或发布成绩”。

## 使用方式

直接描述助教任务：

| 用户意图示例 | 执行任务 |
|-------------|---------|
| "收取并整理并行计算第一次作业提交" | 同步作业提交物并建立批改目录 |
| "按 rubric 批改 hw1，先不发布成绩" | 批量评分、生成反馈、等待人工复核 |
| "复核低于 60 分和被标记的问题提交" | 只复核高风险样本 |
| "导出成绩表和反馈压缩包" | 生成 CSV/XLSX/反馈文件，必要时辅助发布 |

## 核心原则

1. **API-first 获取提交物**：优先复用 pku3b 的 Blackboard 登录会话探测 REST/页面接口，自动下载作业提交物；人工导出只作为最后兜底。
2. **不自动发布成绩**：任何上传成绩、发布反馈、覆盖教学网状态的动作必须先向用户确认。
3. **评分可追溯**：每份作业保留 `grading.json`、反馈文本、引用证据、rubric 命中项和人工复核状态。
4. **先规则后模型**：先用 deterministic checks 检查格式、文件、编译/运行、查重线索、迟交状态，再让评阅 agent 给出 rubric 评分。
5. **高风险必复核**：低分、满分、疑似抄袭、运行失败但代码接近正确、模型置信度低、rubric 缺失的提交必须进入人工复核列表。
6. **最小权限**：默认只下载和本地生成结果；发布成绩、批量上传反馈前二次确认。

## 环境依赖

脚本依赖 Python 3.10+、`requests`、`pandas`，以及已登录的 [pku3b](https://github.com/sshwy/pku3b) CLI（pku3b 按 `PKU3B_BIN` 环境变量 → `PATH` → 相邻 `../pku3b/target/` 的顺序自动查找）。缺少 Python 依赖时在技能目录运行 `uv venv && uv pip install -r requirements.txt`；会话失效时先运行 `scripts/ensure_pku3b_session.py`。

## 工作目录约定

```
{course}/
├── 作业/
│   └── {assignment}/
│       ├── submissions/        # 原始提交，按学生归档
│       ├── normalized/         # 解压/重命名/格式标准化后内容
│       ├── grading/            # 每名学生的 grading.json 与反馈
│       ├── review_queue/       # 需人工复核的样本索引
│       ├── reports/            # 汇总统计、成绩表、发布前核对表
│       └── rubric.md           # 本次作业评分细则
└── 助教记录/
    └── grading_log.md
```

## 任务路由

```
收取/同步提交
  -> 引用 sub-skills/tasks/collect-submissions.md

批改/评分/生成反馈
  -> 引用 sub-skills/tasks/grade-assignment.md

复核/抽检/发布前检查
  -> 引用 sub-skills/tasks/review-and-export.md
```

## 基础设施索引

| 类型 | 文件 | 用途 |
|------|------|------|
| Runtime | `sub-skills/runtime/_detect.md` | 检测 Claude/Codex/Kimi/Fallback |
| Runtime | `sub-skills/runtime/create-agent.md` | 创建并行 agent 的统一接口 |
| Tool | `sub-skills/tools/pku3b-setup.md` | pku3b 安装、登录、只读命令参考 |
| Tool | `sub-skills/tools/blackboard-ta.md` | 助教侧 REST/页面接口探测、提交物下载、上传确认策略 |
| Tool | `sub-skills/tools/data-parser.md` | 教学网输出、名单、成绩表解析 |
| Tool | `sub-skills/tools/pdf-reader.md` | PDF 文本、表格和图片提取 |
| Tool | `sub-skills/tools/submission-normalizer.md` | 提交物解压、重命名、manifest 生成 |
| Tool | `sub-skills/tools/grading-agent-helpers.md` | Collector/Grader/Reviewer/Exporter prompt 模板 |
| Reference | `sub-skills/references/pku3b-source-map.md` | pku3b 源码中可复用的认证、cookie、课程/作业实现位置 |
| Reference | `sub-skills/references/blackboard-rest-api.md` | Blackboard REST API 认证模型和助教侧候选 endpoint |
| Reference | `sub-skills/references/grading-schema.md` | `grading.json`、成绩表和反馈字段规范 |
| Reference | `sub-skills/references/checks-config-examples.md` | 常见代码作业编译/运行检查配置模板 |

## 脚本入口

| 脚本 | 用途 |
|------|------|
| `scripts/ensure_pku3b_session.py` | 检查或刷新 pku3b 保存的 Blackboard 登录会话 |
| `scripts/inspect_courses.py` | 按课程名 inspect：列出我的课程、全站目录搜索、列出课程的作业列（`content_id`、标题、截止时间）；`--grades` 汇总/明细查看各作业已发布的分数与评语 |
| `scripts/publish_grades.py` | 写入单个学生的成绩与评语：**默认优先挂到该生最后一次 attempt**（评分表单接口），无提交才回退 grade 层直写（DWR）；默认 dry-run，`--yes` 才写入并输出回滚命令；`--attempt-id` 可强制指定 attempt；`--copy-from` 仅测试用途 |
| `scripts/fetch_assignment_context.py` | 从教学网页面提取作业说明、可见文本和作业附件 |
| `scripts/collect_blackboard_submissions.py` | 用 `course_id` 和 `content_id` 拉取提交清单，可选下载附件 |
| `scripts/normalize_group_roster.py` | 把不同形态的分组表转换为规范长表 |
| `scripts/group_blackboard_submissions.py` | 根据规范分组表把提交物按组归档 |
| `scripts/run_code_checks.py` | 按本次作业配置隔离运行编译/测试/脚本检查 |
| `scripts/prepare_llm_grading_packets.py` | 为每名学生生成含作业说明、源码片段和检查日志的 LLM 批改包 |

`examples/` 下是一次性/课程专用脚本（如 `grade_abacus_hw6.py`、`grade_local_submissions.py`），仅作参考实现，不得作为默认最终评分标准。

## 标准流程

### 1. 收取提交物

引用 `sub-skills/tasks/collect-submissions.md`：

1. 先运行 `scripts/ensure_pku3b_session.py`，确认可复用 pku3b 的 cookie store。
2. 定位课程与作业：优先用 `scripts/inspect_courses.py <课程名关键词> --contents` 解析出 `course_id` 与 `content_id`；若用户给出教学网作业链接，也可以直接提取。
3. 用 `scripts/fetch_assignment_context.py` 抓取页面作业描述。
4. 复用 pku3b 登录会话探测 REST/页面接口，下载提交物、名单、迟交状态和附件说明。
5. 解压并标准化学生目录。
6. 生成 `manifest.json`、缺交表、异常提交表。

### 2. 批量批改

引用 `sub-skills/tasks/grade-assignment.md`：

1. 先读教学网页面作业描述、附件和提交物样例，推断本次作业的评分维度；rubric 缺失时先生成草案。
2. 代码作业优先写本次作业专用的 `checks_config.json`，用 `scripts/run_code_checks.py` 隔离编译/运行/测试。
3. 用 `scripts/prepare_llm_grading_packets.py` 为每名学生生成批改包。
4. 让 grader agent 根据作业描述、检查日志和源码证据逐份自主评分。
5. 输出每名学生的 `grading.json` 和反馈文件。
6. 汇总分数分布与复核队列。

### 3. 复核与导出

引用 `sub-skills/tasks/review-and-export.md`：

1. 优先复核低分、满分、疑似异常和抽样提交。
2. 生成发布前核对表。
3. 用户确认后导出 CSV/XLSX/反馈压缩包；若需要上传教学网，再二次确认。
4. 向教学网写入成绩用 `scripts/publish_grades.py`（默认 dry-run 只打印变更计划；逐条确认后加 `--yes` 执行，每次写入输出回滚命令；`--copy-from` 可复制他人分数+评语）。不要求学生有提交记录。
5. 成绩发布后，用 `scripts/inspect_courses.py <课程名> --grades`（汇总）与 `--grades <作业关键词>`（逐人分数+评语）核对线上数据与本地 `grading.json` 一致。

## 关键安全边界

- 不绕过教学网权限；只访问当前账号正常可见的课程、作业、提交物和成绩列。
- 不根据学生姓名、学号以外的个人信息调整评分。
- 不在没有 rubric 的情况下批量给最终分；若 rubric 缺失，先生成草案并要求用户确认。
- 不默认覆盖已有 `grading.json`；如需重评，写入新版本或备份旧文件。
- 不删除原始提交物；清理临时文件前确认。
- 发布成绩和反馈前必须输出待发布摘要：课程、作业、人数、分数范围、异常数量、目标上传位置。
