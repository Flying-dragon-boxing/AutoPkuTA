# AutoPkuTA

面向北京大学教学网（Blackboard）助教的作业收取、批改、复核、成绩发布与导出技能（Agent Skill）。

本项目是 [AutoPku](https://github.com/ICUlizhi/AutoPku)（[autopku.com](https://autopku.com/)）的助教侧衍生：AutoPku 面向学生端完成作业，AutoPkuTA 面向助教端批改作业。底层复用 [pku3b](https://github.com/sshwy/pku3b) 的登录会话与教学网访问能力。

## 功能总览

| 阶段 | 能力 | 主要脚本 |
|------|------|---------|
| 定位 | 按课程名查课程/作业，拿 `course_id`、`content_id`、成绩列 | `inspect_courses.py` |
| 收取 | 拉取提交清单、下载附件、生成分组与 manifest | `collect_blackboard_submissions.py` 等 |
| 批改 | 作业说明抓取、隔离编译/运行检查、LLM 批改包 | `fetch_assignment_context.py`、`run_code_checks.py`、`prepare_llm_grading_packets.py` |
| 发布 | 写入分数与评语（**优先挂最后一次提交**，写前 dry-run、写后验证、可回滚） | `publish_grades.py` |
| 核对 | 读回已发布的分数与评语（汇总/逐人），与本地记录比对 | `inspect_courses.py --grades` |
| 导出 | CSV/XLSX/反馈压缩包（由 agent 按工作流生成） | — |

完整的原则、安全边界与标准流程见 [`SKILL.md`](./SKILL.md)。

## 安装

需要 Node.js（npx）。把技能装到任意已检测到的编码 agent（Claude Code / Codex / Kimi Code 等）：

```bash
# 从 GitHub 安装
npx skills add flying-dragon-boxing/AutoPkuTA

# 或从本地路径安装
npx skills add /path/to/AutoPkuTA
```

手动安装：把整个目录复制到 `~/.agents/skills/autopku-ta/`（或你的 agent 的技能目录），保持 `SKILL.md` 位于该目录根部。

## 环境准备

脚本依赖 Python 3.10+、`requests`、`pandas`，以及已登录的 pku3b CLI：

```bash
cd AutoPkuTA
uv venv && uv pip install -r requirements.txt   # 任何虚拟环境都推荐用 uv
pku3b init                                      # 交互式登录教学网，只需一次
```

pku3b 的查找顺序：`PKU3B_BIN` 环境变量 → `PATH` → 相邻源码仓库 `../pku3b/target/{release,debug}/pku3b`。

## 工作流程（端到端）

> 所有脚本在仓库根目录运行。写入类操作（发布成绩）**默认 dry-run**：先不带 `--yes` 看变更计划，确认后再加 `--yes` 执行，每次写入都会输出回滚命令。

### 0. 会话检查

```bash
python3 scripts/ensure_pku3b_session.py            # 检查；失效时加 --refresh 自动刷新
```

### 1. 定位课程与作业

```bash
python3 scripts/inspect_courses.py                      # 列出"我的课程"（区分当前/往期学期）
python3 scripts/inspect_courses.py 并行程序设计          # 按名字匹配课程
python3 scripts/inspect_courses.py 并行程序设计 --contents # 列出作业列：content_id、标题、截止时间
python3 scripts/inspect_courses.py 并行程序设计 --grades   # 各作业已评/未评人数与分数分布
```

`--contents` 会给出可直接复制的收取命令。

### 2. 收取提交

```bash
python3 scripts/collect_blackboard_submissions.py \
    --course-id _98497_1 --content-id _1597534_1 \
    --outdir 作业/hw3/submissions --download
python3 scripts/fetch_assignment_context.py \
    --course-id _98497_1 --content-id _1597534_1 \
    --outdir 作业/hw3/context --download-attachments
```

分组作业先 `normalize_group_roster.py` 转规范分组表，再 `group_blackboard_submissions.py` 按组归档。

### 3. 检查与批改

```bash
python3 scripts/run_code_checks.py --manifest ... --submissions-dir ... --config checks_config.json --outdir 作业/hw3/checks
python3 scripts/prepare_llm_grading_packets.py --manifest ... --submissions-dir ... \
    --assignment-context 作业/hw3/context/assignment_context.md --checks-dir 作业/hw3/checks --outdir 作业/hw3/packets
```

然后由评阅 agent 逐份评分，产出每名学生的 `grading.json` 与反馈文件（见 `SKILL.md` 的批量批改流程）。`examples/` 下的课程专用脚本仅供参考，不是评分标准。

### 4. 人工复核

低分、满分、疑似异常、运行失败但代码接近正确的提交进复核队列（`review_queue/`），人工确认后再进入发布。

### 5. 发布成绩

```bash
# dry-run：打印 before → after 变更计划（分数、评语、目标 attempt）
python3 scripts/publish_grades.py --course-id _98497_1 --column-id _424122_1 \
    --user <学号> --score 95 --feedback "4-1 …"

# 确认后真正写入
python3 scripts/publish_grades.py --course-id _98497_1 --column-id _424122_1 \
    --user <学号> --score 95 --feedback "4-1 …" --yes
```

语义：**默认优先把分数和评语挂到该生最后一次 attempt**（多次补交时不会评错旧版本）；没有提交记录时才写 grade 层。`--attempt-id` 可强制指定某次 attempt；写后自动读回验证，stderr 给出回滚命令。`--copy-from` 仅测试用途。

### 6. 发布后核对

```bash
python3 scripts/inspect_courses.py 并行程序设计 --grades 第3次作业   # 逐人分数+评语读回
```

与本地 `grading.json` 比对，确认线上数据无误。发现错评用第 5 步重新发布（先 dry-run）即可覆盖。

## 脚本一览

| 脚本 | 用途 |
|------|------|
| `scripts/ensure_pku3b_session.py` | 检查或刷新 pku3b 保存的 Blackboard 登录会话 |
| `scripts/inspect_courses.py` | 按课程名 inspect：我的课程、目录搜索、作业列、`--grades` 汇总/明细读回分数评语 |
| `scripts/collect_blackboard_submissions.py` | 用 `course_id`+`content_id` 拉取提交清单，可选下载附件 |
| `scripts/fetch_assignment_context.py` | 从教学网页面提取作业说明、可见文本和作业附件 |
| `scripts/normalize_group_roster.py` | 把不同形态的分组表转换为规范长表 |
| `scripts/group_blackboard_submissions.py` | 根据规范分组表把提交物按组归档 |
| `scripts/run_code_checks.py` | 按本次作业配置隔离运行编译/测试/脚本检查 |
| `scripts/prepare_llm_grading_packets.py` | 为每名学生生成含作业说明、源码片段和检查日志的 LLM 批改包 |
| `scripts/publish_grades.py` | 写入单个学生的成绩与评语（dry-run → `--yes`，写后验证 + 回滚命令） |
| `examples/grade_abacus_hw6.py` 等 | 一次性/课程专用脚本，仅参考实现，不得作为默认评分标准 |

## 目录结构

```
AutoPkuTA/
├── SKILL.md                  # 技能入口（agent 读取此文件）
├── scripts/                  # 可复用的命令行脚本
├── sub-skills/
│   ├── runtime/              # Claude/Codex/Kimi 运行时适配与并行 agent 接口
│   ├── tasks/                # 收取、批改、复核导出三个任务流程
│   ├── tools/                # pku3b、REST 接口、PDF、解析、标准化等工具参考
│   └── references/           # 评分 schema、检查配置模板、接口参考（含写入路径实测记录）
├── examples/                 # 一次性/课程专用脚本（仅参考实现）
└── requirements.txt
```

## 故障排查

- **会话失效**：`python3 scripts/ensure_pku3b_session.py --refresh`（多数情况可无交互刷新）。
- **找不到 pku3b**：设置 `PKU3B_BIN`，或把 pku3b 放入 `PATH`，或保持源码仓库在相邻 `../pku3b` 且已构建。
- **REST 写 405/403**：该校 Blackboard 的 cookie 会话只读开放，写操作强制 OAuth2；`publish_grades.py` 已内置可用的 DWR/表单写路径，无需处理。
- **评分表单 500**：`gradeAssignment/submit` 端点成功时也返回 500（响应组装报错），`publish_grades.py` 以写后读回为准，不以此判断成败。

## 安全原则

只访问当前账号可见的课程与成绩列；发布成绩前必须输出待发布摘要并经用户确认；写操作默认 dry-run、逐条确认、保留回滚。详见 `SKILL.md` 的「关键安全边界」。

## 许可证

[MIT](./LICENSE)。上游 AutoPku 与 pku3b 均为独立项目，各自保留其版权。
