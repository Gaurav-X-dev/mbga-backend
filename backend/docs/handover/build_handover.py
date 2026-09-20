"""Build the Customer/Merchant authentication handover as Markdown and DOCX.

Usage: python build_handover.py   (requires python-docx)
"""

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from content import BLOCKS, META, TITLE

OUT = Path(__file__).parent
NAME = "MBGA_Customer_Merchant_Auth_Handover"
NAVY = RGBColor(0x14, 0x2B, 0x4C)
TEAL = RGBColor(0x0E, 0x6B, 0x74)
INK = RGBColor(0x22, 0x2A, 0x33)
MUTED = RGBColor(0x5B, 0x66, 0x73)
HEADER_FILL = "142B4C"
ZEBRA_FILL = "F2F5F8"
CODE_FILL = "F4F6F8"
CALLOUT = {"info": ("E8F1F8", "1F5F99"), "warning": ("FFF4E0", "B26A00"), "critical": ("FDECEC", "B42318")}
PORTRAIT_WIDTH_CM = 17.2
LANDSCAPE_WIDTH_CM = 25.9
INLINE = re.compile(r"(\*\*.+?\*\*|`.+?`)")


# ------------------------------------------------------------------ Markdown

def md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def build_markdown() -> str:
    out = [f"# {TITLE}", ""]
    out += ["| Item | Value |", "| --- | --- |"] + [f"| {k} | {md_cell(v)} |" for k, v in META] + [""]
    out += ["## Contents", ""]
    for block in BLOCKS:
        if block[0] == "h1":
            anchor = re.sub(r"[^a-z0-9 -]", "", block[1].lower()).replace(" ", "-")
            out.append(f"- [{block[1]}](#{anchor})")
    out.append("")
    for block in BLOCKS:
        kind = block[0]
        if kind == "h1":
            out += [f"## {block[1]}", ""]
        elif kind == "h2":
            out += [f"### {block[1]}", ""]
        elif kind == "h3":
            out += [f"#### {block[1]}", ""]
        elif kind == "p":
            out += [block[1], ""]
        elif kind == "bullets":
            out += [f"- {item}" for item in block[1]] + [""]
        elif kind == "numbers":
            out += [f"{i}. {item}" for i, item in enumerate(block[1], 1)] + [""]
        elif kind == "code":
            out += ["```text", block[1], "```", ""]
        elif kind == "callout":
            label = {"info": "Note", "warning": "Important", "critical": "Critical"}[block[1]]
            lines = block[2].split("\n")
            out += [f"> **{label}:** {lines[0]}"] + [f"> {line}" for line in lines[1:]] + [""]
        elif kind == "table":
            headers, rows = block[1], block[2]
            out.append("| " + " | ".join(md_cell(h) for h in headers) + " |")
            out.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows:
                assert len(row) == len(headers), (headers, row)
                out.append("| " + " | ".join(md_cell(c) for c in row) + " |")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------------ DOCX helpers

def shade(cell_or_par, fill: str) -> None:
    props = cell_or_par._tc.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") else cell_or_par._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def par_border(par, color: str, side: str = "left", size: int = 24) -> None:
    ppr = par._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    edge = OxmlElement(f"w:{side}")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), str(size))
    edge.set(qn("w:space"), "8")
    edge.set(qn("w:color"), color)
    borders.append(edge)
    ppr.append(borders)


def add_runs(par, text: str, size: float | None = None, color: RGBColor | None = None, bold: bool = False) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = par.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = par.add_run(part[1:-1])
            run.font.name = "Consolas"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            run.font.color.rgb = TEAL
        else:
            run = par.add_run(part)
            run.bold = bold or None
        if size:
            run.font.size = Pt(size if not part.startswith("`") else size - 0.5)
        if color is not None and not part.startswith("`"):
            run.font.color.rgb = color


def set_cell_margins(table, top=60, bottom=60, left=90, right=90) -> None:
    tbl_pr = table._tbl.tblPr
    margins = OxmlElement("w:tblCellMar")
    for side, value in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(value))
        el.set(qn("w:type"), "dxa")
        margins.append(el)
    tbl_pr.append(margins)


