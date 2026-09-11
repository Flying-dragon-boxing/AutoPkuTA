---
name: autopku-ta-tool-blackboard-ta
description: 助教侧 Blackboard/教学网 REST/页面接口探测、提交物下载、成绩中心读取、反馈上传与发布前确认策略
---

# Blackboard/教学网助教侧工具策略

## 适用范围

pku3b 当前学生侧命令不能直接拉取提交物，但源码已经提供可复用的基础能力：IAAA 登录、Blackboard cookie store、课程列表、content tree、作业 content_id 和附件下载。助教侧获取提交物应优先复用这些能力探测 Blackboard REST/页面接口，而不是默认要求人工导出。

## 获取提交物优先级

1. **pku3b session + Blackboard REST**：复用已登录 cookie 或官方 OAuth token，访问 gradebook column attempts、attempt files、users/enrollments。
2. **pku3b session + 教师页面接口**：用已登录 cookie 抓取成绩中心/作业批改页面中可见的提交记录和下载链接。
3. **浏览器会话辅助**：仅在页面接口需要 JS token、CSRF nonce 或动态参数时，用已登录浏览器读取这些参数。
4. **人工导出兜底**：只有上述路径失败时，才要求 Blackboard/教学网原生 ZIP/CSV/XLSX 导出。

## 官方 REST 认证判断

Blackboard public REST 不是普通网页 cookie API。官方模式需要：

- Learn 管理员启用 REST integration。
- 应用在 Anthology Developer Portal 注册，有 OAuth key/secret。
- 用 `/learn/api/public/v1/oauth2/token` 取 bearer token。
- integration user 或 3LO 用户有相应 entitlements。

因此，skill 不应假设 TA 账号天然有 REST bearer token。没有 key/secret 时，优先尝试 pku3b cookie session 能否访问同路径；若返回 401/403，再退回页面接口。

## 候选 REST endpoints

按实例版本和权限探测，保存成功/失败状态：

```text
GET /learn/api/public/v1/courses
GET /learn/api/public/v1/courses/{courseId}/contents
GET /learn/api/public/v1/courses/{courseId}/gradebook/columns
GET /learn/api/public/v1/courses/{courseId}/gradebook/columns/{columnId}/users
GET /learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/attempts
GET /learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/attempts/{attemptId}
GET /learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/attempts/{attemptId}/files
GET /learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/attempts/{attemptId}/files/{fileId}/download
```

Endpoint 名称可能随 Learn 版本变化。先用 `OPTIONS` 或 API 文档/错误响应确认；不要硬编码为唯一真相。

## PKU 实测提交物链路

给定教师预览链接：

```text
/webapps/assignment/uploadAssignment?content_id={content_id}&course_id={course_id}&mode=cpview
```

PKU 当前实例可用链路：

```text
GET /learn/api/public/v1/courses/{course_id}/gradebook/columns
  -> 找到 contentId == {content_id} 的 column.id

GET /learn/api/public/v2/courses/{course_id}/gradebook/columns/{column_id}/attempts
  -> 每条 result 给出 attempt.id、userId、status、attemptDate、attemptReceipt

GET /learn/api/public/v1/courses/{course_id}/gradebook/attempts/{attempt_id}/files
  -> 返回提交附件 id/name

GET /learn/api/public/v1/courses/{course_id}/gradebook/attempts/{attempt_id}/files/{file_id}/download
  -> 部分 Learn 版本会 302 到 bbcswebdav，但教师账号可能最终 404

GET /webapps/assignment/download?course_id={course_id}&attempt_id={attempt_id}&file_id={file_id}&fileName={file_name}
  -> PKU 当前实例实测稳定返回附件内容，优先用于实际下载

GET /learn/api/public/v1/users/{user_id}
  -> 映射 userName、姓名、邮箱等身份字段
```

可直接运行脚本：

```bash
python3 AutoPkuTA/scripts/ensure_pku3b_session.py --json

python3 AutoPkuTA/scripts/collect_blackboard_submissions.py \
  --course-id _98497_1 \
  --content-id _1619008_1 \
  --outdir AutoPkuTA_probe/submissions
```

默认只生成 `submission_manifest.json`。下载附件时显式加 `--download`。

如果 `GET /learn/api/public/v1/users/{user_id}` 对个别用户返回 404，不中断抓取；在 manifest 中记录 `user_lookup_error`，以教学网提交记录中的 `userId` 作为稳定 key，后续人工或名单表补全身份信息。

实测样例：

| 作业 | content_id | column_id | 结果 |
|------|------------|-----------|------|
| 阶段性测试与总结报告 | `_1619008_1` | `_427505_1` | 可列出 attempts 并下载附件 |
| 第6次作业 | `_1603010_1` | `_424995_1` | 可列出 72 次 attempts，下载 76 个附件 |

按分组归档时先规范化分组表：

```bash
python3 AutoPkuTA/scripts/normalize_group_roster.py 分组.csv \
  -o normalized_groups.csv

python3 AutoPkuTA/scripts/group_blackboard_submissions.py \
  --manifest AutoPkuTA_probe/submissions/submission_manifest.json \
  --groups normalized_groups.csv \
  --outdir AutoPkuTA_probe/submissions_by_group
```

## pku3b 复用点

读 `sub-skills/references/pku3b-source-map.md`。关键思路：

- 复用 `Client::blackboard()` 完成登录和 cookie 恢复。
- 复用 `Blackboard::get_courses()` 定位课程 key。
- 复用 `Course::content_stream()` 找 content tree 中的 assignment。
- 用 assignment 的 `course_id` 和 `content_id` 映射/探测 gradebook column。
- 在 `LowLevelClient` 增加带 cookie 的 JSON GET/download 方法，或单独写脚本读取 pku3b 保存的 cookie store。

## 页面接口探测

当官方 REST 不可用时，从当前账号可访问的页面找入口：

- 课程控制面板/Grade Center。
- 作业 Needs Grading / View Grade Details。
- 作业 attempt 列表页。
- 批量下载提交物链接。

步骤：

1. 从课程页 HTML 提取控制面板、成绩中心、作业管理链接。
2. 访问作业对应的 grade column 或 attempt 页面。
3. 解析学生、attempt id、提交时间、附件链接。
4. 用同一 cookie 下载附件，保存原始响应头、文件名、hash。

页面接口不稳定，必须把解析 selector 和 URL 记录到 `reports/acquisition_trace.json`，便于下次修正。

## 上传成绩

上传或发布成绩是高风险动作，必须满足：

- 用户明确要求上传/发布。
- `reports/pre_publish_checklist.md` 已生成。
- 成绩表中学生 ID 与教学网导出名单完全匹配，异常行已列出。
- 用户确认是否覆盖已有成绩。

若系统只支持网页表单逐项录入，优先建议用户使用官方成绩中心 CSV 导入；只有用户确认后才进行浏览器自动化。

## 字段匹配

常见字段同义词：

| 标准字段 | 可能列名 |
|----------|----------|
| student_id | 学号, Student ID, Username, 用户名 |
| name | 姓名, Name, Full Name |
| email | 邮箱, Email |
| submitted_at | 提交时间, Submission Time, Last Submitted |
| status | 状态, Status |
| score | 分数, Score, Grade |
| feedback | 评语, Feedback, Comments |

字段无法唯一匹配时停止发布，要求用户提供映射。

## 浏览器自动化注意事项

- 使用用户已登录的浏览器会话，避免在技能中保存密码。
- 每次点击上传/发布前截图或记录当前页面标题、课程、作业名。
- 上传后导出成绩中心重新核对，而不是只相信页面提示。
- 不绕过教学网权限和访问控制。
