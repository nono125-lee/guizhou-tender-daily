import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const sourcePath = process.argv[2];
if (!sourcePath) {
  throw new Error("Usage: add_zunyibus_source.mjs <source-workbook>");
}

const input = await FileBlob.load(sourcePath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("平台账号");
sheet.getRange("A173:I173").values = [[
  108,
  "遵义市公共交通（集团）有限责任公司",
  "http://www.zunyibus.com/",
  null,
  null,
  null,
  null,
  "公开网站，无需登录",
  "通知公告栏目：/tzgg/",
]];

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(sourcePath);

const inspection = await workbook.inspect({
  kind: "table",
  range: "平台账号!A170:I173",
  include: "values,formulas",
  tableMaxRows: 10,
  tableMaxCols: 9,
});
console.log(inspection.ndjson);

const preview = await workbook.render({
  sheetName: "平台账号",
  range: "A168:I173",
  scale: 1.5,
});
await fs.writeFile("/tmp/zunyibus-source-preview.png", await preview.bytes());
