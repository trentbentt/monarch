// Load the captured video in headless Chromium, seek to several timestamps,
// and save PNG thumbnails + average brightness so we can verify the brain
// actually rendered (not black) and the camera path looks right.
import puppeteer from "puppeteer";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import fs from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const VIDEO = join(__dirname, "..", "public", "brain-intro.mp4");
const OUTDIR = "/tmp/cap-thumbs";
fs.mkdirSync(OUTDIR, { recursive: true });

const TIMES = [0.5, 2.5, 4.0, 6.0, 9.0, 12.0, 15.0, 17.5];

const dataUrl = "data:text/html," + encodeURIComponent(`
<body style="margin:0;background:#000">
<video id="v" muted playsinline></video>
<canvas id="c" width="960" height="540"></canvas>
</body>`);

const browser = await puppeteer.launch({
  headless: true,
  executablePath: await puppeteer.executablePath(),
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--use-gl=angle", "--use-angle=gl-egl", "--autoplay-policy=no-user-gesture-required"],
  defaultViewport: { width: 1000, height: 600 },
});
const page = await browser.newPage();
page.on("console", (m) => console.log("  [page]", m.text()));

const bytes = fs.readFileSync(VIDEO);
const b64 = bytes.toString("base64");

await page.goto(dataUrl);
await page.evaluate((b64) => {
  const v = document.getElementById("v");
  v.src = "data:video/webm;base64," + b64;
  return new Promise((res) => { v.onloadedmetadata = () => res(); });
}, b64);

const meta = await page.evaluate(() => {
  const v = document.getElementById("v");
  return { duration: v.duration, w: v.videoWidth, h: v.videoHeight };
});
console.log("[verify] duration:", meta.duration.toFixed(2), "s   dims:", meta.w + "x" + meta.h);

for (const t of TIMES) {
  const res = await page.evaluate(async (t) => {
    const v = document.getElementById("v");
    const c = document.getElementById("c");
    const ctx = c.getContext("2d");
    await new Promise((r) => { v.onseeked = () => r(); v.currentTime = Math.min(t, v.duration - 0.05); });
    ctx.drawImage(v, 0, 0, c.width, c.height);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) sum += (d[i] + d[i + 1] + d[i + 2]) / 3;
    const avg = sum / (d.length / 4);
    return { png: c.toDataURL("image/png"), avg };
  }, t);
  const file = join(OUTDIR, `t${String(t).replace(".", "_")}.png`);
  fs.writeFileSync(file, Buffer.from(res.png.split(",")[1], "base64"));
  console.log(`[verify] t=${t}s  avgBrightness=${res.avg.toFixed(1)}  -> ${file}`);
}

await browser.close();
console.log("[verify] thumbnails in", OUTDIR);
