"""以串流方式合併多個裁判書 Excel，保留各工作表並容納不同年度的欄位差異。"""

import argparse
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill


# 依輸入檔出現順序建立工作表與欄位聯集，避免新版新增欄位時遺失資料。
def discover_layout(paths: list[Path]) -> tuple[list[str], dict[str, list[str]]]:
    sheet_names: list[str] = []
    headers: dict[str, list[str]] = {}
    for path in paths:
        workbook = load_workbook(path, read_only=True, data_only=True)
        for sheet_name in workbook.sheetnames:
            if sheet_name not in sheet_names:
                sheet_names.append(sheet_name)
                headers[sheet_name] = []
            source_headers = [cell.value for cell in next(workbook[sheet_name].iter_rows(max_row=1))]
            for header in source_headers:
                if header not in headers[sheet_name]:
                    headers[sheet_name].append(header)
        workbook.close()
    return sheet_names, headers


# 將同名工作表逐列寫入輸出檔；write-only 模式避免大型判決全文耗盡記憶體。
def merge_workbooks(paths: list[Path], output: Path) -> dict[str, int]:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"找不到輸入檔：{', '.join(missing)}")

    sheet_names, headers = discover_layout(paths)
    target = Workbook(write_only=True)
    sheets = {}
    counts = {name: 0 for name in sheet_names}
    seen_links = {name: set() for name in sheet_names}
    for name in sheet_names:
        sheet = target.create_sheet(name)
        header_cells = []
        for value in headers[name]:
            cell = WriteOnlyCell(sheet, value=value)
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="1F3864")
            header_cells.append(cell)
        sheet.append(header_cells)
        sheets[name] = sheet

    for path in paths:
        workbook = load_workbook(path, read_only=True, data_only=True)
        for name in workbook.sheetnames:
            source = workbook[name]
            source_headers = [cell.value for cell in next(source.iter_rows(max_row=1))]
            positions = {header: index for index, header in enumerate(source_headers)}
            link_index = positions.get("裁判書連結")
            for row in source.iter_rows(min_row=2, values_only=True):
                link = row[link_index] if link_index is not None and link_index < len(row) else ""
                if link and link in seen_links[name]:
                    continue
                if link:
                    seen_links[name].add(link)
                sheets[name].append([
                    row[positions[header]] if header in positions and positions[header] < len(row) else ""
                    for header in headers[name]
                ])
                counts[name] += 1
        workbook.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    target.save(output)
    return counts


# 提供可重複使用的命令列入口，至少需要兩個輸入檔與一個輸出檔。
def main() -> None:
    parser = argparse.ArgumentParser(description="合併多個裁判書 Excel 的所有工作表")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args()
    counts = merge_workbooks(args.inputs, args.output)
    print(f"完成：{args.output}")
    for sheet_name, count in counts.items():
        print(f"  {sheet_name}: {count} 筆")


if __name__ == "__main__":
    main()
