// Measure on-screen text boxes of a built HyperFrames page at given times (for tools/review.py).
// Usage: node tools/js/measure_text.mjs <project dir> <chrome path> <W> <H> <json [{id, t}]>
// Prints JSON [{id, t, box:[x0,y0,x1,y1] | null, overflow:bool}]. Loads index.html straight from
// disk, switches transforms off (settled layout) and unions the text's glyph boxes.
import puppeteer from "puppeteer-core";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [, , dir, chrome, W, H, jobsJson] = process.argv;
const jobs = JSON.parse(jobsJson);
const browser = await puppeteer.launch({ executablePath: chrome, headless: true,
  args: ["--allow-file-access-from-files", "--autoplay-policy=no-user-gesture-required"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: Number(W), height: Number(H), deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(path.join(dir, "index.html")).href, { waitUntil: "load", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  // animations only move/scale/fade text, so measure the settled layout: transforms off
  await page.addStyleTag({ content: ".txt, .txt *, #endcard, #endcard * { transform: none !important; translate: none !important; scale: none !important; }" });
  const out = [];
  for (const j of jobs) {
    const r = await page.evaluate((id, t) => {
      const tl = window.__timelines && window.__timelines.main;
      try { if (tl) tl.seek(t, false); } catch (e) { /* shader runtime may be absent outside HyperFrames */ }
      const el = document.getElementById(id);
      if (!el) return { box: null, overflow: false };
      const parts = el.querySelectorAll(".w, .ec-l:not(.ec-rule)");
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const p of parts) {
        const rg = document.createRange();
        rg.selectNodeContents(p);
        for (const b of rg.getClientRects()) {
          if (b.width < 1 || b.height < 1) continue;
          x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top); x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom);
        }
      }
      const overflow = el.scrollWidth > el.clientWidth + 2;
      return { box: x1 > x0 ? [x0, y0, x1, y1].map(v => Math.round(v)) : null, overflow };
    }, j.id, j.t);
    out.push({ id: j.id, t: j.t, ...r });
  }
  console.log(JSON.stringify(out));
} finally {
  await browser.close();
}
