"""Safe, in-memory report exports with no server-side file persistence."""

import csv
import io
import json
import re
import zipfile
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi.responses import StreamingResponse

from app.modules.reports.constants import ExportFormat
from app.modules.reports.schemas import ReportResponse

FORMULA_PREFIXES = ("=", "+", "-", "@")


def export_response(report: ReportResponse, export_format: ExportFormat) -> StreamingResponse:
    stamp = report.period.date_from.strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9_]+", "_", report.type.value.lower()).strip("_")
    columns = [column.key for column in report.columns]
    labels = [column.label for column in report.columns]
    rows = [{key: row.get(key) for key in columns} for row in report.rows]

    if export_format is ExportFormat.CSV:
        payload, media, extension = _csv(labels, columns, rows), "text/csv; charset=utf-8", "csv"
    elif export_format in {ExportFormat.EXCEL, ExportFormat.XLSX}:
        payload, media, extension = _xlsx(labels, columns, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    elif export_format in {ExportFormat.XML, ExportFormat.XAML}:
        payload, media = _xml(report, columns, rows), "application/xml; charset=utf-8"
        extension = "xaml" if export_format is ExportFormat.XAML else "xml"
    else:
        payload = json.dumps(report.model_dump(by_alias=True, mode="json"), ensure_ascii=False, indent=2).encode("utf-8")
        media, extension = "application/json; charset=utf-8", "json"

    filename = f"report_{slug}_{stamp}.{extension}"
    return StreamingResponse(
        iter((payload,)),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


def _csv(labels: list[str], columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(labels)
    for row in rows:
        writer.writerow([_safe_cell(row.get(column)) for column in columns])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    # Prevent spreadsheet formula injection from customer names, notes and references.
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


def _xml(report: ReportResponse, columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    root = Element("report", {"type": report.type.value})
    SubElement(root, "title").text = report.title
    SubElement(root, "from").text = report.period.date_from.isoformat()
    SubElement(root, "to").text = report.period.date_to.isoformat()
    body = SubElement(root, "rows")
    for values in rows:
        node = SubElement(body, "row")
        for column in columns:
            SubElement(node, column).text = "" if values.get(column) is None else str(values[column])
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="utf-8")


def _xlsx(labels: list[str], columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    """Build a standards-compliant single-sheet XLSX using only the standard library."""
    sheet_rows = [labels, *[[_safe_cell(row.get(column)) for column in columns] for row in rows]]
    xml_rows = []
    for row_number, values in enumerate(sheet_rows, start=1):
        cells = []
        for column_number, value in enumerate(values, start=1):
            reference = f"{_column_name(column_number)}{row_number}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                escaped = _xml_escape("" if value is None else str(value))
                cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>')
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
