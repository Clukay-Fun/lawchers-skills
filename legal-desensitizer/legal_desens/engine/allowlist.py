"""Built-in baseline allowlist for common terms that NER often mislabels as ORG.

This file contains generic terms that should NOT be redacted even if NER
labels them as ORG. This is the built-in baseline that goes into git.

Case-specific allowlist (local, not in git) should be loaded separately.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

# Built-in baseline allowlist: common job positions, departments, headers,
# business terms, OCR fragments that NER often mislabels as ORG.
#
# These are generic labor-case terms and should NOT be redacted.
BUILTIN_ALLOWLIST: Set[str] = {
    # ── 通用岗位词 ──
    "综合部", "行政部", "人事部", "人力资源部", "财务部", "法务部",
    "市场部", "销售部", "技术部", "研发部", "生产部", "质检部",
    "客服部", "采购部", "物流部", "仓储部", "安保部", "后勤部",
    "运营部", "项目部", "策划部", "设计部", "工程部", "施工部",
    "管理部", "监督部", "审计部", "合规部", "风控部",
    "总经理", "副总经理", "总经理办公室", "总裁办",
    "人事处", "财务处", "行政处", "办公室",

    # ── 部门/流程字段 ──
    "人力资源", "行政管理", "财务管理", "法务合规",
    "质量管理", "项目管理", "运营管理", "客户管理",
    "薪酬福利", "绩效考核", "考勤管理", "培训管理",
    "招聘管理", "员工关系", "劳动关系",

    # ── 表头词 ──
    "序号", "编号", "姓名", "性别", "年龄", "出生日期",
    "身份证号", "联系电话", "手机号", "邮箱", "地址",
    "入职日期", "离职日期", "工龄", "岗位", "职务", "职级",
    "基本工资", "绩效工资", "加班工资", "津贴", "补贴",
    "社保", "公积金", "个税", "实发工资",
    "合计", "小计", "总计", "备注", "说明",
    "日期", "时间", "地点", "事由", "结果",

    # ── 常见业务词 ──
    "劳动合同", "劳务合同", "聘用合同", "用工合同",
    "社会保险", "住房公积金", "五险一金",
    "经济补偿金", "赔偿金", "违约金", "代通知金",
    "加班费", "年休假", "病假", "事假", "产假", "婚假",
    "劳动仲裁", "劳动争议", "劳动纠纷",
    "一审", "二审", "再审", "执行",
    "起诉状", "答辩状", "上诉状", "申诉状",
    "证据", "证据清单", "质证意见",
    "调解书", "判决书", "裁定书", "裁决书",
    "开庭", "庭审", "审理", "判决", "裁定",

    # ── OCR 碎片 ──
    "公司", "企业", "单位", "机构", "部门", "科室",
    "处", "局", "委", "办", "所", "院", "校", "厂", "场",
    "中心", "基地", "园区", "开发区", "试验区",
    "有限公司", "股份公司", "集团公司",
    "事务所", "律师事务所", "会计师事务所",

    # ── 常见地名误标 ──
    "北京", "上海", "广州", "深圳", "天津", "重庆",
    "杭州", "南京", "武汉", "成都", "西安", "长沙",
    "郑州", "济南", "合肥", "福州", "厦门", "南昌",
    "昆明", "贵阳", "兰州", "太原", "石家庄", "哈尔滨",
    "长春", "沈阳", "大连", "青岛", "宁波", "苏州",
    "无锡", "佛山", "东莞", "珠海", "中山", "惠州",
}

# Type restriction: allowlist only applies to NER-derived types
# (ORG, ADDRESS). It NEVER applies to structural PII.
ALLOWLIST_APPLICABLE_TYPES = {"ORG", "ADDRESS"}

# Structural PII types that are ALWAYS redacted regardless of allowlist
STRUCTURAL_PII_TYPES = {
    "PHONE", "LANDLINE", "ID_CARD", "EMAIL",
    "BANK_ACCOUNT", "BANK_INFO", "ORG_CODE",
    "CASE_NO",
}


def load_allowlist(
    builtin: bool = True,
    case_file: Optional[str] = None,
) -> Set[str]:
    """Load allowlist from built-in baseline and optional case-specific file.

    Args:
        builtin: Include built-in baseline allowlist (default True).
        case_file: Path to case-specific allowlist file (one term per line).
                   This file is local, NOT in git.

    Returns:
        Combined set of allowlist terms (lowercase for case-insensitive matching).
    """
    result: Set[str] = set()

    if builtin:
        result.update(term.lower() for term in BUILTIN_ALLOWLIST)

    if case_file:
        try:
            with open(case_file, "r", encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term and not line.startswith("#"):
                        result.add(term.lower())
        except FileNotFoundError:
            pass  # Case file is optional

    return result


def is_allowlist_applicable(entity_type: str) -> bool:
    """Check if allowlist rules apply to this entity type.

    Allowlist only applies to NER-derived types (ORG, ADDRESS).
    Structural PII types are NEVER affected by allowlist.
    """
    return entity_type in ALLOWLIST_APPLICABLE_TYPES


def is_structural_pii(entity_type: str) -> bool:
    """Check if entity type is structural PII (always redacted)."""
    return entity_type in STRUCTURAL_PII_TYPES