def set_column_widths(table, widths_cm) -> None:
    """Keep the table grid, the table width and every cell width identical (Word, LibreOffice and
    Google Docs each read a different one)."""
    twips = [int(round(w * 566.929)) for w in widths_cm]
    grid = table._tbl.tblGrid
    for col, value in zip(grid.findall(qn("w:gridCol")), twips):
        col.set(qn("w:w"), str(value))
    tbl_w = table._tbl.tblPr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        table._tbl.tblPr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(twips)))
    tbl_w.set(qn("w:type"), "dxa")
    for row in table.rows:
        for cell, value in zip(row.cells, widths_cm):
            cell.width = Cm(value)


def fixed_layout(table) -> None:
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    table._tbl.tblPr.append(layout)


def repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def no_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def add_field(par, instruction: str) -> None:
    for tag, text in (("begin", None), (None, instruction), ("separate", None), (None, "1"), ("end", None)):
        run = par.add_run()
        if tag:
            fld = OxmlElement("w:fldChar")
            fld.set(qn("w:fldCharType"), tag)
            run._r.append(fld)
        elif text == instruction:
            instr = OxmlElement("w:instrText")
            instr.set(qn("xml:space"), "preserve")
            instr.text = f" {instruction} "
            run._r.append(instr)
        else:
            run.text = text
        run.font.size = Pt(8)
        run.font.color.rgb = MUTED


def setup_section(section, landscape: bool) -> None:
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(1.9)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.8)
    section.header_distance = Cm(0.9)
    section.footer_distance = Cm(0.8)


def decorate_header_footer(section) -> None:
    section.different_first_page_header_footer = False
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.text = ""
    add_runs(hp, "MBGA · Customer and Merchant Authentication Handover", size=8, color=MUTED)
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    par_border(hp, "C9D2DC", side="bottom", size=4)
    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_runs(fp, "Backend Team · 17 September 2026 · Page ", size=8, color=MUTED)
    add_field(fp, "PAGE")
    add_runs(fp, " of ", size=8, color=MUTED)
    add_field(fp, "NUMPAGES")


# ------------------------------------------------------------------ DOCX build

def plan_orientation(blocks) -> list[bool]:
    """Orientation per block: a group (h1 or h2 up to the next heading) is landscape if it holds a landscape
    table. A group without any table takes the orientation of the next group, so headings are never left
    alone on a page before an orientation change."""
    groups, current = [], []
    for index, block in enumerate(blocks):
        if block[0] in ("h1", "h2") and current:
            groups.append(current)
            current = []
        current.append(index)
    groups.append(current)
    flags = []
    for group in groups:
        tables = [blocks[i] for i in group if blocks[i][0] == "table"]
        flags.append(None if not tables else any(t[4].get("landscape") for t in tables))
    for i in range(len(flags) - 1, -1, -1):
        if flags[i] is None:
            is_intro = all(blocks[j][0] in ("h1", "h2", "p") for j in groups[i]) and len(groups[i]) <= 2
            flags[i] = flags[i + 1] if (is_intro and i + 1 < len(flags)) else False
    result = [False] * len(blocks)
    for group, flag in zip(groups, flags):
        for i in group:
            result[i] = flag
    return result


