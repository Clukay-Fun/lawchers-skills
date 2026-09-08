# lawchers-skills

法律工作技能集合。四个日常事务技能采用纯 skill，由模型理解请求并使用环境已有能力；材料脱敏保留本地处理引擎。

| 英文标识 | 中文名称 | 职责 |
|---|---|---|
| [legal-receipt](legal-receipt/SKILL.md) | 贴票统计 | 整理报销贴票材料，核对并登记贴票台账 |
| [legal-invoice](legal-invoice/SKILL.md) | 合同发票统计 | 登记已开的合同发票，关联合同并核对已开票金额 |
| [legal-contract](legal-contract/SKILL.md) | 合同登记 | 提取合同信息，核对并登记合同台账 |
| [legal-organize](legal-organize/SKILL.md) | 日常工作文件整理 | 根据内容与既有习惯命名、分类和归档工作文件 |
| [legal-mask](legal-mask/SKILL.md) | 材料脱敏 | 对材料脱敏、审核与还原；CLI 命令仍为 `legal-desens` |

## 使用

四个事务技能各自独立，读取对应 `SKILL.md` 即可。`agents/openai.yaml` 仅提供中文显示名，不包含程序或调度配置。具体台账、目录、命名和业务规则沿用用户上下文及实际样例；无需配置一整套自动化系统，不包含业务汇总。

材料脱敏先读 [安装说明](legal-mask/README.md)，按需安装依赖并自测，再按 [SKILL.md](legal-mask/SKILL.md) 处理材料。skill 标识为 `legal-mask`，Python 包与命令保留 `legal_desens` / `legal-desens`。
