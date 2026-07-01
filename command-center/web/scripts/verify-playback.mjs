// Load the running app, let the entrance mount, then seek the intro <video> to
// several timestamps and screenshot the whole page to verify the composited
// playback (video + aurora + procedural ground + ending overlay).
import puppeteer from "puppeteer";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import fs from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTDIR = "/tmp/play-thumbs";
fs.mkdirSync(OUTDIR, { recursive: true });
const URL = process.env.APP_URL || "http://127.0.0.1:5173/";
const TIMES = [1, 4, 9, 14, 16, 18.6];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  headless: true,
  executablePath: await puppeteer.executablePath(),
  args: [
    "--no-sandbox", "--disable-setuid-sandbox",
    "--use-gl=angle", "--use-angle=gl-egl",
    "--autoplay-policy=no-user-gesture-required",
  ],
  defaultViewport: { width: 1366, height: 768, deviceScaleFactor: 1 },
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("  [page-error]", e.message));

console.log("[verify] opening", URL);
await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });

await page.waitForSelector("video.intro-video", { timeout: 15000 });
const meta = await page.evaluate(async () => {
  const v = document.querySelector("video.intro-video");
  if (v.readyState < 1) await new Promise((r) => (v.onloadedmetadata = r));
  return { duration: v.duration, w: v.videoWidth, h: v.videoHeight };
});
console.log("[verify] intro video:", meta.w + "x" + meta.h, meta.duration.toFixed(2) + "s");

// Let the loader fade out.
await sleep(2600);

for (const t of TIMES) {
  await page.evaluate(async (t) => {
    const v = document.querySelector("video.intro-video");
    v.pause();
    await new Promise((r) => { v.onseeked = r; v.currentTime = Math.min(t, v.duration - 0.05); });
  }, t);
  // let the rAF-driven overlays (and the ending stagger) settle
  await sleep(t >= 15 ? 1400 : 500);
  const file = join(OUTDIR, `play_t${String(t).replace(".", "_")}.png`);
  await page.screenshot({ path: file });
  console.log("[verify] t=" + t + "s ->", file);
}

await browser.close();
console.log("[verify] done");
