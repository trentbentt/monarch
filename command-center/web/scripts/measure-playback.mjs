// Measure REAL-TIME playback rate + decode/buffer health.
import puppeteer from "puppeteer";
const APP = process.env.APP_URL || "http://127.0.0.1:5173/";
const VIDEO_URL = "http://127.0.0.1:5173/brain-intro.mp4";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function measure(page, label) {
  const r = await page.evaluate(async () => {
    const v = document.querySelector("video");
    if (!v) return { error: "no video element" };
    v.muted = true;
    try { await v.play(); } catch (e) { /* ignore */ }
    const t0 = performance.now();
    const c0 = v.currentTime;
    await new Promise((res) => setTimeout(res, 6000));
    const wall = (performance.now() - t0) / 1000;
    const played = v.currentTime - c0;
    const q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
    const bufEnd = v.buffered.length ? v.buffered.end(v.buffered.length - 1) : 0;
    return {
      rate: played / wall, played, wall,
      vw: v.videoWidth, vh: v.videoHeight, dur: v.duration,
      readyState: v.readyState, networkState: v.networkState,
      bufferedEnd: bufEnd, paused: v.paused,
      dropped: q.droppedVideoFrames, total: q.totalVideoFrames,
    };
  });
  console.log(`\n[${label}]`, JSON.stringify(r, null, 0));
  if (!r.error) console.log(`   -> rate ${r.rate.toFixed(2)}x  (played ${r.played.toFixed(1)}s in ${r.wall}s)  dropped ${r.dropped}/${r.total}  buffered→${(r.bufferedEnd||0).toFixed(1)}s`);
  return r;
}

const browser = await puppeteer.launch({
  headless: true,
  executablePath: await puppeteer.executablePath(),
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--use-gl=angle", "--use-angle=gl-egl", "--autoplay-policy=no-user-gesture-required"],
  defaultViewport: { width: 1366, height: 768 },
});

// Bare decode: open the video URL directly (chromium's built-in media page).
const bare = await browser.newPage();
await bare.goto(VIDEO_URL, { waitUntil: "domcontentloaded", timeout: 30000 }).catch((e) => console.log("bare goto:", e.message));
await sleep(1500);
await measure(bare, "bare video (direct URL)");

// Full app entrance.
const app = await browser.newPage();
app.on("pageerror", (e) => console.log("  [page-error]", e.message));
await app.goto(APP, { waitUntil: "domcontentloaded", timeout: 60000 });
await app.waitForSelector("video.intro-video", { timeout: 15000 });
await sleep(2600);
await measure(app, "full app entrance");

await browser.close();
