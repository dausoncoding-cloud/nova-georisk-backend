// Screenshots for the FRRIS user guide, from a LOCAL dev stack (never production).
//
// The local stack (Postgres, Redis, API, BFF, Celery worker, Vite) runs on 127.0.0.1 with a seeded organisation and a
// placeholder user (analyst@example.org). The session cookie comes from the seed step (~/frris-guide-data/stack/session.json).
//
//   node tools/capture-frris.mjs before-run   # sign-in, suite, playground, new analysis, preflight; submits the two runs
//   node tools/capture-frris.mjs analysis     # only the new-analysis part (the area already exists)
//   node tools/capture-frris.mjs results      # task pages and result tabs, once both runs have finished
//   node tools/capture-frris.mjs trend-run     # Trend analysis option and preflight; submits a May 2024 run with trends
//   node tools/capture-frris.mjs trend-results # the Trends tab of that run ("trend" in results.json)
//
// Images go to ./img (1280 x 860 viewport, device scale 1.5).
import { chromium } from "playwright";
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(dirname(fileURLToPath(import.meta.url)));
const IMG = join(here, "img");
mkdirSync(IMG, { recursive: true });
const HOME = process.env.HOME;
const DATA = join(HOME, "frris-guide-data");
const BASE = "http://127.0.0.1:5173";
const session = JSON.parse(readFileSync(join(DATA, "stack", "session.json"), "utf8"));
const stage = process.argv[2] ?? "before-run";

// Date inputs follow the OS locale, not the page locale: British format (dd/mm/yyyy) as in Tanzania.
const browser = await chromium.launch({ env: { ...process.env, LANG: "en_GB.UTF-8", LC_ALL: "en_GB.UTF-8" } });
async function context(authenticated = true) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1.5, locale: "en-GB",
                                         timezoneId: "Africa/Dar_es_Salaam" });
  if (authenticated) await ctx.addCookies([{ name: "nova_session", value: session.cookie, domain: "127.0.0.1", path: "/", httpOnly: true }]);
  return ctx;
}
const settle = async (page, ms = 1200) => { await page.waitForLoadState("networkidle").catch(() => {}); await page.waitForTimeout(ms); };
async function shot(target, name, options = {}) {
  const path = join(IMG, `${name}.png`);
  await target.screenshot({ path, ...options });
  console.log("img/" + name + ".png");
}
const page = async (ctx, path) => { const p = await ctx.newPage(); await p.goto(BASE + path); await settle(p); return p; };

async function fillPeriods(p, target, baseline) {
  const dates = p.locator('main input[type="date"]');
  await dates.nth(0).fill(target[0]); await dates.nth(1).fill(target[1]);
  await dates.nth(2).fill(baseline[0]); await dates.nth(3).fill(baseline[1]);
  await dates.nth(3).blur();
}
async function chooseArea(p, name) {
  await p.locator("main label").filter({ hasText: name }).first().click();
}
// Screenshot of the card (section) that holds a heading.
async function card(p, heading, name) {
  const h = p.getByRole("heading", { name: heading, exact: false }).first();
  await h.scrollIntoViewIfNeeded();
  const box = await h.evaluateHandle((el) => el.closest("section, article, fieldset, aside, .fr-card, [class*='card']") ?? el.parentElement);
  await settle(p, 500);
  await shot(box.asElement(), name);
}
const section = (p, heading) => p.locator("main section, main .fr-card, main form > div").filter({ has: p.getByText(heading, { exact: false }) }).first();
async function waitPreflight(p) {
  await p.waitForFunction(() => /Ready to run|cannot run|Warnings|Blocked|can run/i.test(document.querySelector("main")?.innerText ?? ""),
                          null, { timeout: 120000 }).catch(() => {});
  await settle(p, 1500);
}

if (stage === "before-run") {
  // 1. Sign in (no session) and the suite.
  const anon = await context(false);
  const login = await page(anon, "/login");
  await shot(login, "01-sign-in");
  await anon.close();

  const ctx = await context();
  const home = await page(ctx, "/");
  await shot(home, "02-suite-home");
  const analyses = await page(ctx, "/frris/analyses");
  await analyses.locator("aside button, nav button").filter({ hasText: "FRRIS" }).first().click();
  await settle(analyses, 600);
  await shot(analyses, "03-system-switcher");
  await analyses.close();

  // 2. Area playground.
  const pg = await page(ctx, "/frris/playground");
  await pg.setInputFiles('input[type="file"]', join(DATA, "large-area.geojson"));
  await settle(pg, 3500);
  await shot(pg, "04-playground-too-large", { fullPage: true });
  await pg.getByText("Trim to the largest box that fits").click();
  await pg.getByRole("button", { name: "Apply" }).click();
  await settle(pg, 3000);
  await shot(pg, "05-playground-trimmed", { fullPage: true });
  await pg.getByRole("button", { name: "Clear" }).click();
  await settle(pg, 800);
  await pg.setInputFiles('input[type="file"]', join(DATA, "rufiji-area.geojson"));
  await settle(pg, 3500);
  const name = pg.locator("main input[type='text'], main input:not([type])").first();
  await name.fill("Rufiji floodplain 2024");
  await shot(pg, "06-playground-fits", { fullPage: true });
  await pg.getByRole("button", { name: "Save to my areas" }).click();
  await settle(pg, 2500);
  await shot(pg, "07-playground-saved", { fullPage: true });
  await pg.close();
  await ctx.close();
}

