# NOVA-GeoRisk user guides

One build for every system guide (FRRIS now; WRRIS and MEGIS reuse it). Markdown → HTML (`guide.css`) → PDF in headless Chromium (Playwright `page.pdf`, running header and "Page X of Y" from `headerTemplate`/`footerTemplate`).

| File | What it is |
|---|---|
| `FRRIS_USER_GUIDE.md` | The FRRIS guide text (front matter: title, subtitle, date, author, header) |
| `FRRIS_User_Guide.pdf` | The built PDF |
| `guide.css` | The shared stylesheet (A4, Source Serif 4 headings, Inter body, tables, figures, callouts) |
| `fonts/` | Inter and Source Serif 4 (SIL OFL 1.1, licences included), embedded in the PDF |
| `img/` | Screenshots (FRRIS: `NN-name.png`) |
| `build.mjs` | Markdown → HTML → PDF |
| `preview.mjs` | PDF pages → PNG (pdf.js), for a style check |
| `tools/capture-frris.mjs` | FRRIS screenshots from a **local** dev stack (never production) |
| `tools/report-page.mjs` | One page of a report PDF → PNG, found by its text |
| `tools/contact-sheet.mjs` | All rendered pages on one sheet |

## Build

```bash
npm install
node build.mjs FRRIS_USER_GUIDE.md FRRIS_User_Guide.pdf
node preview.mjs FRRIS_User_Guide.pdf ./.build/pv 1 2
```

Chromium needs `libnss3`, `libnspr4` and `libasound2`. Without root, extract them with `apt-get download` and `dpkg-deb -x`, then set `LD_LIBRARY_PATH`. The fonts need no install: `build.mjs` converts them to TTF in `.build/fonts` and gives Chromium its own fontconfig file. The header and footer templates cannot load web fonts.

## Markdown conventions

- `## N. Title` starts a chapter on a new page and goes into the contents list.
- `![Caption](img/file.png)` on its own line becomes "Figure N. Caption". Landscape screenshots fill the text width; tall crops are capped at 125 mm and centred.
- `::: tip`, `::: caveat` and `::: steps` (each closed with `:::`) give a tip box, a caveat box or numbered steps.

## A new guide (WRRIS, MEGIS)

Copy `FRRIS_USER_GUIDE.md` as `<SYSTEM>_USER_GUIDE.md` and keep its front matter and chapter pattern. Write a `tools/capture-<system>.mjs` on the FRRIS model, then run `node build.mjs <SYSTEM>_USER_GUIDE.md <System>_User_Guide.pdf`.

## FRRIS screenshots (how they were made, 2026-11-18)

- **Stack:** the local stack ran on 127.0.0.1: Postgres and Redis in throwaway containers, the API, BFF and Celery worker from this repository, and Vite from the frontend. The Earth Engine key was the local dev key.
- **Account:** one organisation ("Example Organisation"), one placeholder user (`analyst@example.org`, role analyst) and a session written straight into Redis. No real identity provider is involved; the sign-in page used placeholder OIDC settings (`login.example.org`).
- **Analyses:** the two Rufiji analyses (24–25 May 2024 and 29 Apr – 1 May 2024) were submitted through the UI and ran for real. They reproduce the production figures:
  - May: overall accuracy 94.2%, kappa 0.446, AUC 0.805, n = 106,088, reference coverage 98.8%;
  - peak: reference coverage 0.42%, so not assessable.
- **The failed run (Figure 18)** is a seeded example task, carrying the real message format of the valid-coverage gate.
- **Map viewer:** it uses the "Street" (OpenStreetMap) basemap, because the "Light" basemap needs a key the local stack does not have.
