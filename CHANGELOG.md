# Changelog

## [Unreleased]

### Changed

- `publish_grades.py` 默认行为：分数和评语**优先挂到该生最后一次 attempt**（自动解析，`--attempt-id` 仍可强制指定某次），无提交才回退 grade 层直写；dry-run 计划里显示将写入的 attempt。
- `publish_grades.py` 新增 `--attempt-id`：把分数和评语关联到指定 attempt（走评分表单 `/webapps/assignment/gradeAssignment/submit`，该端点成功也返回 500，脚本以读回验证为准），随后 DWR 同步成绩簿单元格。实测：某课程作业下一名学生两次提交，评分只落在最后一次（Completed 95 + 评语），第一次未动，单元格同步为 95。`--copy-from` 标注为仅测试用途。
- 新增 `scripts/publish_grades.py`：向教学网写入单个学生的成绩与评语。默认 dry-run 打印变更计划，`--yes` 才写入，写后读回验证并输出回滚命令。实例 REST 写被拒（PUT 405 / PATCH 403），改为复刻 Grade Center 网格的 DWR 调用（`updateGrade` + `setComments`，详见 `sub-skills/references/blackboard-rest-api.md` 新增"写入成绩的可行路径"一节）。实测：某课程作业将一名学生 5→100 分并写入评语（含 `--copy-from` 复制），三路读回验证。
- `inspect_courses.py --grades` 明细：无提交的学生回退读取 grade 层评语（之前只读 attempt 评语，会漏掉写给无提交学生的评语）。
- `inspect_courses.py` 新增 `--grades`：按课程 inspect 已发布的成绩与评语——不带值汇总各作业列（已评/未评/avg/min/max），带作业关键词输出逐人学号、姓名、分数、状态、提交次数与评语（HTML 转纯文本）；`--json` 可机器消费。
- 新增 `scripts/inspect_courses.py`：按课程名 inspect——列出我的课程（区分当前/往期学期）、全站课程目录关键词搜索（★ 标注已选课程）、`--contents` 列出课程作业列（`content_id`、标题、截止时间）并给出收取提交命令示例。
- 工程化整理：建立 git 仓库，删除重复的 `skill.md`（保留规范的 `SKILL.md`）。
- 达到 npx-ready 技能包规范：根目录单个 `SKILL.md`，可用 `npx skills add <owner>/AutoPkuTA` 安装。
- `find_pku3b()` 发现顺序改为 `PKU3B_BIN` → `PATH` → 相邻 `../pku3b/target/{release,debug}/`，移除失效的绝对路径硬编码。
- 一次性/课程专用脚本移入 `examples/`（`grade_abacus_hw6.py`、`grade_local_submissions.py`）。
- 新增 README（安装/环境准备/使用）、MIT LICENSE、依赖声明 `requirements.txt`。