if (stage === "before-run" || stage === "analysis") {
  const ctx = await context();
  // 3. New analysis: area, periods and preflight states, products; then the two Rufiji runs.
  const na = await page(ctx, "/frris/analyses/new");
  await chooseArea(na, "Rufiji floodplain 2024");
  await settle(na, 1500);
  await card(na, "Area of interest", "08-new-analysis-area");
  await fillPeriods(na, ["2024-05-24", "2024-05-25"], ["2022-08-28", "2022-09-02"]);
  await waitPreflight(na);
  await card(na, "Periods and satellite availability", "09-preflight-ready");
  await fillPeriods(na, ["2024-04-08", "2024-04-10"], ["2023-10-22", "2023-10-22"]);   // no radar pass: blocked
  await waitPreflight(na);
  await card(na, "Periods and satellite availability", "10-preflight-blocked");
  await fillPeriods(na, ["2024-04-07", "2024-04-07"], ["2023-10-22", "2023-10-22"]);   // pass, but no clear Sentinel-2
  await waitPreflight(na);
  await card(na, "Periods and satellite availability", "11-preflight-warning");
  await card(na, "Data quality", "12-data-quality");
  await fillPeriods(na, ["2024-05-24", "2024-05-25"], ["2022-08-28", "2022-09-02"]);
  await waitPreflight(na);
  await na.getByText("Model confidence score", { exact: false }).first().click();
  await na.getByText("Estimated exposure (WorldPop, Open Buildings)").click();
  await settle(na, 800);
  await card(na, "Products", "13-products");
  await card(na, "Run summary", "14-run-summary");
  await na.getByRole("button", { name: "Run analysis" }).click();
  await na.waitForURL((url) => !url.pathname.endsWith("/new"), { timeout: 60000 }).catch(() => {});
  await settle(na, 3000);
  writeFileSync(join(DATA, "may-task-url.txt"), na.url());
  await shot(na, "15-run-progress");
  await na.close();

  const peak = await page(ctx, "/frris/analyses/new");
  await chooseArea(peak, "Rufiji floodplain 2024");
  await settle(peak, 1500);
  await fillPeriods(peak, ["2024-04-29", "2024-05-01"], ["2023-10-22", "2023-10-22"]);
  await waitPreflight(peak);
  await card(peak, "Periods and satellite availability", "16-preflight-peak");
  await peak.getByText("Model confidence score", { exact: false }).first().click();
  await peak.getByText("Estimated exposure (WorldPop, Open Buildings)").click();
  await peak.getByRole("button", { name: "Run analysis" }).click();
  await peak.waitForURL((url) => !url.pathname.endsWith("/new"), { timeout: 60000 }).catch(() => {});
  await settle(peak, 3000);
  writeFileSync(join(DATA, "peak-task-url.txt"), peak.url());
  await peak.close();
  await ctx.close();
}

