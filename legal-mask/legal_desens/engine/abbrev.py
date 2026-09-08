"""Document-based org abbreviation dictionary: conservative, document-internal."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .span import Span

# Suffixes to strip from org full names to get significant stem
_ORG_STRIP_SUFFIXES = [
    "有限责任公司", "股份有限公司", "有限公司", "股份公司",
    "律师事务所", "法律服务所", "法律援助中心",
    "人民法院", "中级人民法院", "基层人民法院", "人民检察院",
    "集团", "银行", "信用社",
    "研究院", "研究所", "研究中心",
    "医院", "学校", "大学", "学院",
]

# Administrative prefixes to strip (longer forms first)
_ADMIN_PREFIXES = [
    "中国", "中华", "国家", "全国",
    "北京市", "上海市", "天津市", "重庆市",
    "广东省", "深圳市", "广州市", "浙江省", "杭州市", "江苏省", "南京市",
    "四川省", "成都市", "湖北省", "武汉市", "湖南省", "长沙市",
    "山东省", "济南市", "河南省", "郑州市", "河北省", "石家庄市",
    "福建省", "厦门市", "安徽省", "合肥市", "江西省", "南昌市",
    "辽宁省", "沈阳市", "吉林省", "长春市", "黑龙江省", "哈尔滨市",
    "陕西省", "西安市", "甘肃省", "兰州市", "云南省", "昆明市",
    "贵州省", "贵阳市", "海南省", "广西壮族自治区", "内蒙古自治区",
    "西藏自治区", "新疆维吾尔自治区", "宁夏回族自治区", "青海省",
    # Short forms
    "北京", "上海", "天津", "重庆",
    "广东", "深圳", "广州", "浙江", "杭州", "江苏", "南京",
    "四川", "成都", "湖北", "武汉", "湖南", "长沙",
    "山东", "济南", "河南", "郑州", "河北", "石家庄",
    "福建", "厦门", "安徽", "合肥", "江西", "南昌",
    "辽宁", "沈阳", "吉林", "长春", "黑龙江", "哈尔滨",
    "陕西", "西安", "甘肃", "兰州", "云南", "昆明",
    "贵州", "贵阳", "海南", "广西", "内蒙古", "西藏", "新疆", "宁夏", "青海",
]

# Minimum stem length to be considered significant
_MIN_STEM_LENGTH = 2


def _extract_stem(org_name: str) -> Optional[str]:
    """Extract significant stem from org full name.

    Returns None if stem is too short or not meaningful.
    """
    stem = org_name

    # Strip admin prefixes
    for prefix in sorted(_ADMIN_PREFIXES, key=len, reverse=True):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break

    # Strip org suffixes
    for suffix in sorted(_ORG_STRIP_SUFFIXES, key=len, reverse=True):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break

    # Strip trailing whitespace/punctuation
    stem = stem.strip()

    if len(stem) < _MIN_STEM_LENGTH:
        return None

    # Avoid overly common stems that would cause false positives
    _COMMON_STEMS = {"人民", "中国", "中华", "国家", "工商", "建设", "农业", "发展"}
    if stem in _COMMON_STEMS:
        return None

    return stem


def build_abbrev_dict(org_full_names: List[str]) -> Dict[str, str]:
    """Build abbreviation dictionary from org full names found in document.

    Returns: {abbrev_form: full_name} where abbrev_form = stem + 公司/所/院 etc.
    Only includes stems with length >= 2.
    """
    abbrev_dict: Dict[str, str] = {}

    for full_name in org_full_names:
        stem = _extract_stem(full_name)
        if stem is None:
            continue

        # Generate possible abbreviation forms
        # The most common pattern is stem + 公司
        abbrev_candidates = [stem + "公司"]

        # For law firms
        if "律" in full_name or "事务所" in full_name:
            abbrev_candidates.append(stem + "所")

        # For courts
        if "法院" in full_name:
            abbrev_candidates.append(stem + "法院")

        for abbrev in abbrev_candidates:
            if abbrev != full_name and len(abbrev) >= _MIN_STEM_LENGTH + 2:
                abbrev_dict[abbrev] = full_name

    return abbrev_dict


def find_abbreviations(
    text: str,
    org_full_names: List[str],
    existing_spans: List[Span],
) -> List[Span]:
    """Find abbreviated org names in text that correspond to full names.

    Only triggers when the full name has already appeared in the document.
    Returns new spans for abbreviated forms not already covered by existing spans.
    """
    abbrev_dict = build_abbrev_dict(org_full_names)
    if not abbrev_dict:
        return []

    # Collect regions already covered by existing spans
    covered_regions: List[Tuple[int, int]] = [
        (s.start, s.end) for s in existing_spans
    ]

    def is_covered(start: int, end: int) -> bool:
        for cs, ce in covered_regions:
            if start < ce and end > cs:
                return True
        return False

    new_spans: List[Span] = []
    order = max((s.discovery_order for s in existing_spans), default=0) + 1

    for abbrev, full_name in abbrev_dict.items():
        # Find all occurrences of the abbreviation
        idx = 0
        while True:
            pos = text.find(abbrev, idx)
            if pos == -1:
                break
            end = pos + len(abbrev)
            if not is_covered(pos, end):
                new_spans.append(Span(
                    entity_type="ORG",
                    start=pos,
                    end=end,
                    text=text[pos:end],
                    engine="regex",
                    rule_id="org_abbrev",
                    priority=95,  # Slightly below full match
                    discovery_order=order,
                ))
                order += 1
            idx = end

    return new_spans