class DocBuilder:
    def __init__(self) -> None:
        self.doc = Document()
        self.landscape = False
        self._styles()
        setup_section(self.doc.sections[0], landscape=False)

    def _styles(self) -> None:
        styles = self.doc.styles
        normal = styles["Normal"]
        normal.font.name = "Calibri"
        normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        normal.font.size = Pt(10)
        normal.font.color.rgb = INK
        normal.paragraph_format.space_after = Pt(5)
        normal.paragraph_format.line_spacing = 1.12
        for name, size, color, before, after in (
            ("Heading 1", 16, NAVY, 16, 6),
            ("Heading 2", 12.5, TEAL, 12, 4),
            ("Heading 3", 11, NAVY, 10, 3),
        ):
            style = styles[name]
            style.font.name = "Calibri"
            style._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.color.rgb = color
            style.paragraph_format.space_before = Pt(before)
            style.paragraph_format.space_after = Pt(after)
            style.paragraph_format.keep_with_next = True

    @property
    def width(self) -> float:
        return LANDSCAPE_WIDTH_CM if self.landscape else PORTRAIT_WIDTH_CM

    def orientation(self, landscape: bool) -> None:
        if landscape == self.landscape:
            return
        section = self.doc.add_section(WD_SECTION.NEW_PAGE)
        setup_section(section, landscape)
        decorate_header_footer(section)
        self.landscape = landscape

    # -------------------------------------------------------------- title page

    def title_page(self) -> None:
        doc = self.doc
        for _ in range(5):
            doc.add_paragraph()
        band = doc.add_paragraph()
        add_runs(band, "MBGA COMMERCIAL LPG PLATFORM", size=10, color=TEAL, bold=True)
        title = doc.add_paragraph()
        title.paragraph_format.space_after = Pt(10)
        add_runs(title, TITLE, size=26, color=NAVY, bold=True)
        par_border(title, "0E6B74", side="left", size=36)
        sub = doc.add_paragraph()
        add_runs(sub, "Backend-to-mobile implementation handover for the Customer and Merchant apps", size=12, color=MUTED)
        doc.add_paragraph()
        table = doc.add_table(rows=0, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        fixed_layout(table)
        set_cell_margins(table, 70, 70, 100, 100)
        for key, value in META:
            row = table.add_row()
            for i, (text, width) in enumerate(((key, 5.0), (value, 12.2))):
                cell = row.cells[i]
                cell.width = Cm(width)
                par = cell.paragraphs[0]
                add_runs(par, text, size=10, color=NAVY if i == 0 else INK, bold=i == 0)
                par.paragraph_format.space_after = Pt(0)
            shade(row.cells[0], "E9EEF4")
        set_column_widths(table, [5.0, 12.2])
        doc.add_paragraph()
        note = doc.add_paragraph()
        add_runs(note, "Confidential project document. Contains no credentials, OTPs, tokens or personal data; "
                       "all examples use placeholders.", size=8.5, color=MUTED)
        decorate_header_footer(doc.sections[0])
        self.page_break()

    def contents(self) -> None:
        heading = self.doc.add_paragraph(style="Heading 1")
        add_runs(heading, "Contents")
        for block in BLOCKS:
            if block[0] not in ("h1", "h2"):
                continue
            par = self.doc.add_paragraph()
            par.paragraph_format.space_after = Pt(1)
            if block[0] == "h1":
                add_runs(par, block[1], size=10, color=NAVY, bold=True)
                par.paragraph_format.space_before = Pt(4)
            else:
                par.paragraph_format.left_indent = Cm(0.8)
                add_runs(par, block[1], size=9, color=MUTED)
        self.page_break()

    def page_break(self) -> None:
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # -------------------------------------------------------------- blocks

    def heading(self, level: int, text: str) -> None:
        par = self.doc.add_paragraph(style=f"Heading {level}")
        add_runs(par, text)
        if level == 1:
            par_border(par, "C9D2DC", side="bottom", size=6)

    def paragraph(self, text: str) -> None:
        add_runs(self.doc.add_paragraph(), text)

    def items(self, items, numbered: bool) -> None:
        for index, item in enumerate(items, 1):
            par = self.doc.add_paragraph()
            par.paragraph_format.left_indent = Cm(0.7)
            par.paragraph_format.first_line_indent = Cm(-0.45)
            par.paragraph_format.space_after = Pt(3)
            marker = f"{index}. " if numbered else "•  "
            run = par.add_run(marker)
            run.font.color.rgb = TEAL
            run.bold = True
            add_runs(par, item)

    def code(self, text: str) -> None:
        limit = 98 if self.landscape else 92
        for line in text.split("\n"):
            assert len(line) <= limit, f"code line too long ({len(line)}): {line}"
        par = self.doc.add_paragraph()
        par.paragraph_format.space_before = Pt(2)
        par.paragraph_format.space_after = Pt(8)
        par.paragraph_format.line_spacing = 1.0
        par.paragraph_format.left_indent = Cm(0.15)
        par.paragraph_format.keep_together = True
        shade(par, CODE_FILL)
        par_border(par, "9FB3C8", side="left", size=12)
        for i, line in enumerate(text.split("\n")):
            run = par.add_run(line)
            run.font.name = "Consolas"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            run.font.size = Pt(8)
            run.font.color.rgb = INK
            if i < len(text.split("\n")) - 1:
                run.add_break()

    def callout(self, kind: str, text: str) -> None:
        fill, edge = CALLOUT[kind]
        label = {"info": "Note", "warning": "Important", "critical": "Critical"}[kind]
        par = self.doc.add_paragraph()
        par.paragraph_format.space_before = Pt(4)
        par.paragraph_format.space_after = Pt(8)
        par.paragraph_format.left_indent = Cm(0.15)
        par.paragraph_format.keep_together = True
        shade(par, fill)
        par_border(par, edge, side="left", size=30)
        lines = text.split("\n")
        run = par.add_run(f"{label}: ")
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(edge)
        for i, line in enumerate(lines):
            add_runs(par, line, size=9.5)
            if i < len(lines) - 1:
                par.add_run().add_break()

    def table(self, headers, rows, widths, options) -> None:
        total = sum(widths)
        assert total <= self.width + 0.05, f"table too wide: {total} > {self.width} ({headers})"
        font = options.get("font", 8.5)
        table = self.doc.add_table(rows=1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"
        fixed_layout(table)
        set_cell_margins(table)
        head = table.rows[0]
        repeat_header(head)
        for i, text in enumerate(headers):
            cell = head.cells[i]
            cell.width = Cm(widths[i])
            shade(cell, HEADER_FILL)
            par = cell.paragraphs[0]
            par.paragraph_format.space_after = Pt(0)
            add_runs(par, text, size=font, color=RGBColor(0xFF, 0xFF, 0xFF), bold=True)
        for r, values in enumerate(rows):
            assert len(values) == len(headers), (headers, values)
            row = table.add_row()
            no_split(row)
            for i, value in enumerate(values):
                cell = row.cells[i]
                cell.width = Cm(widths[i])
                if r % 2 == 1:
                    shade(cell, ZEBRA_FILL)
                lines = str(value).split("\n")
                par = cell.paragraphs[0]
                par.paragraph_format.space_after = Pt(0)
                par.paragraph_format.line_spacing = 1.05
                for j, line in enumerate(lines):
                    add_runs(par, line, size=font)
                    if j < len(lines) - 1:
                        par.add_run().add_break()
        borders = table._tbl.tblPr.find(qn("w:tblBorders"))
        if borders is None:
            borders = OxmlElement("w:tblBorders")
            table._tbl.tblPr.append(borders)
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            el = OxmlElement(f"w:{side}")
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), "C9D2DC")
            borders.append(el)
        set_column_widths(table, widths)
        spacer = self.doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(4)

    def build(self) -> Document:
        self.title_page()
        self.contents()
        orientations = plan_orientation(BLOCKS)
        for block, landscape in zip(BLOCKS, orientations):
            kind = block[0]
            self.orientation(landscape)
            if kind == "h1":
                self.heading(1, block[1])
            elif kind == "h2":
                self.heading(2, block[1])
            elif kind == "h3":
                self.heading(3, block[1])
            elif kind == "p":
                self.paragraph(block[1])
            elif kind == "bullets":
                self.items(block[1], numbered=False)
            elif kind == "numbers":
                self.items(block[1], numbered=True)
            elif kind == "code":
                self.code(block[1])
            elif kind == "callout":
                self.callout(block[1], block[2])
            elif kind == "table":
                self.table(*block[1:])
            elif kind == "pagebreak":
                self.page_break()
        props = self.doc.core_properties
        props.title = TITLE
        props.subject = "Authentication API implementation handover"
        props.author = "Backend Team"
        props.keywords = "MBGA, authentication, OTP, mobile, handover"
        return self.doc


def main() -> None:
    (OUT / f"{NAME}.md").write_text(build_markdown(), encoding="utf-8")
    DocBuilder().build().save(OUT / f"{NAME}.docx")
    print("written", OUT / f"{NAME}.md", OUT / f"{NAME}.docx")


if __name__ == "__main__":
    main()
