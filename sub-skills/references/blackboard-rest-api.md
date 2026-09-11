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

## 关联指定 attempt 的评分（三条路径实测对比）

要把分数和评语挂到**某一次 attempt**，按优先级有三条路径：

### 路径 A：reconcileGrades 三件套（首选；上游 pku3b `ta` 同款）

借鉴自 [pku3b 上游](https://github.com/sshwy/pku3b) 的 `ta` 实现（2026-07 引入）：

1. `GET /webapps/gradebook/controller/loadReconcileData?course_id=&id=<列id>` — 一次返回整列评分状态：`attempts[].attemptId / studentUserId / status / reconciledScore / provisionalGrades[]`。读路径稳定可用，也是很好的只读整列状态接口。
2. `GET /webapps/gradebook/controller/reconcileGrades?course_id=&id=<列id>` — 页面里提取 ajax nonce（`NonceUtil.nonce.ajax`）。
3. `POST /webapps/gradebook/controller/saveReconcileGrade`，form 参数：`attemptId, gradableItemId, score(%.2f), hasFeedback, myfeedbacktext(评语), showStagedFeedbackToStu=true, isDetailPage=false, reconcileMode=A, course_id, blackboard.platform.security.NonceUtil.nonce.ajax`；头需 `Origin / Referer(reconcileGrades页) / X-Requested-With: XMLHttpRequest / X-Prototype-Version: 1.7`。

⚠️ **实测该校实例（Learn 3900.39.0-rel.27，2026-09）reconcile 页面与 saveReconcileGrade 均 500**（loadReconcileData 正常），可能随版本修复；上游 2026-07 开发时可用。`publish_grades.py` 已内置此路径并自动降级。

### 路径 B：评分表单（降级；首次评分与改评 Completed attempt 均可用）

1. `GET /webapps/assignment/gradeAssignmentRedirector?outcomeDefinitionId=<列id去前导下划线>&course_id=&attempt_id=` — 取表单 nonce（`NonceUtil.nonce`，非 ajax 版）。
2. **multipart POST**（与表单 `enctype="multipart/form-data"` 一致；⚠️ **urlencoded 会被服务端静默忽略**——曾误判为"实例故障/已完成 attempt 不可改评"，实为编码问题）：字段 `nonce, course_id, attempt_id, courseMembershipId=<成员pk数字>, grade, feedbacktext, feedbacktype=P, gradingNotestext=, gradingNotestype=P`，以 `files=` 形式发送（每字段 `(None, value)`）。VTBE 会话存储（`feedbacktext_f/_w`）非必需，纯文本即可。

⚠️ 该端点**成功也返回 500**（响应组装报错，写入已提交），必须以读回为准：`GET /learn/api/public/v2/courses/{cid}/gradebook/columns/{col}/attempts/{att}` 确认 score/feedback。首次评分与已完成 attempt 的改评均实测可写（2026-09-11，multipart）。单元格若存在手动覆盖（`overridden`），用 `POST /webapps/assignment/gradeAssignment/revert`（参数 `course_id, courseMembershipId=_成员pk_1, gradableItemId, blackboard.platform.security.NonceUtil.nonce.ajax=<评分页 ajaxNonceId>`）**还原覆盖**让单元格跟随 attempt，而不是直接写单元格。清空手动单元格分：DWR `updateGrade` 传空分数与空文本（模拟 UI 清空成绩格）。

### 路径 C：DWR grade 层（保底；仅无提交时使用）

Grade Center 网格的 `updateGrade`（分数）+ `setComments`（评语写 grade 层 comment，不动教师备注）。成绩独立于 attempt，**只用于学生没有任何提交的场景**；有提交时禁止直接改成绩表（分数必须落在 attempt 上，单元格只能跟随或还原覆盖），改评必须走路径 A/B。

`publish_grades.py` 的策略：A → 失败降级 B（multipart）→ 写后读回校验，校验不过即报错（不会假成功）。有提交时绝不直接写成绩表：单元格若与 attempt 不一致，先 `gradeAssignment/revert` 还原覆盖使其跟随 attempt，仍不一致则报错。当前实例（2026-09）路径 A 整体 500（路径 B 可用，不影响）， reconcile 恢复后自动优先走 A。
