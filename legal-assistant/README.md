# legal-assistant

律所日常事务自动化：发票贴票、开票入账、合同登记、扫描件归档、定时汇总推送。数据中枢是飞书多维表格（经 [lark-cli](https://github.com/larksuite/cli)），在 Windows 上由任务计划程序挂机运行。

**脚本为主，agent 辅助**：确定性批处理全由 CLI 完成（无 LLM、无 token 成本、可重跑）；AI agent 只介入合同确认、开票歧义复核和异常诊断（见 [SKILL.md](SKILL.md)）。

## 运行环境

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11（运行机）；macOS/Linux 可开发测试 |
| Python | 3.9+，pip ≥ 21.3 |
| Node.js | 任意近期版本（装 lark-cli 用） |
| lark-cli | 飞书官方 CLI，源码与文档见 https://github.com/larksuite/cli |
| 飞书 | 一个自建应用（凭据由 lark-cli 管理，本项目不存密钥） |

## 快速开始

### 让 Agent 帮你安装（推荐）

把下面这段发给 Claude Code 等 agent：

```text
请安装并配置 legal-assistant：
1. 在 legal-assistant/ 目录执行 pip install -e ".[dev,pdf]"，
   然后 python -m pytest tests/ -q，须全部通过
2. 复制 config.example.yaml 为 config.yaml，向我逐项确认：
   收件箱路径、飞书 base_token、三张表的 tbl id、汇总推送 user_id、本所全称 firm_name
3. 执行 legal-assistant doctor --config config.yaml，把未通过项修复或报给我
4. 读 SKILL.md 后向我复述：哪些操作你可以自动做，哪些必须我确认
```

### 手动安装

```powershell
# 1. 安装本体
pip install -e ".[pdf]"

# 2. 安装 lark-cli（飞书官方 CLI，仓库：https://github.com/larksuite/cli）
npm i -g @larksuite/cli
lark-cli --version          # 验证；已装过则 lark-cli update 升级到最新
lark-cli config init && lark-cli auth login --domain base

# 3. 配置并诊断
copy config.example.yaml config.yaml     # 填路径、base_token、表 id、推送对象
legal-assistant doctor --config config.yaml

# 4. 注册挂机任务（轮询 + 汇总推送；星期/时间自定义，周五 16:00 只是默认值）
powershell -ExecutionPolicy Bypass -File deploy\register-tasks.ps1 `
    -PollMinutes 10 -WeeklyDay Friday -WeeklyTime 16:00
```

## 工作原理

```text
QQ 发票 zip ─┐
销项发票 PDF ─┼─▶ 收件箱（Task Scheduler 轮询）─▶ legal-assistant CLI ─▶ 飞书多维表格（lark-cli）
扫描件      ─┘                                        │                    │
                                                 分类归档到本地           定时汇总 ─▶ 机器人私聊推送
```

| 流程 | 命令 | 行为 |
|------|------|------|
| 发票贴票 | `invoice-once` | 解析 zip → 按类型归档打印目录 → 写报销台账（发票号幂等） |
| 扫描件归档 | `scan-once` | 文件名/首页文本/OCR 三级识别 → 七分类；占用跳过、重名不覆盖 |
| 开票入账 | `output-invoice-once` | 解析发票 → 唯一匹配合同才写入并回写台账；歧义挂起，`pending`/`resolve` 人工复核 |
| 合同登记 | `contract-draft` → `contract-commit` | 草稿确认制，确认前不落任何数据 |
| 定时汇总 | `weekly-summary` | 两表按成员出全量累计快照 → 飞书私聊推送；推送星期/时间在注册任务时自定义 |

安全设计：发票号/合同号幂等去重、不确定不写（挂起转人工）、`--dry-run` 全流程演练、每个动作留痕 `journal/`。退出码 `0/1/2` = 成功/有失败项/配置错误。

## 面向开发者

```text
scripts/            Python 包本体（映射为 legal_assistant，见 pyproject）
deploy/             register-tasks.ps1（Windows 计划任务注册）
tests/              pytest（FakeLark 内存桩，不触真实飞书）
docs/plan/          v1 范围与拆分（SSOT）
SKILL.md            agent 决策表 / 人工确认协议 / 安全边界
AGENTS.md CLAUDE.md agent 开发约束与关键不变量
```

```bash
pip install -e ".[dev,pdf]" && python -m pytest tests/ -q
```

改发票解析逻辑前先读 `AGENTS.md` 的「Invoice PDF Parsing Notes」，改完必须重跑真实样例验证。

## 许可证

个人/内部使用项目，暂未设置开源许可证。
