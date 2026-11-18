// Render PDF pages to PNG with pdf.js in headless Chromium (style check of a built guide).
//   node preview.mjs FRRIS_User_Guide.pdf <out-dir> [first] [last]
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = dirname(fileURLToPath(import.meta.url));
const [pdfFile, outDir, first = "1", last = "2"] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const pdf = readFileSync(resolve(pdfFile)).toString("base64");
const lib = readFileSync(join(here, "node_modules/pdfjs-dist/build/pdf.min.mjs"), "utf8");
const worker = readFileSync(join(here, "node_modules/pdfjs-dist/build/pdf.worker.min.mjs"), "utf8");

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent("<html><body style='margin:0;background:#fff'><canvas id='c'></canvas></body></html>");
await page.addScriptTag({ type: "module", content: `${lib}\nwindow.pdfjsLib = { getDocument, GlobalWorkerOptions };` });
await page.waitForFunction(() => window.pdfjsLib);
for (let n = Number(first); n <= Number(last); n += 1) {
  const png = await page.evaluate(async ({ data, workerSource, n }) => {
    const { getDocument, GlobalWorkerOptions } = window.pdfjsLib;
    GlobalWorkerOptions.workerSrc = URL.createObjectURL(new Blob([workerSource], { type: "text/javascript" }));
    const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
    const doc = await getDocument({ data: bytes }).promise;
    const pg = await doc.getPage(n);
    const viewport = pg.getViewport({ scale: 2 });
    const canvas = document.getElementById("c");
    canvas.width = viewport.width; canvas.height = viewport.height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    await pg.render({ canvasContext: ctx, viewport }).promise;
    return canvas.toDataURL("image/png").split(",")[1];
  }, { data: pdf, workerSource: worker, n });
  const path = join(outDir, `page-${n}.png`);
  writeFileSync(path, Buffer.from(png, "base64"));
  console.log(path);
}
await browser.close();
