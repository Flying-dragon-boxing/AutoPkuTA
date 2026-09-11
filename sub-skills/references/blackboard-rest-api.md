# Blackboard REST API 参考要点

## 官方认证模型

Blackboard Learn public REST 使用 OAuth 2.0。常见 client credentials 模式需要：

- 在 Anthology Developer Portal 注册 application，获得 key/secret。
- Learn 管理员在本校 Learn 实例启用该 application。
- 使用 `/learn/api/public/v1/oauth2/token` 获取 access token。
- 后续请求带 `Authorization: Bearer <token>`。

官方文档说明 token 有生命周期，且 REST integration 默认不会自动启用；必须由 Learn 管理员启用并配置具有相应 entitlements 的用户。

## 对 AutoPkuTA 的含义

- 普通 TA 账号只有网页登录态时，不一定能直接调用 public REST。
- 如果用户提供官方 OAuth key/secret，使用 bearer token。
- 如果没有 key/secret，先尝试 pku3b 的网页登录 cookie 访问相同路径；失败后用页面接口解析。
- 不把 401/403 当作任务失败，应记录后自动 fallback。

## 助教侧候选数据路径

按优先级探测：

1. Course / content / gradebook columns：
   - `/learn/api/public/v1/courses`
   - `/learn/api/public/v1/courses/{courseId}/contents`
   - `/learn/api/public/v1/courses/{courseId}/gradebook/columns`
2. Column users / grades：
   - `/learn/api/public/v1/courses/{courseId}/gradebook/columns/{columnId}/users`
3. Attempts / submitted files：
   - `/learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/attempts`
   - `/learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/attempts/{attemptId}`
   - attempt file metadata/download endpoint, names vary by Learn version
4. Group attempts when assignment is group-based：
   - `/learn/api/public/v2/courses/{courseId}/gradebook/columns/{columnId}/groupAttempts`

## 探测输出

每次获取提交物都写入 `reports/acquisition_trace.json`：

```json
{
  "course_id": "",
  "assignment": "",
  "auth_mode": "pku3b-cookie|oauth-client-credentials|browser-session",
  "attempted_endpoints": [
    {"method": "GET", "url": "...", "status": 200, "note": ""}
  ],
  "fallback": "none|page-interface|manual-export",
  "warnings": []
}
```

## 版本差异

Blackboard Learn endpoint 和可见字段随版本、Original/Ultra Course View、权限 entitlements 变化。实现时优先从 API reference 或实例错误响应确认字段，不要把候选 endpoint 写死为唯一可行路径。

## 写入成绩的可行路径（PKU 实例实测，Learn 3900）

官方 REST 写操作在本实例不可用：cookie 会话下 `PUT /learn/api/public/v{1,2}/courses/{cid}/gradebook/columns/{col}/users/{uid}` 返回 405，`PATCH` 返回 403「此请求未与有效会话关联」（写操作强制 OAuth2，普通 TA 账号无 key/secret）。**可用路径是复刻 Original Grade Center 网格的 DWR 调用**：

1. `GET /webapps/gradebook/do/instructor/getJSONData?course_id=_COURSE_` — 全量成绩簿 JSON，取 `version`（乐观锁）和 `rows`（每行首格 `uid`=课程成员 pk，`iuid`=用户 pk）。
2. `POST /webapps/gradebook/dwrbatchid/call/plaincall/GradebookDWRFacade.updateGrade.dwr` — 写分数。表单参数：`batchId`（必需，数字）、`callCount=1`、`c0-scriptName=GradebookDWRFacade`、`c0-methodName`、`c0-id=c0`、`c0-paramN=<type>:<value>`。签名：`updateGrade(int coursePk, int bookVersion, double score, String text, int membershipPk, int columnPk)`。
3. `POST .../GradebookDWRFacade.setComments.dwr` — 写「给学生的反馈」。签名：`setComments(int coursePk, String membershipPk, String columnPk, String studentFeedback, String instructorNote, boolean studentChanged, boolean instructorChanged)`；空串 instructorNote + `instructorChanged=false` 不会触碰教师备注。
4. 请求头：`Content-Type: text/plain; charset=UTF-8`、`Referer` 指向 `enterGradeCenter?course_id=...`。

关键坑：写接口的 `userId` 是**课程成员 pk**（getJSONData 行的 `uid`），不是 REST 的用户 pk（`iuid`）；用错会返回笼统的 `Throwable: Error`。成绩（grade）独立于提交（attempt）存在，无提交的学生可直接写分数和评语。实现见 `scripts/publish_grades.py`。

## 关联指定 attempt 的评分（实测）

要把分数和评语挂到**某一次 attempt**（如多次提交中的最后一次），用评分表单的页面接口：

1. `GET /webapps/assignment/gradeAssignmentRedirector?outcomeDefinitionId=<col_id 去掉前导下划线>&course_id=_COURSE_&attempt_id=_ATTEMPT_` — 取表单 nonce（`name="blackboard.platform.security.NonceUtil.nonce"`，单双引号都有）。
2. `POST /webapps/assignment/gradeAssignment/submit`（urlencoded）：`nonce, course_id, attempt_id, courseMembershipId=<成员pk>, grade, feedbacktext, feedbacktype=P, gradingNotestext=, gradingNotestype=P`。multipart 表单和 VTBE 会话存储（`feedbacktext_f/_w`）都非必需，直接纯文本即可。
3. 该端点**成功时也返回 500**（响应组装报错，写入已提交），必须以读回为准：`GET /learn/api/public/v2/courses/{cid}/gradebook/columns/{col}/attempts/{att}` 确认 status=Completed、score、feedback。
4. 表单只更新 attempt，不自动同步成绩簿单元格（尤其单元格曾被手动覆盖时）；需要再补一次 DWR `updateGrade` 同步单元格分数。
