// NOVA-GeoRisk user-guide builder (FRRIS, WRRIS, MEGIS): Markdown -> HTML (guide.css) -> PDF (headless Chromium).
//
//   npm install && node build.mjs FRRIS_USER_GUIDE.md FRRIS_User_Guide.pdf
//
// Markdown conventions (see FRRIS_USER_GUIDE.md):
//   * front matter between "---" lines: title, subtitle, date (pill), author (pill), header (running-header text);
//   * "## N. Title" starts a chapter on a new page and goes into the table of contents;
//   * ![Caption](img/file.png) on its own line becomes a numbered figure ("Figure N. Caption");
//   * ::: tip | caveat | steps ... ::: wraps Markdown in a callout box or a numbered-steps list.
// The running header (title, 7 pt, grey, top-left) and "Page X of Y" (bottom-right) come from Playwright's
// headerTemplate/footerTemplate. The cover is printed without the header and merged in front (pdf-lib).
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { decompress } from "wawoff2";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { marked } from "marked";
import { chromium } from "playwright";
import { PDFDocument } from "pdf-lib";

const here = dirname(fileURLToPath(import.meta.url));
const [source = "FRRIS_USER_GUIDE.md", output = "FRRIS_User_Guide.pdf"] = process.argv.slice(2);
const text = readFileSync(resolve(here, source), "utf8");

// ---- front matter ----
const fm = /^---\n([\s\S]*?)\n---\n/.exec(text);
const meta = Object.fromEntries((fm ? fm[1] : "").split("\n").filter(Boolean).map((line) => {
  const i = line.indexOf(":");
  return [line.slice(0, i).trim(), line.slice(i + 1).trim()];
}));
let body = fm ? text.slice(fm[0].length) : text;

// ---- ::: containers ----
body = body.replace(/^:::[ \t]*(\w+)[ \t]*\n([\s\S]*?)\n:::[ \t]*$/gm, (_, kind, inner) => {
  const html = marked.parse(inner);
  if (kind === "steps") return `<div class="steps">${html}</div>\n`;
  const label = { tip: "Tip.", caveat: "Caveat.", note: "Note." }[kind] ?? "";
  return `<div class="callout ${kind}">${html.replace(/^<p>/, `<p><span class="label">${label}</span>`)}</div>\n`;
});

// ---- figures, chapters, table of contents ----
let figure = 0;
const toc = [];
const slug = (s) => s.toLowerCase().replace(/<[^>]+>/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const renderer = new marked.Renderer();
renderer.paragraph = function ({ tokens }) {
  if (tokens.length === 1 && tokens[0].type === "image") {
    const { href, text: caption } = tokens[0];
    figure += 1;
    const narrow = /\{narrow\}\s*$/.test(caption);
    const clean = caption.replace(/\s*\{narrow\}\s*$/, "");
    return `<figure${narrow ? ' class="narrow"' : ""}><img src="${href}" alt="${clean.replace(/"/g, "&quot;")}"><figcaption>Figure ${figure}. ${this.parser.parseInline(marked.Lexer.lexInline(clean))}</figcaption></figure>\n`;
  }
  return `<p>${this.parser.parseInline(tokens)}</p>\n`;
};
renderer.heading = function ({ tokens, depth }) {
  const inner = this.parser.parseInline(tokens);
  const id = slug(inner);
  if (depth === 2) {
    const m = /^(\d+)\.\s+(.*)$/.exec(inner);
    if (m) toc.push({ n: m[1], title: m[2], id });
    return `<h2 id="${id}" class="${m ? "chapter" : ""}">${inner}</h2>\n`;
  }
  return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
};
marked.use({ renderer, gfm: true });
const content = marked.parse(body);

const cover = `<section class="cover">
  <h1>${meta.title ?? ""}</h1>
  ${meta.subtitle ? `<p class="subtitle">${meta.subtitle}</p>` : ""}
  <div class="pills">${meta.date ? `<span class="pill">${meta.date}</span>` : ""}${meta.author ? `<span class="pill">${meta.author}</span>` : ""}</div>
  <nav class="toc"><h2>Contents</h2><ol>${toc.map((t) => `<li><span class="n">${t.n}</span><a href="#${t.id}">${t.title}</a></li>`).join("")}</ol></nav>
</section>`;
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${meta.title ?? ""}</title>
<link rel="stylesheet" href="guide.css"></head><body>${cover}<main>${content}</main></body></html>`;
mkdirSync(join(here, ".build"), { recursive: true });
const htmlPath = join(here, ".build", source.replace(/\.md$/, ".html"));
// The HTML sits in .build/; point relative assets (css, fonts, img) back to the guide folder.
writeFileSync(htmlPath, html.replace('href="guide.css"', 'href="../guide.css"').replace(/src="img\//g, 'src="../img/'));

// ---- PDF ----
// Header/footer templates cannot load web fonts, so the guide fonts are converted to TTF and given to Chromium
// through its own fontconfig file (no system install; the same on any build machine).
const fontDir = join(here, ".build", "fonts");
mkdirSync(fontDir, { recursive: true });
for (const file of readdirSync(join(here, "fonts")).filter((f) => f.endsWith(".woff2"))) {
  writeFileSync(join(fontDir, file.replace(/\.woff2$/, ".ttf")), Buffer.from(await decompress(readFileSync(join(here, "fonts", file)))));
}
const fontsConf = join(here, ".build", "fonts.conf");
writeFileSync(fontsConf, `<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>
  <dir>${fontDir}</dir><include ignore_missing="yes">/etc/fonts/fonts.conf</include><cachedir>${join(here, ".build", "fc-cache")}</cachedir></fontconfig>`);
const templateStyle = `<style>.t{font-family:"Inter","DejaVu Sans",sans-serif;font-size:7pt;color:#8a8a86;width:100%;padding:0 20mm;box-sizing:border-box;}</style>`;
const header = `${templateStyle}<div class="t" style="text-align:left;padding-top:9mm;">${meta.header ?? meta.title ?? ""}</div>`;
const footer = `${templateStyle}<div class="t" style="text-align:right;padding-bottom:8mm;">Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>`;
const margin = { top: "20mm", bottom: "20mm", left: "20mm", right: "20mm" };

const browser = await chromium.launch({ env: { ...process.env, FONTCONFIG_FILE: fontsConf } });
const page = await browser.newPage();
await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
const options = { format: "A4", printBackground: true, displayHeaderFooter: true, margin, footerTemplate: footer };
// Page numbers and the total refer to the whole document in both passes (pageRanges keeps them).
const first = await page.pdf({ ...options, headerTemplate: "<span></span>", pageRanges: "1" });
const rest = await page.pdf({ ...options, headerTemplate: header, pageRanges: "2-" });
await browser.close();

const merged = await PDFDocument.create();
for (const bytes of [first, rest]) {
  const doc = await PDFDocument.load(bytes);
  (await merged.copyPages(doc, doc.getPageIndices())).forEach((p) => merged.addPage(p));
}
merged.setTitle(meta.title ?? "");
merged.setAuthor(meta.author ?? "");
merged.setProducer("NOVA-GeoRisk user-guide builder (Chromium, pdf-lib)");
writeFileSync(resolve(here, output), await merged.save());
console.log(`${output}: ${merged.getPageCount()} pages, ${figure} figures`);
