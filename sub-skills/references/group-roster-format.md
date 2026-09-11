# 分组表格式

`normalize_group_roster.py` 把助教手里各种形态的分组表统一成**规范长表**；`group_blackboard_submissions.py` 消费它（或直接吃原始宽表），按组归档提交物。

## 规范长表（canonical）

CSV（UTF-8 带 BOM），四列：

| 列 | 含义 | 说明 |
|----|------|------|
| `topic` | 题目/项目方向 | 可留空；同组内所有行应相同 |
| `group_id` | 组号 | 必填，如 `3`、`第3组` |
| `member_order` | 组内序号 | 字符串数字，`1` 起 |
| `member_name` | 组员姓名 | **必须与教学网显示名一致**（匹配的 key） |

示例：

```csv
topic,group_id,member_order,member_name
稀疏矩阵,1,1,张三
稀疏矩阵,1,2,李四
图算法,2,1,王五
```

## 支持的输入形态（`normalize_group_roster.py` 自动识别）

接受 `.xlsx` / `.xls` / `.csv`（utf-8-sig）：

1. **长表**：`topic + group_id + member_name` 三列，一人一行。列名别名：
   - topic：`topic` `题目` `项目` `任务` `方向` `课题` `problem`
   - group：`group_id` `group` `组别` `组号` `多少组选` `分组` `小组`
   - member：`member_name` `member` `姓名` `组员` `学生` `student` `name`
2. **宽表**：一行一组——`题目,多少组选,组员1,组员2,组员3,...`（英文：`topic,group,member1,...`），组员列按出现顺序编 `member_order`。
3. **简单行**：`group_id, member_name[, topic]`，一人一行。

另：`topic` 为空的行沿用上一行的 topic（处理 Excel 合并单元格导出的表格）。

```bash
python3 scripts/normalize_group_roster.py 分组表.xlsx -o 作业/hw3/groups_normalized.csv
```

## 按组归档（`group_blackboard_submissions.py`）

```bash
python3 scripts/group_blackboard_submissions.py \
    --manifest 作业/hw3/submissions/submission_manifest.json \
    --groups 作业/hw3/groups_normalized.csv \
    --outdir 作业/hw3/by_group
```

- 读取 `collect_blackboard_submissions.py` 产物的 manifest，按**姓名**匹配分组；二次下载文件走 classic `/webapps/assignment/download` 接口。
- 输出目录：`{topic}__{group_id}/`；匹配不到的进 `_未匹配/`。
- 文件名：`{学号}_{姓名}_{attempt_id}_{原文件名}`，attempt id 保留以便追溯。
- 写出 `分组下载清单.csv`（每人每文件一行），stdout 打印未匹配名单——**归档后先核对 `_未匹配/` 和清单**，通常是分组表姓名与教学网显示名不一致（生僻字、空格、别名）导致。
