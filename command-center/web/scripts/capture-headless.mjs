// Headless capture driver. Runs the deterministic brain-intro capture in a
// real Chromium (Puppeteer's bundled build) using the box's RTX 3090 via EGL,
// encodes in-browser with WebCodecs, and writes the file into public/.
//
//   node scripts/capture-headless.mjs            # uses GPU (EGL)
//   CAPTURE_GL=swiftshader node scripts/...       # force software fallback
//
import puppeteer from "puppeteer";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import fs from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = join(__dirname, "..", "public");
const URL = process.env.CAPTURE_URL || "http://127.0.0.1:5173/capture.html";
const OUT = "brain-intro";

const glMode = process.env.CAPTURE_GL === "swiftshader"
  ? ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
  : ["--use-gl=angle", "--use-angle=gl-egl"];

const args = [
  "--no-sandbox",
  "--disable-setuid-sandbox",
  "--disable-dev-shm-usage",
  "--ignore-gpu-blocklist",
  "--enable-gpu",
  ...glMode,
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  console.log("[driver] launching chromium with:", glMode.join(" "));
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: await puppeteer.executablePath(),
    args,
    defaultViewport: { width: 1920, height: 1400, deviceScaleFactor: 1 },
    protocolTimeout: 600000,
  });

  const page = await browser.newPage();
  page.on("console", (m) => console.log("  [page]", m.text()));
  page.on("pageerror", (e) => console.log("  [page-error]", e.message));

  // Route downloads into public/.
  const client = await page.createCDPSession();
  await client.send("Browser.setDownloadBehavior", {
    behavior: "allow",
    downloadPath: PUBLIC_DIR,
    eventsEnabled: true,
  });

  console.log("[driver] opening", URL);
  await page.goto(URL, { waitUntil: "networkidle0", timeout: 60000 });

  // Report the actual GL renderer + WebCodecs support.
  const caps = await page.evaluate(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    let renderer = "no-webgl";
    if (gl) {
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "webgl(masked)";
    }
    return { renderer, webcodecs: typeof VideoEncoder !== "undefined" };
  });
  console.log("[driver] GL renderer:", caps.renderer);
  console.log("[driver] WebCodecs VideoEncoder:", caps.webcodecs);
  if (!caps.webcodecs) throw new Error("WebCodecs unavailable in this Chromium.");

  // Wait for the brain/head GLBs to finish loading.
  await page.waitForFunction("window.__sceneReady === true", { timeout: 30000 }).catch(() => {
    console.log("[driver] __sceneReady timeout — proceeding after buffer");
  });
  await sleep(1500);

  const before = new Set(fs.readdirSync(PUBLIC_DIR));
  console.log("[driver] clicking Record…");
  await page.click("#rec");

  // Wait for the in-page capture to finish encoding.
  await page.waitForFunction(
    "window.__capDone === true || window.__capError",
    { timeout: 600000, polling: 500 },
  );
  const err = await page.evaluate(() => window.__capError || null);
  if (err) throw new Error("in-page capture error: " + err);
  const ext = await page.evaluate(() => window.__capExt || "webm");

  // Wait for the download to land + stabilise.
  const target = join(PUBLIC_DIR, `${OUT}.${ext}`);
  let lastSize = -1;
  for (let i = 0; i < 120; i++) {
    await sleep(500);
    if (fs.existsSync(target)) {
      const sz = fs.statSync(target).size;
      if (sz > 0 && sz === lastSize) break;
      lastSize = sz;
    } else {
      // chromium may use a .crdownload temp; just keep polling
      const now = fs.readdirSync(PUBLIC_DIR).filter((f) => !before.has(f));
      if (now.length) console.log("[driver] downloading:", now.join(", "));
    }
  }

  await browser.close();

  if (!fs.existsSync(target)) throw new Error("download did not appear: " + target);
  const mb = (fs.statSync(target).size / 1e6).toFixed(1);
  console.log(`[driver] DONE → ${target} (${mb} MB)`);
}

main().catch((e) => {
  console.error("[driver] FAILED:", e.message);
  process.exit(1);
});
