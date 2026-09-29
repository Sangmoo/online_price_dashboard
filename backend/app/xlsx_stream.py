"""대용량 엑셀(xlsx) 스트리밍 작성기.

xlsxwriter 보다 8배 이상 빠르게 쓰기 위해 시트 XML 을 직접 만들어 zip 에 흘려 쓴다.
- 문자열은 inline string, 숫자는 #,##0 서식. 행 수 제한 없음(시트당 sheet_rows 행마다 새 시트).
- 메모리에는 버퍼 몇 천 행만 유지한다.
"""
from __future__ import annotations

import re
import zipfile
from typing import Iterable, Sequence
from xml.sax.saxutils import escape

EXCEL_MAX_ROWS = 1_048_576
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
NS_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _col(n: int) -> str:
    s, n = "", n + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xml_attr(s: str) -> str:
    return escape(_ILLEGAL.sub("", s), {'"': "&quot;"})


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet {NS}>
<fonts count="2"><font><sz val="10"/><name val="맑은 고딕"/><family val="2"/></font><font><b/><sz val="10"/><name val="맑은 고딕"/><family val="2"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8ECF7"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FFB4BCCC"/></left><right style="thin"><color rgb="FFB4BCCC"/></right><top style="thin"><color rgb="FFB4BCCC"/></top><bottom style="thin"><color rgb="FFB4BCCC"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf><xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


class XlsxStreamWriter:
    """사용법: with XlsxStreamWriter(path, headers, kinds, widths, sheet_name) as w: w.write_rows(rows)"""

    def __init__(self, path: str, headers: Sequence[str], kinds: Sequence[str], widths: Sequence[float],
                 sheet_name: str = "Sheet", sheet_rows: int = 1_000_000):
        assert 1 <= sheet_rows < EXCEL_MAX_ROWS
        self.path, self.headers, self.kinds, self.widths = path, list(headers), list(kinds), list(widths)
        self.sheet_name, self.sheet_rows = sheet_name, sheet_rows
        self.zip = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True)
        self.sheets: list[str] = []
        self._f = None
        self._row = 0          # 현재 시트에 쓴 데이터 행 수
        self.total = 0         # 전체 데이터 행 수
        self._buf: list[str] = []

    # ---- 시트 ----
    def _open_sheet(self) -> None:
        self._close_sheet()
        n = len(self.sheets) + 1
        name = self.sheet_name if n == 1 else f"{self.sheet_name}_{n}"
        self.sheets.append(name)
        self._f = self.zip.open(f"xl/worksheets/sheet{n}.xml", "w", force_zip64=True)
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(self.widths))
        head = "".join(f'<c r="{_col(i)}1" s="1" t="inlineStr"><is><t>{_xml_attr(h)}</t></is></c>'
                       for i, h in enumerate(self.headers))
        self._f.write((
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet {NS} {NS_R}>'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'
            f'<cols>{cols}</cols><sheetData><row r="1">{head}</row>'
        ).encode("utf-8"))
        self._row = 0

    def _flush(self) -> None:
        if self._buf:
            self._f.write("".join(self._buf).encode("utf-8"))
            self._buf = []

    def _close_sheet(self) -> None:
        if self._f is not None:
            self._flush()
            self._f.write(b"</sheetData></worksheet>")
            self._f.close()
            self._f = None

    # ---- 행 ----
    def write_rows(self, rows: Iterable[Sequence]) -> None:
        kinds = self.kinds
        for r in rows:
            if self._f is None or self._row >= self.sheet_rows:
                self._flush()
                self._open_sheet()
            self._row += 1
            cells = []
            for v, k in zip(r, kinds):
                if v is None or v == "":
                    cells.append("<c/>")
                elif k == "int" and not isinstance(v, str):
                    cells.append(f'<c s="2"><v>{v}</v></c>')
                else:
                    cells.append(f'<c t="inlineStr"><is><t>{_xml_attr(str(v))}</t></is></c>')
            self._buf.append(f'<row r="{self._row + 1}">{"".join(cells)}</row>')
            if len(self._buf) >= 5000:
                self._flush()
            self.total += 1

    # ---- 마무리 ----
    def close(self) -> None:
        if self._f is None and not self.sheets:
            self._open_sheet()  # 빈 결과여도 헤더 시트 1개
        self._close_sheet()
        z, n = self.zip, len(self.sheets)
        z.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, n + 1))
            + "</Types>"))
        z.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"))
        z.writestr("xl/workbook.xml", (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook {NS} {NS_R}><sheets>'
            + "".join(f'<sheet name="{_xml_attr(s)}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(self.sheets, 1))
            + "</sheets></workbook>"))
        z.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
            + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"))
        z.writestr("xl/styles.xml", STYLES)
        z.close()

    def abort(self) -> None:
        try:
            if self._f is not None:
                self._f.close()
            self.zip.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            self.abort()
