---
name: autopku-ta-runtime-create-agent
description: 统一的 Agent 创建接口，自动适配当前 AI 环境
---

# 统一 Agent 创建接口

## 快速开始

在 task skill 中引用此文件来创建 agents，无需关心底层 AI 环境。

## 接口定义

### create_agents(task_list, agent_config)

**参数：**
- `task_list`: 任务列表，每个元素是一个字典，包含任务参数
- `agent_config`: agent 配置模板

**示例：**

```markdown
## 并行批改提交

引用: `sub-skills/runtime/create-agent.md`

任务：为每名学生或每个提交创建专属 agent

任务列表：
```json
[
  {"student_id": "2300010001", "student_name": "张三", "student_dir": "./normalized/2300010001_张三"},
  {"student_id": "2300010002", "student_name": "李四", "student_dir": "./normalized/2300010002_李四"}
]
```

Agent 模板：
```
你是学生 "{student_id} {student_name}" 的批改 agent。

提交目录：{student_dir}
任务：按 rubric 批改并生成 grading.json 与 feedback.md。
```
```

## 运行时适配逻辑

### Claude Code 环境

```python
for task in task_list:
    Agent({
        "name": f"{task['student_id']}-grader",
        "prompt": agent_template.format(**task),
        "description": f"批改 {task['student_id']}"
    })
```

### Kimi Code CLI 环境

```python
for task in task_list:
    Agent({
        "description": f"批改 {task['student_id']}",
        "prompt": agent_template.format(**task),
        "subagent_type": "coder"
    })
```

### Codex 环境

```
请为以下提交并行创建 subagents：

{formatted_task_list}

每个 subagent 使用对应的配置模板。
```

### Fallback 环境

串行执行，逐个处理任务。

## 完整示例

### grade-assignment.md 中的使用

```markdown
# 批量批改作业

## 并行处理

引用: `sub-skills/runtime/create-agent.md`

为每份提交创建 grader agent，并行执行：

```python
# 自动检测环境并执行
agents = create_agents(
    task_list=[
        {"student_id": s["student_id"], "student_name": s["name"], "student_dir": s["normalized_dir"]}
        for s in manifest["students"] if s["status"] != "missing"
    ],
    agent_template="""
你是 Grader，按 rubric 批改一名学生的提交。

学生：{student_id} {student_name}
提交目录：{student_dir}

任务：
1. 读取 rubric.md 和 checks.json
2. 逐项给分并引用证据
3. 生成 grading.json 和 feedback.md
4. 标记 needs_review
"""
)
```
```

## 注意事项

1. 不要直接调用此接口，而是通过引用方式使用
2. 实际的 agent 创建语法由运行时环境决定
3. 在 Codex 环境中，使用自然语言描述并行任务
4. 在 Kimi 环境中，Agent 结果直接返回，无需额外消息通信机制
