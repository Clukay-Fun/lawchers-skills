"""Synthetic fixtures for NER evaluation (012 stage).

All text is artificial. No real PII. Covers:
- Four entity types: PERSON, ORG, LOCATION, MONEY
- Boundary cases: adjacent entities, nested/overlapping, no entity, ambiguity
"""

from __future__ import annotations

from .schema import Annotation, Entity, _generate_bio_tags


def _make_annotation(
    ann_id: str,
    text: str,
    raw_entities: list[tuple[str, int, int]],
) -> Annotation:
    """Helper to build an Annotation with auto-generated BIO tags.

    raw_entities: list of (entity_type, start, end)
    """
    entities = [
        Entity(
            id=f"{ann_id}_e{i}",
            entity_type=etype,
            start=start,
            end=end,
            text=text[start:end],
        )
        for i, (etype, start, end) in enumerate(raw_entities)
    ]
    bio_tags = _generate_bio_tags(text, entities, scheme="BIO")
    return Annotation(id=ann_id, text=text, entities=entities, bio_tags=bio_tags)


# ── Fixture 1: Basic sentence with all four types ─────────────────────────────

FIX_BASIC = _make_annotation(
    "basic",
    "张三向北京市朝阳区人民法院提交起诉状，请求判令北京某某科技有限公司支付货款人民币10000元。",
    [
        ("PERSON", 0, 2),      # 张三
        ("LOCATION", 3, 9),    # 北京市朝阳区
        ("ORG", 9, 13),        # 人民法院
        ("ORG", 23, 33),       # 北京某某科技有限公司
        ("MONEY", 37, 46),     # 人民币10000元
    ],
)

# ── Fixture 2: Adjacent entities (no gap) ─────────────────────────────────────

FIX_ADJACENT = _make_annotation(
    "adjacent",
    "原告李四被告王五均到庭参加诉讼。",
    [
        ("PERSON", 2, 4),  # 李四
        ("PERSON", 6, 8),  # 王五
    ],
)

# ── Fixture 3: Single entity ──────────────────────────────────────────────────

FIX_SINGLE = _make_annotation(
    "single",
    "上海某某律师事务所接受委托。",
    [
        ("ORG", 0, 9),  # 上海某某律师事务所
    ],
)

# ── Fixture 4: No entities ────────────────────────────────────────────────────

FIX_NO_ENTITY = _make_annotation(
    "no_entity",
    "本案依法受理，现已审理终结。",
    [],
)

# ── Fixture 5: Multiple same-type entities ────────────────────────────────────

FIX_MULTI_SAME = _make_annotation(
    "multi_same",
    "张三、李四、王五三人签订合作协议。",
    [
        ("PERSON", 0, 2),   # 张三
        ("PERSON", 3, 5),   # 李四
        ("PERSON", 6, 8),   # 王五
    ],
)

# ── Fixture 6: MONEY with various formats ─────────────────────────────────────

FIX_MONEY = _make_annotation(
    "money_variants",
    "赔偿金额为人民币五万元整，另支付违约金10000元及利息3.5万元。",
    [
        ("MONEY", 5, 12),    # 人民币五万元整
        ("MONEY", 16, 25),   # 违约金10000元
        ("MONEY", 26, 33),   # 利息3.5万元
    ],
)

# ── Fixture 7: ORG with court name ────────────────────────────────────────────

FIX_COURT = _make_annotation(
    "court",
    "北京市第一中级人民法院作出（2024）京01民初123号民事判决书。",
    [
        ("ORG", 0, 11),  # 北京市第一中级人民法院
    ],
)

# ── Fixture 8: Location at various granularities ─────────────────────────────

FIX_LOCATION = _make_annotation(
    "location_levels",
    "甲住所地为广东省深圳市南山区，乙住所地为浙江省杭州市。",
    [
        ("LOCATION", 5, 14),   # 广东省深圳市南山区
        ("LOCATION", 20, 26),  # 浙江省杭州市
    ],
)

# ── Fixture 9: Ambiguous text (could be person or org) ────────────────────────

FIX_AMBIGUOUS = _make_annotation(
    "ambiguous",
    "长城公司与张三签订劳动合同，长城公司为用人单位。",
    [
        ("ORG", 0, 4),      # 长城公司 (first)
        ("PERSON", 5, 7),   # 张三
        ("ORG", 13, 17),    # 长城公司 (second)
    ],
)

# ── Fixture 10: Stress test with fullwidth / emoji / CRLF ─────────────────────

FIX_STRESS = _make_annotation(
    "stress",
    "张三  在上海市浦东新区签署合同，金额为１２０００元。\r\n甲方：北京某某科技有限公司",
    [
        ("PERSON", 0, 2),      # 张三
        ("LOCATION", 5, 14),   # 上海市浦东新区
        ("MONEY", 20, 27),     # １２０００元
        ("ORG", 32, 42),       # 北京某某科技有限公司
    ],
)

# ── Fixture 11: Boundary - entity at start and end of text ────────────────────

FIX_BOUNDARY = _make_annotation(
    "boundary",
    "张三起诉某某公司要求赔偿损失人民币10000元整",
    [
        ("PERSON", 0, 2),      # 张三
        ("ORG", 4, 8),         # 某某公司
        ("MONEY", 14, 24),     # 人民币10000元整
    ],
)

# ── Fixture 12: Long text with mixed entities ─────────────────────────────────

FIX_LONG = _make_annotation(
    "long",
    "原告张三诉被告李四民间借贷纠纷一案，本院于2024年1月1日立案后，依法适用简易程序。"
    "原告张三向本院提出诉讼请求：判令被告李四偿还借款人民币50000元及利息。"
    "事实与理由：2023年6月，被告李四因经营北京某某贸易有限公司需要资金，"
    "向原告张三借款人民币50000元，双方约定于2023年12月31日前归还。"
    "借款到期后，原告张三多次催要，被告李四拒不归还。",
    [
        ("PERSON", 2, 4),       # 张三
        ("PERSON", 7, 9),       # 李四
        ("PERSON", 45, 47),     # 张三
        ("PERSON", 61, 63),     # 李四
        ("MONEY", 67, 76),      # 人民币50000元
        ("PERSON", 96, 98),     # 李四
        ("ORG", 101, 111),      # 北京某某贸易有限公司
        ("PERSON", 119, 121),   # 张三
        ("MONEY", 123, 132),    # 人民币50000元
        ("PERSON", 161, 163),   # 张三
        ("PERSON", 170, 172),   # 李四
    ],
)


# ── All fixtures as a list ────────────────────────────────────────────────────

SYNTHETIC_ANNOTATIONS: list[Annotation] = [
    FIX_BASIC,
    FIX_ADJACENT,
    FIX_SINGLE,
    FIX_NO_ENTITY,
    FIX_MULTI_SAME,
    FIX_MONEY,
    FIX_COURT,
    FIX_LOCATION,
    FIX_AMBIGUOUS,
    FIX_STRESS,
    FIX_BOUNDARY,
    FIX_LONG,
]
