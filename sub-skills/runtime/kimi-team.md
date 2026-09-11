---
name: autopku-ta-runtime-kimi
description: Kimi Code CLI Agent Team 运行时接口
---

# Kimi Code CLI Agent Team 运行时

## 创建 Subagent

Kimi Code CLI 使用内置 `Agent()` tool 创建子代理，支持三种类型：

```python
# explore: 快速探查代码库、定位文件和逻辑
Agent({
    "description": "探索 {assignment} 提交结构",
    "prompt": f"请快速探查 {assignment_dir} 目录下的提交物、rubric、manifest 和异常清单。",
    "subagent_type": "explore"
})

# coder: 处理代码编写、修改、调试任务（默认）
Agent({
    "description": f"批改 {student_id}",
    "prompt": f"请按 rubric 批改 {student_id} 的提交，生成 grading.json 和 feedback.md。",
    "subagent_type": "coder"
})

# plan: 实现前的架构规划和步骤拆解
Agent({
    "description": f"规划 {assignment} 批改流程",
    "prompt": f"请为 {assignment} 制定批改计划，包括确定性检查、rubric 项、复核策略和导出文件。",
    "subagent_type": "plan"
})
```

## 并行执行

Kimi 支持两种方式实现并行：

### 方式 1：同时发起多个 Agent 调用

在同一个回复中发起多个 `Agent()` 调用，Kimi 会并行调度执行：

```python
# 为多个学生提交同时创建 grader agent
for student in students:
    Agent({
        "description": f"批改 {student['student_id']}",
        "prompt": f"你是 Grader。请批改 {student['student_id']} 的提交并输出 grading.json 和 feedback.md。",
        "subagent_type": "coder"
    })
```

### 方式 2：后台任务（长时间运行）

对于需要持续运行的任务（如编译、测试、服务器），使用 `run_in_background=True`：

```python
# 启动后台任务
Agent({
    "description": "启动本地服务器",
    "prompt": "请在后台启动 npm run dev，并监控其输出。",
    "subagent_type": "coder",
    "run_in_background": True
})

# 查询后台任务状态
TaskList({"active_only": True})
TaskOutput({"task_id": "<task_id>"})

# 停止后台任务
TaskStop({"task_id": "<task_id>"})
```

## 结果收集

Kimi 的子代理**没有 `SendMessage()` 工具**。子代理的结果会直接返回给父代理，由父代理统一收集：

```python
results = []
for course in courses:
    result = Agent({
        "description": f"批改 {course}",
        "prompt": f"请按 rubric 批改该提交，完成后返回 grading.json 路径、分数和 needs_review。",
        "subagent_type": "coder"
    })
    results.append({"course": course, "summary": result})
```

## Coordinator 模式

```python
# Phase 1: 并行创建 checker agents
checked = []
for student in students:
    result = Agent({
        "description": f"检查 {student['student_id']}",
        "prompt": f"对 {student['student_id']} 的提交执行格式、编译/运行、PDF 可读性等确定性检查。",
        "subagent_type": "coder"
    })
    checked.append(result)

# Phase 2: 收到结果后，指派 grader agent 批改
graded = Agent({
    "description": "批改所有提交",
    "prompt": f"根据以下检查结果和 rubric 批改：\n{checked}",
    "subagent_type": "coder"
})

# Phase 3: 指派 reviewer/exporter agent 复核并导出
final = Agent({
    "description": "复核并导出成绩",
    "prompt": f"复核以下批改结果，生成 grades_draft.csv 和 review_queue：\n{graded}",
    "subagent_type": "coder"
})
```

## 约束条件

- Agent 之间**不直接通信**，结果通过父代理传递
- 长时间任务建议使用 `run_in_background=True` + `TaskList/TaskOutput`
- `timeout` 参数可以控制子代理最大运行时间（单位：秒）
- 默认 `subagent_type` 为 `"coder"`，探查类任务推荐 `"explore"`，规划类任务推荐 `"plan"`
