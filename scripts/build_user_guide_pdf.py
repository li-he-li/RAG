from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "法律文书相似检索系统-用户操作指南.pdf"


def register_fonts() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="GuideTitle",
            parent=styles["Title"],
            fontName="STSong-Light",
            fontSize=24,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#143d35"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideSubtitle",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=11.5,
            leading=18,
            textColor=colors.HexColor("#55606e"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideH2",
            parent=styles["Heading2"],
            fontName="STSong-Light",
            fontSize=17,
            leading=22,
            textColor=colors.HexColor("#174a40"),
            spaceBefore=14,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideH3",
            parent=styles["Heading3"],
            fontName="STSong-Light",
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#214d45"),
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideBody",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=11,
            leading=18,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideBullet",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=11,
            leading=18,
            leftIndent=14,
            firstLineIndent=-10,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideTip",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=10.5,
            leading=16,
            textColor=colors.HexColor("#225949"),
            backColor=colors.HexColor("#eef7f3"),
            borderColor=colors.HexColor("#d8e7e0"),
            borderWidth=0.8,
            borderPadding=8,
            borderRadius=6,
            spaceBefore=4,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="GuideWarn",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=10.5,
            leading=16,
            textColor=colors.HexColor("#8a5a11"),
            backColor=colors.HexColor("#fff7e8"),
            borderColor=colors.HexColor("#ecd8ad"),
            borderWidth=0.8,
            borderPadding=8,
            borderRadius=6,
            spaceBefore=4,
            spaceAfter=8,
        )
    )
    return styles


def add_bullets(story: list, styles, items: list[str], ordered: bool = False) -> None:
    for index, item in enumerate(items, start=1):
        prefix = f"{index}. " if ordered else "• "
        story.append(Paragraph(prefix + item, styles["GuideBullet"]))


