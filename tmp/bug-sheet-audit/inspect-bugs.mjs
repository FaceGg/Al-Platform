import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("E:/codex_workspace/agent_spot_welding/docs/bug清单.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
const summary = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 16000,
  tableMaxRows: 80,
  tableMaxCols: 16,
  tableMaxCellChars: 240,
});

console.log(summary.ndjson);