if (stage === "results" || stage === "fix") {
  // Result ids from the local stack: ~/frris-guide-data/results.json {"may": id, "peak": id, "failed_task": id}.
  const ids = JSON.parse(readFileSync(join(DATA, "results.json"), "utf8"));
  const ctx = await context();
  const list = await page(ctx, "/frris/analyses");
  await shot(list, "17-analyses-list");
  await list.close();
  const failed = await page(ctx, `/tasks/${ids.failed_task}`);
  await shot(failed, "18-run-failed");
  await failed.close();

  const tab = async (id, key, ms = 2500) => {
    const p = await page(ctx, `/results/${id}?tab=${key}`);
    // Wait for the area name: until it loads, the page title falls back to "Flood mapping".
    await p.getByRole("heading", { level: 1, name: "Rufiji floodplain 2024" }).waitFor({ timeout: 30000 });
    await settle(p, ms);
    return p;
  };
  const region = async (p, label, name) => {
    const r = p.getByRole("region", { name: label }).first();
    await r.scrollIntoViewIfNeeded(); await settle(p, 1500);
    await p.evaluate(() => window.scrollBy(0, -90)); await settle(p, 300);
    await shot(p, name);
  };
  let p = await tab(ids.may, "overview", 4000); await shot(p, "19-overview-may"); await p.close();
  p = await tab(ids.may, "accuracy"); await shot(p, "20-accuracy-may");
  await region(p, "Accuracy figures", "21-accuracy-may-figures"); await p.close();
  p = await tab(ids.peak, "accuracy"); await shot(p, "22-accuracy-peak"); await p.close();
  p = await tab(ids.peak, "overview", 4000); await shot(p, "23-overview-peak"); await p.close();
  p = await tab(ids.peak, "hazard"); await shot(p, "24-hazard-peak");
  await p.locator("main figure").first().scrollIntoViewIfNeeded(); await settle(p, 1500);
  await p.evaluate(() => window.scrollBy(0, -60)); await shot(p, "25-hazard-figures"); await p.close();
  p = await tab(ids.peak, "exposure");
  await p.getByLabel("Observed extent caveat").scrollIntoViewIfNeeded(); await settle(p, 800);
  await p.evaluate(() => window.scrollBy(0, 330)); await settle(p, 500);
  await shot(p, "26-exposure-peak");
  await p.close();
  // Map viewer: Street basemap (OpenStreetMap; the Light basemap needs a key the local stack does not have);
  // the flood-candidate extent next to the modelled 1-in-100-year depth.
  p = await tab(ids.peak, "maps", 3000);
  await p.locator("main label").filter({ hasText: "Estimated people inside the observed" }).locator("input").uncheck();
  await p.locator("main label").filter({ hasText: "Flood-candidate extent (model-classified)" }).first().locator("input").check();
  await p.locator("main label").filter({ hasText: "Modelled flood depth, 1-in-100-year" }).locator("input").check();
  await settle(p, 2000);
  for (const select of await p.locator("main select").all()) await select.selectOption({ label: "Street" });
  await settle(p, 6000);
  await p.evaluate(() => { const map = document.querySelector(".leaflet-container"); window.scrollTo(0, map.getBoundingClientRect().top + window.scrollY - 230); });
  await settle(p, 1500);
  await shot(p, "28-map-viewer"); await p.close();
  p = await tab(ids.peak, "downloads"); await shot(p, "29-downloads"); await p.close();
  p = await tab(ids.peak, "provenance"); await shot(p, "30-provenance"); await p.close();
  await ctx.close();
}

if (stage === "trend-run") {
  // Trend Analysis (guide v1.2): the option, the preflight pass count, and a May 2024 run with trends.
  const ctx = await context();
  const p = await page(ctx, "/frris/analyses/new");
  await chooseArea(p, "Rufiji floodplain 2024");
  await settle(p, 1500);
  await fillPeriods(p, ["2024-05-24", "2024-05-25"], ["2022-08-28", "2022-09-02"]);
  await waitPreflight(p);
  await p.getByText("Model confidence score", { exact: false }).first().click();
  await p.getByRole("switch", { name: /^Trend analysis/ }).check();
  await p.waitForFunction(() => /Sentinel-1 pass(es)? on orbit/.test(document.querySelector("main")?.innerText ?? ""), null, { timeout: 120000 });
  await settle(p, 1500);
  await card(p, "Periods and satellite availability", "34-trend-preflight");
  await card(p, "Products", "35-trend-option");
  await p.getByRole("button", { name: "Run analysis" }).click();
  await p.waitForURL((url) => !url.pathname.endsWith("/new"), { timeout: 60000 }).catch(() => {});
  writeFileSync(join(DATA, "trend-task-url.txt"), p.url());
  await ctx.close();
}

if (stage === "trend-results") {
  const ids = JSON.parse(readFileSync(join(DATA, "results.json"), "utf8"));
  const ctx = await context();
  const p = await page(ctx, `/results/${ids.trend}?tab=trends`);
  await p.getByRole("heading", { level: 1, name: "Rufiji floodplain 2024" }).waitFor({ timeout: 30000 });
  // Card captures only: the sticky result tabs would overlap a card scrolled to the top of the viewport.
  await p.addStyleTag({ content: ".fr-result .workspace-tabs.result-tabs { position: static !important; }" });
  await settle(p, 2500);
  await shot(p, "36-trends-tab");
  for (const [name, file] of [["Surface-water extent, annual (JRC, 1984–2021)", "37-trends-surface-water"],
                              ["Daily rainfall, 90 days to 25 May 2024", "38-trends-rainfall"],
                              ["SAR open water (VV < -18 dB) per Sentinel-1 pass", "39-trends-sar"]]) {
    const region = p.getByRole("region", { name }).first();
    await region.scrollIntoViewIfNeeded();
    await settle(p, 600);
    await shot(region, file);
  }
  await ctx.close();
}

await browser.close();
