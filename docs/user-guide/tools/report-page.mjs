// Render one page of a PDF to PNG: the first page whose text contains <needle> (or page 1 when needle is "1").
//   node tools/report-page.mjs report.pdf "<needle>" out.png [scale]
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const [pdfFile, needle, out, scale = "1.6"] = process.argv.slice(2);
const pdf = readFileSync(resolve(pdfFile)).toString("base64");
const lib = readFileSync(join(here, "node_modules/pdfjs-dist/build/pdf.min.mjs"), "utf8");
const worker = readFileSync(join(here, "node_modules/pdfjs-dist/build/pdf.worker.min.mjs"), "utf8");
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent("<canvas id='c'></canvas>");
await page.addScriptTag({ type: "module", content: `${lib}\nwindow.pdfjsLib = { getDocument, GlobalWorkerOptions };` });
await page.waitForFunction(() => window.pdfjsLib);
const result = await page.evaluate(async ({ data, workerSource, needle, scale }) => {
  const { getDocument, GlobalWorkerOptions } = window.pdfjsLib;
  GlobalWorkerOptions.workerSrc = URL.createObjectURL(new Blob([workerSource], { type: "text/javascript" }));
  const doc = await getDocument({ data: Uint8Array.from(atob(data), (c) => c.charCodeAt(0)) }).promise;
  let number = 1;
  if (needle !== "1") {
    number = 0;
    for (let n = 1; n <= doc.numPages && !number; n += 1) {
      const text = (await (await doc.getPage(n)).getTextContent()).items.map((i) => i.str).join(" ");
      if (text.includes(needle)) number = n;
    }
    if (!number) return { error: `"${needle}" not found in ${doc.numPages} pages` };
  }
  const pg = await doc.getPage(number);
  const viewport = pg.getViewport({ scale: Number(scale) });
  const canvas = document.getElementById("c");
  canvas.width = viewport.width; canvas.height = viewport.height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  await pg.render({ canvasContext: ctx, viewport }).promise;
  return { number, png: canvas.toDataURL("image/png").split(",")[1] };
}, { data: pdf, workerSource: worker, needle, scale });
await browser.close();
if (result.error) { console.error(result.error); process.exit(1); }
writeFileSync(out, Buffer.from(result.png, "base64"));
console.log(`${out} (page ${result.number})`);