def add_table(story: list, styles, rows: list[tuple[str, str]]) -> None:
    data = [[Paragraph("<b>位置 / 场景</b>", styles["GuideBody"]), Paragraph("<b>说明</b>", styles["GuideBody"])]]
    for left, right in rows:
        data.append([Paragraph(left, styles["GuideBody"]), Paragraph(right, styles["GuideBody"])])
    table = Table(data, colWidths=[48 * mm, 120 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f7f4")),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#d8e1dc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))


def build_story():
    styles = build_styles()
    story = []

    story.append(Paragraph("法律文书相似检索系统", styles["GuideTitle"]))
    story.append(Paragraph("用户操作指南", styles["GuideTitle"]))
    story.append(
        Paragraph(
            "这份指南是写给日常使用系统的人看的。你不需要懂代码，只要按照页面按钮一步一步操作，就能完成文件上传、普通检索、合同审查、观点预测和类案检索。",
            styles["GuideSubtitle"],
        )
    )
    story.append(
        Paragraph(
            "当前系统主要有 4 类常用能力：普通聊天检索、合同审查、观点预测、类案检索。",
            styles["GuideTip"],
        )
    )

    story.append(Paragraph("1. 先认识页面", styles["GuideH2"]))
    add_table(
        story,
        styles,
        [
            ("左侧菜单", "进入“文件管理”“合同审查”“观点预测”“系统状态”等功能区。"),
            ("中间聊天区", "输入问题、查看回答、查看合同审查结果、观点预测结果和类案检索结果。"),
            ("输入框左侧按钮", "上传文件，或者切换成“合同审查”“观点预测”“类案检索”模式。"),
            ("右侧栏", "查看当前会话附件，或者查看回答引用了哪些文件片段。"),
        ],
    )
    story.append(
        Paragraph(
            "最容易混淆的一点是：不同功能用的文件不完全一样。普通聊天和类案检索主要看当前会话附件；合同审查要用标准模板加待审合同；观点预测要先建立案件模板。",
            styles["GuideTip"],
        )
    )

    story.append(Paragraph("2. 开始使用前，你要确认什么", styles["GuideH2"]))
    add_bullets(
        story,
        styles,
        [
            "如果系统已经有人帮你启动好了，你只需要打开网页即可。",
            "通常前端页面地址是 http://localhost:3000。",
            "如果网页能打开，但一直查不到结果，先点左侧“系统状态”看看服务是否正常。",
        ],
    )
    story.append(
        Paragraph(
            "如果系统状态里 PostgreSQL、Qdrant、Embedding、Reranker 长时间不是正常状态，先联系维护人员，不建议继续盲目操作。",
            styles["GuideWarn"],
        )
    )

    story.append(Paragraph("3. 四个最常用功能怎么用", styles["GuideH2"]))

    story.append(Paragraph("3.1 普通聊天检索：像聊天一样提问", styles["GuideH3"]))
    story.append(Paragraph("适合场景：你想直接问系统一个法律问题，或者让系统结合数据库材料给出回答。", styles["GuideBody"]))
    add_bullets(
        story,
        styles,
        [
            "直接在输入框里输入你的问题。",
            "点击发送按钮。",
            "如果你想让回答结合你手头的材料，先上传当前会话附件，再提问。",
            "回答出来后，如果页面里有“引用来源”，可以在右侧栏查看具体引用了哪几行内容。",
        ],
        ordered=True,
    )
    story.append(
        Paragraph(
            "建议把问题写完整一点。比如不要只写“帮我看一下”，最好写成“请结合我上传的材料，判断对方是否构成违约，并说明依据”。",
            styles["GuideTip"],
        )
    )

    story.append(Paragraph("3.2 合同审查：先准备模板，再审目标合同", styles["GuideH3"]))
    story.append(Paragraph("适合场景：你手里有一份待审合同，想按照某个标准模板去比对、找问题。", styles["GuideBody"]))
    add_bullets(
        story,
        styles,
        [
            "先点左侧“合同审查”。",
            "在左侧模板库上传标准合同模板。模板会显示在“模板列表”里。",
            "回到聊天区，点击输入框左侧“合同审查”按钮，切换成合同审查模式。",
            "再点击回形针上传待审合同。",
            "在输入框里写清楚你的要求，比如“请重点检查付款条款、违约责任和解除条件”。",
            "发送后，系统会先帮你匹配模板，再生成审查结果。",
        ],
        ordered=True,
    )
    story.append(
        Paragraph(
            "左侧上传的是“标准模板”，聊天区上传的是“待审合同”。这两个不是一回事，别传反了。",
            styles["GuideWarn"],
        )
    )

    story.append(Paragraph("3.3 观点预测：先建案件模板，再问问题", styles["GuideH3"]))
    story.append(Paragraph("适合场景：你想知道对方大概率会怎么答、会从哪里攻击、我方该怎么防。", styles["GuideBody"]))
    add_bullets(
        story,
        styles,
        [
            "点击左侧“观点预测”。",
            "填写案件名称。",
            "上传“案情材料”。这是必填项。",
            "如果你有答辩状、聊天记录、律师函等对方材料，也可以上传到“对方语料”。这一步不是必须，但通常很有帮助。",
            "点击“保存为案件模板”。",
            "回到聊天区，点“观点预测”按钮切换模式。",
            "直接输入问题，例如“对方最可能从哪些角度辩驳？”“对方最可能攻击我方哪条证据？”",
            "系统会提示你选择案件模板，然后给出预测报告。",
        ],
        ordered=True,
    )
    story.append(
        Paragraph(
            "想让结果更接近真实对方说法，就尽量补充真实的对方语料。对方语料越像真实答辩口径，结果通常越贴近实战。",
            styles["GuideTip"],
        )
    )

    story.append(Paragraph("3.4 类案检索：拿你上传的材料去找相似案件", styles["GuideH3"]))
    story.append(Paragraph("适合场景：你已经有一份案件材料，想看看库里有没有相似案件或同案不同版本。", styles["GuideBody"]))
    add_bullets(
        story,
        styles,
        [
            "先在当前会话里上传聊天附件。",
            "再点击输入框左侧“类案检索”按钮。",
            "你可以直接发送，也可以补一句要求，比如“优先找物业费拖欠和违约金争议的案件”。",
            "系统会返回同案命中、高度相似候选、普通相似案例，以及每个结果的原因、分数和引用片段。",
        ],
        ordered=True,
    )
    story.append(
        Paragraph(
            "这里最重要的一句：一定要先上传文件，再在同一个会话里使用“类案检索”。如果当前会话没有聊天附件，这个功能就没有材料可以比对。",
            styles["GuideWarn"],
        )
    )

    story.append(Paragraph("4. 文件到底要传到哪里", styles["GuideH2"]))
    add_table(
        story,
        styles,
        [
            ("普通聊天时，让回答参考你的材料", "上传到当前会话附件。"),
            ("做类案检索", "上传到当前会话附件。"),
            ("做合同审查的标准参照", "上传到左侧“合同审查”里的标准模板库。"),
            ("上传待审合同", "在聊天区进入合同审查模式后，用回形针上传。"),
            ("做观点预测", "上传到左侧“观点预测”里的案件模板。"),
        ],
    )

    story.append(Paragraph("5. 右侧栏怎么用", styles["GuideH2"]))
    add_bullets(
        story,
        styles,
        [
            "附件：查看当前会话里已经上传过哪些文件。类案检索主要就用这里的文件来比对。",
            "引用来源：查看系统回答时具体引用了哪个文件、哪一段。这个功能非常适合核对系统有没有说偏。",
        ],
    )

    story.append(Paragraph("6. 常见问题", styles["GuideH2"]))
    story.append(Paragraph("为什么我上传了文件，但回答里没用上？", styles["GuideH3"]))
    story.append(Paragraph("先确认你是不是把文件上传到了“当前会话附件”，而不是上传到了模板库或别的功能面板。", styles["GuideBody"]))
    story.append(Paragraph("为什么合同审查没开始？", styles["GuideH3"]))
    story.append(Paragraph("通常是因为没有标准模板，或者没有上传待审合同。", styles["GuideBody"]))
    story.append(Paragraph("为什么观点预测没有结果？", styles["GuideH3"]))
    story.append(Paragraph("通常是因为还没有先建立案件模板，或者没选模板就直接问了问题。", styles["GuideBody"]))
    story.append(Paragraph("为什么类案检索结果很少？", styles["GuideH3"]))
    story.append(Paragraph("可能是当前会话没有附件，也可能是补充要求写得太窄。建议先上传更完整的材料，再写明确但不要过窄的检索要求。", styles["GuideBody"]))
    story.append(Paragraph("“同案命中 / 高度相似 / 类案”有什么区别？", styles["GuideH3"]))
    story.append(Paragraph("可以简单理解为：同案命中最接近原文；高度相似通常是非常近的版本或非常接近的案件；类案是争议点、事实结构或法律关系相近，但不一定是同一个案子。", styles["GuideBody"]))

    story.append(Paragraph("7. 推荐的使用顺序", styles["GuideH2"]))
    add_bullets(
        story,
        styles,
        [
            "先看“系统状态”，确认服务正常。",
            "普通检索或类案检索前，先把材料传到当前会话附件。",
            "合同审查前，先建好标准模板。",
            "观点预测前，先建好案件模板。",
            "结果出来后，养成查看“引用来源”的习惯。",
        ],
        ordered=True,
    )
    story.append(
        Paragraph(
            "这份指南适合日常业务人员、法务、律师助理或第一次接触系统的使用者。",
            styles["GuideTip"],
        )
    )
    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    register_fonts()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="法律文书相似检索系统-用户操作指南",
    )
    doc.build(build_story())
    print(OUTPUT)


if __name__ == "__main__":
    main()
