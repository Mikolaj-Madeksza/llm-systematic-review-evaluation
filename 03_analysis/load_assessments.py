"""Read original records and their returned workbook cells."""

import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import openpyxl


def load_assessments(data_dir):
    linked = data_dir / "inputs/linked_assessments.json"
    if linked.exists():
        return json.loads(linked.read_text())

    records = json.loads((data_dir / "inputs/original_records.json").read_text())
    with ZipFile(data_dir / "inputs/reviewer_workbooks.zip") as archive:
        books = {
            name: openpyxl.load_workbook(io.BytesIO(archive.read(name)), data_only=True)
            for name in archive.namelist()
        }
    columns = {
        (filename, sheet.title): {c.value: c.column for c in sheet[1] if c.value}
        for filename, book in books.items()
        for sheet in book
    }
    result = {}
    for kind, rows in records.items():
        result[kind] = []
        for record in rows:
            location = record["returned_cell"]
            filename = Path(location["file"]).name
            sheet = books[filename][location["sheet"]]
            reviewed = {
                key: sheet.cell(location["row"], column).value
                for key, column in columns[filename, sheet.title].items()
            }
            reviewed.update(
                _row=location["row"], _sheet=sheet.title, _file=location["file"]
            )
            assert reviewed["study_id"] == record["original"]["study_id"]
            result[kind].append({"original": record["original"], "reviewed": reviewed})
    with (data_dir / "inputs/timing.csv").open(encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            filename = Path(row["file"]).name
            sheet = books[filename][row["sheet"]]
            column = columns[filename, sheet.title][row["task"] + "_time_s"]
            assert float(sheet.cell(int(row["row"]), column).value) == float(
                row["time_s"]
            )
    for book in books.values():
        book.close()
    return result
