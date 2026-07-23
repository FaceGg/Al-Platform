import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];

if (!workbookPath) {
  throw new Error("Usage: node inspect_bug_workbook.mjs <workbook-path>");
}

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 8000,
  tableMaxRows: 30,
  tableMaxCols: 12,
  tableMaxCellChars: 240,
});

console.log(overview.ndjson);

const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 2000 });
console.log(sheets.ndjson);
