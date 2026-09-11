---
name: autopku-ta-tool-pku3b-setup
description: 助教工作流中可复用的 PKU 教学网 pku3b 安装、配置、登录和只读命令参考
---

# pku3b 工具配置（助教侧）

pku3b 在本技能中主要用于课程、公告、作业元数据等只读信息。学生提交物、成绩中心导出、反馈上传通常需要 Blackboard/教学网助教页面，见 `blackboard-ta.md`。

## 安装检查

```bash
which pku3b 2>/dev/null || echo "NOT_FOUND"
```

## 安装

### macOS Apple Silicon
```bash
cd /tmp
curl -LO "https://github.com/sshwy/pku3b/releases/download/0.11.0/pku3b-0.11.0-aarch64-apple-darwin.tar.gz"
tar -xzf pku3b-0.11.0-aarch64-apple-darwin.tar.gz
chmod +x pku3b-0.11.0-aarch64-apple-darwin/pku3b
ln -sf pku3b-0.11.0-aarch64-apple-darwin/pku3b pku3b
./pku3b --version
```

### 其他平台
从 [sshwy/pku3b releases](https://github.com/sshwy/pku3b/releases) 下载对应版本。

> **版本说明**: v0.11.0+ 支持公告 (`ann`) 和课表 (`ct`) 功能

## TTY-safe 登录

使用 expect 脚本避免 "input device is not a TTY" 错误：

```bash
cat > /tmp/pku3b_login.exp << 'EOF'
#!/usr/bin/expect -f
set timeout 30
spawn /tmp/pku3b init
expect "username:"
send "学号\r"
expect "password:"
send "密码\r"
expect eof
EOF
chmod +x /tmp/pku3b_login.exp
/tmp/pku3b_login.exp
```

## 验证登录

```bash
/tmp/pku3b a ls
```

## 助教脚本会话衔接

本技能的 Blackboard 抓取脚本默认读取 pku3b 的 cookie store：

```text
~/.cache/pku3b/ua.json
```

开始抓取提交物前先检查会话：

```bash
python3 AutoPkuTA/scripts/ensure_pku3b_session.py --json
```

若会话失效，尝试复用本地 pku3b 刷新：

```bash
python3 AutoPkuTA/scripts/ensure_pku3b_session.py --refresh
```

脚本会按顺序查找 `PKU3B_BIN` 环境变量、`PATH` 中的 `pku3b`、相邻源码仓库 `../pku3b/target/{release,debug}/pku3b`。刷新过程可能需要 pku3b 自身的交互式登录；不要在 skill 文档或脚本参数里保存密码。

## 常用只读命令

```bash
# 作业
/tmp/pku3b a ls --all-term          # 所有学期作业
/tmp/pku3b a download <ID> -d <dir> # 下载作业说明/附件（如账号权限允许）

# 公告
/tmp/pku3b ann ls                   # 列出公告
/tmp/pku3b ann show <ID>            # 查看公告详情

# 课表
/tmp/pku3b ct -r                    # 获取课表 JSON

# 选课
/tmp/pku3b s -d major show          # 主修课程
```

## 不默认执行的命令

```bash
/tmp/pku3b a submit <ID> <file>
```

助教批改工作流不使用学生侧提交命令。任何会改变教学网状态的上传、发布、覆盖操作，必须通过 `blackboard-ta.md` 的发布确认流程执行。

## 踩坑记录

- `pku3b init` 需要交互式输入，直接管道输入不工作
- `pku3b auth status/login` 命令不存在，正确命令是 `pku3b init`
- `pku3b s -d major show` 可能在某些账号返回 `302 Found`，作为可选步骤处理
- 助教侧提交物批量下载和成绩中心导出不一定由 pku3b 覆盖，遇到权限或功能缺失时切换到 Blackboard/浏览器导出。
