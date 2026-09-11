---
name: autopku-ta-runtime-codex
description: Codex Native Subagent 运行时接口
---

# Codex Native Subagent 运行时

## 创建 Subagent

Codex 使用内置的 subagent 机制：

```
请创建 subagent 处理以下任务：

Subagent: {student_id}-grader

任务：
1. 读取学生 {student_id} 的提交目录
2. 按 rubric 和 checks.json 逐项批改
3. 生成 grading.json 与 feedback.md
4. 标记 needs_review

提交目录：{student_dir}
```

## 并行执行

```
请为以下学生提交并行创建 subagents：
{student_task_list}

每个 subagent 独立处理一名学生的提交，完成后返回评分文件路径和复核标记。
```

## Coordinator 模式

```
你作为 Coordinator，协调以下 subagents 按顺序执行：

Phase 1: 指派 parser-agent 解析 PDF
Phase 2: 指派 checker-agent 执行确定性检查
Phase 3: 收到结果后，指派 grader-agent 评分
Phase 4: 收到结果后，指派 reviewer-agent 复核高风险样本
Phase 5: 指派 exporter-agent 生成成绩表和反馈包

使用 subagent 完成各 phase，等待每个 phase 完成后再进行下一个。
```

## 与 Claude Code 的差异

| 特性 | Claude Code | Codex |
|------|-------------|-------|
| Agent 创建 | `Agent()` tool | Natural language + subagent |
| 通信方式 | `SendMessage()` tool | Return values + context |
| 并行控制 | Team coordination | Parallel subagent requests |
| 状态跟踪 | `TaskCreate/TaskUpdate` | Session context |
