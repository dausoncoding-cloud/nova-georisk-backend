import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
// Contact sheet of rendered pages (.build/pv/page-N.png from preview.mjs), for a quick layout check.
//   node tools/contact-sheet.mjs 1 18 .build/sheet.png
const [from, to, out] = process.argv.slice(2).map((v, i) => i < 2 ? Number(v) : v);
const imgs = []; for (let n = from; n <= to; n++) imgs.push(`<figure><img src="file://${process.cwd()}/.build/pv/page-${n}.png"><figcaption>${n}</figcaption></figure>`);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 2000, height: 1000 } });
writeFileSync(".build/sheet.html", `<style>body{margin:0;display:grid;grid-template-columns:repeat(6,1fr);gap:8px;background:#999;padding:8px}figure{margin:0;background:#fff}img{width:100%;display:block}figcaption{font:14px sans-serif;text-align:center}</style>${imgs.join("")}`);
await p.goto(`file://${process.cwd()}/.build/sheet.html`);
await p.waitForTimeout(800); await p.screenshot({ path: out, fullPage: true }); await b.close();
