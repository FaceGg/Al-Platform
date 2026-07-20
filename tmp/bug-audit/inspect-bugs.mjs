import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "E:/codex_workspace/agent_spot_welding/docs/bug清单.xlsx";
const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 100,
  tableMaxCols: 30,
  tableMaxCellChars: 500,
});

console.log(summary.ndjson);
