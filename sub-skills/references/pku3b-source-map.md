# pku3b 源码复用地图

本技能参考本地源码：`~/pku3b`（任何本地 pku3b 源码检出均可，也可直接用 PATH 里的 `pku3b`）。

## 认证和会话

- `src/cli/mod.rs`
  - `build_client()`：设置 cookie restore path。
  - `load_client_courses()`：读取配置、检查 OTP、登录 Blackboard、获取课程。
- `src/api/blackboard.rs`
  - `Client::blackboard(username, password, otp_code)`：调用 `bb_homepage()` 检查 cookie 是否仍有效；无效时执行登录并保存 cookie。
- `src/api/low_level/blackboard.rs`
  - `bb_login()`：IAAA OAuth 登录并跟随 SSO redirect。
  - `bb_homepage()`：验证 Blackboard 登录态。
- `src/http.rs`
  - `Client` 包装 cookie store。
  - `save_set_cookies()` / `load_set_cookies()` 保存和恢复 cookie JSON。

## 课程和作业定位

- `src/api/blackboard.rs`
  - `Blackboard::_get_courses()`：从 Blackboard home page 提取课程 key。
  - `Blackboard::get_courses(only_current)`：返回 `CourseHandle`。
  - `CourseHandle::_get()`：读取课程页菜单入口。
  - `Course::content_stream()`：从 content list 递归抓课程内容。
  - `CourseContentData::from_element()`：解析 content item，识别 `CourseContentKind::Assignment`。
  - `CourseContent::into_assignment_opt()`：把 content item 转成作业 handle。
  - `CourseAssignmentHandle::_get()`：访问作业 upload/view 页面，读取 deadline 和当前学生 attempt。

## 当前学生侧限制

- `src/cli/cmd_assignment.rs`
  - `list()`：列作业。
  - `download()`：下载作业说明附件。
  - `submit()`：学生侧提交作业。

这些命令没有助教侧“列出全部学生 attempt / 下载提交物”的逻辑。TA 版应新增接口，而不是复用学生提交命令。

## 建议扩展点

1. 在 low-level client 增加 `bb_rest_get_json()` / `bb_rest_download()`：
   - 使用已有 cookie store。
   - 支持可选 bearer token。
   - 记录 HTTP status、URL、响应 content-type。
2. 在 high-level blackboard API 增加：
   - `Course::gradebook_columns()`
   - `Course::assignment_attempts(column_id)`
   - `Course::download_attempt_file(attempt_id, file_id, dest)`
3. 在 CLI 增加 TA 子命令：
   - `pku3b ta assignments`
   - `pku3b ta submissions <course-id> <assignment-or-column-id> -d <dir>`
   - `pku3b ta grades export/import`

## 安全约束

- 不打印 cookie、密码、OAuth secret、bearer token。
- 下载提交物只用于当前账号可见课程。
- 发布成绩和反馈必须与 AutoPkuTA 的二次确认流程集成。
