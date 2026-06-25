"""Generate synthetic 3-page scanned PDF for OCR spike evaluation.

No real client data. All names/phones/IDs are synthetic.
Simulates: labor contract / termination notice / arbitration application.
Dense sensitive entities: person names, phones, ID cards, companies, amounts, dates, addresses.
"""

import os
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

OUT_DIR = os.path.join(os.path.dirname(__file__), "samples")
os.makedirs(OUT_DIR, exist_ok=True)


def _get_font(size=20):
    """Try to find a CJK font for realistic rendering."""
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _render_page(lines, filename, size=(1240, 1754)):
    """Render text lines onto a white image simulating a scanned page."""
    img = Image.new("RGB", size, (252, 250, 245))  # slightly off-white like scan
    draw = ImageDraw.Draw(img)
    font = _get_font(22)
    y = 60
    for line in lines:
        draw.text((80, y), line, fill=(30, 30, 30), font=font)
        y += 36
    path = os.path.join(OUT_DIR, filename)
    img.save(path, "PNG")
    return path


def main():
    # === Page 1: Labor Contract ===
    page1_lines = [
        "劳动合同书",
        "",
        "甲方（用人单位）：北京明远科技有限公司",
        "统一社会信用代码：91110108MA01ABCDEF",
        "法定代表人：张伟华",
        "注册地址：北京市海淀区中关村南大街12号院3号楼1506室",
        "",
        "乙方（劳动者）：李晓明",
        "身份证号码：110108199203151234",
        "联系电话：13812345678",
        "户籍地址：河北省石家庄市桥西区中山路88号",
        "",
        "第一条 合同期限",
        "本合同为固定期限劳动合同，自2025年3月1日起至2028年2月28日止。",
        "试用期自2025年3月1日起至2025年5月31日止。",
        "",
        "第二条 工作内容与工作地点",
        "乙方同意在甲方技术研发部门担任高级软件工程师岗位，",
        "工作地点为北京市海淀区中关村南大街12号。",
        "",
        "第三条 劳动报酬",
        "乙方月工资为人民币28000元（税前），其中基本工资22000元，",
        "绩效工资6000元。工资发放日为每月15日。",
        "甲方于每月15日通过银行转账方式将工资转入乙方指定账户：",
        "开户银行：中国工商银行北京海淀支行",
        "银行账号：6222021234567890123",
        "",
        "第四条 社会保险与住房公积金",
        "甲方依法为乙方缴纳养老保险、医疗保险、失业保险、",
        "工伤保险、生育保险及住房公积金。",
        "",
        "签订日期：2025年3月1日",
        "",
        "甲方（盖章）：                乙方（签字）：",
        "张伟华                       李晓明",
    ]

    # === Page 2: Termination Notice ===
    page2_lines = [
        "解除劳动合同通知书",
        "",
        "致：李晓明",
        "身份证号码：110108199203151234",
        "",
        "您与北京明远科技有限公司签订的劳动合同（合同期限：",
        "2025年3月1日至2028年2月28日），经公司研究决定，",
        "依据《中华人民共和国劳动合同法》第四十条第（三）项之规定，",
        "于2026年1月15日解除与您的劳动合同关系。",
        "",
        "经济补偿方案：",
        "1. 经济补偿金：人民币42000元（按工作年限1年×月工资28000元×1.5倍）",
        "2. 代通知金：人民币28000元",
        "3. 未休年假工资：人民币5600元",
        "4. 合计：人民币75600元",
        "",
        "上述款项将于2026年1月20日前转入您的工资账户：",
        "开户银行：中国工商银行北京海淀支行",
        "银行账号：6222021234567890123",
        "",
        "请于2026年1月15日前办理工作交接手续。",
        "",
        "联系人：王丽芳（人力资源部）",
        "联系电话：010-82345678",
        "手机号码：13987654321",
        "",
        "特此通知。",
        "",
        "北京明远科技有限公司",
        "2026年1月10日",
        "",
        "签收人：李晓明",
        "签收日期：2026年1月10日",
    ]

    # === Page 3: Arbitration Application ===
    page3_lines = [
        "劳动争议仲裁申请书",
        "",
        "申请人：李晓明",
        "身份证号码：110108199203151234",
        "住所地：北京市朝阳区望京西路66号院8号楼1203室",
        "联系电话：13812345678",
        "",
        "被申请人：北京明远科技有限公司",
        "统一社会信用代码：91110108MA01ABCDEF",
        "法定代表人：张伟华",
        "住所地：北京市海淀区中关村南大街12号院3号楼1506室",
        "联系电话：010-82345678",
        "",
        "仲裁请求：",
        "1. 裁决被申请人支付违法解除劳动合同赔偿金人民币84000元",
        "   （计算方式：28000元×1.5年×2倍）",
        "2. 裁决被申请人支付2025年12月绩效工资差额人民币3000元",
        "3. 裁决被申请人支付未提前三十日通知的代通知金人民币28000元",
        "4. 裁决被申请人补缴2025年3月至2026年1月住房公积金差额人民币15600元",
        "",
        "事实与理由：",
        "申请人于2025年3月1日入职被申请人处，担任高级软件工程师，",
        '月工资人民币28000元。2026年1月10日，被申请人以\u201c客观情况发生',
        '重大变化\u201d为由，向申请人送达解除劳动合同通知书。',
        "",
        "申请人认为，被申请人的解除行为违反《劳动合同法》相关规定，",
        "构成违法解除，应依法支付赔偿金。",
        "",
        "证人：赵志刚",
        "身份证号码：110105198807206789",
        "联系电话：15600123456",
        "",
        "证据清单：",
        "1. 劳动合同书复印件",
        "2. 解除劳动合同通知书复印件",
        "3. 工资银行流水（2025年3月至2026年1月）",
        "4. 社保缴费记录",
        "",
        "申请人：李晓明",
        "日期：2026年1月20日",
    ]

    pages = [
        (page1_lines, "page1_contract.png"),
        (page2_lines, "page2_termination.png"),
        (page3_lines, "page3_arbitration.png"),
    ]

    image_paths = []
    for lines, filename in pages:
        path = _render_page(lines, filename)
        image_paths.append(path)
        print(f"  Generated: {path}")

    # Combine into a single 3-page PDF
    pdf_path = os.path.join(OUT_DIR, "synthetic_labor_case_3pages.pdf")
    doc = fitz.open()
    for img_path in image_paths:
        img_doc = fitz.open(img_path)
        pdfbytes = img_doc.convert_to_pdf()
        img_doc.close()
        pdf_part = fitz.open("pdf", pdfbytes)
        doc.insert_pdf(pdf_part)
        pdf_part.close()
    doc.save(pdf_path)
    doc.close()
    print(f"\n  PDF: {pdf_path}  ({os.path.getsize(pdf_path)} bytes)")

    # Also save individual page images for overlay later
    print("\nDone. Samples in:", OUT_DIR)


if __name__ == "__main__":
    main()
