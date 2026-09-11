---
name: autopku-ta-task-review-and-export
description: 复核批改结果，生成发布前核对表，导出成绩表和反馈，必要时经确认上传 Blackboard/教学网
---

# 任务：复核、导出与发布前检查

## 流程

### 1. 读取草稿

读取：

- `reports/grades_draft.csv`
- `grading/*/grading.json`
- `review_queue/high_risk.json`
- `review_queue/random_sample.json`

若缺少草稿成绩，先执行 `grade-assignment.md`。

### 2. 复核策略

优先复核：

- `needs_review=true`
- 低于及格线、满分、接近分档边界
- 迟交、缺交、格式异常
- 疑似抄袭或相似提交
- 随机抽样至少 5% 或不少于 5 份（人数不足时全部）

复核时只修改明确有证据的问题，并在 `grading.json.review_history` 追加记录，不覆盖原始评语。

### 3. 一致性检查

生成 `reports/pre_publish_checklist.md`：

- 人数：名单、提交、已评分、缺交是否一致
- 分数：范围、均值、中位数、异常值
- rubric：各项分数是否在范围内，总分是否正确
- 反馈：是否每名已评分学生都有反馈
- 发布目标：课程、作业、成绩列名、满分

### 4. 导出

默认导出本地文件：

- `reports/grades_final.csv`
- `reports/grades_final.xlsx`（如环境支持）
- `reports/feedback_bundle.zip`
- `reports/pre_publish_checklist.md`

### 5. 发布或上传

只有用户明确确认后，才根据 `sub-skills/tools/blackboard-ta.md` 执行上传。上传前再次展示摘要：

- 课程与作业
- 待发布人数
- 分数范围
- 将上传的文件路径
- 是否覆盖已有成绩/反馈

## 输出

- 复核后的最终成绩表
- 反馈包
- 发布前核对表
- 如执行上传，记录上传结果和时间戳
