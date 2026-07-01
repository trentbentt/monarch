// In-browser video encoder built on WebCodecs + a muxer. Produces a single
// high-bitrate file with no ffmpeg and no giant frame dumps. VP9/WebM is the
// primary target (best for the dark cyan gradients); H.264/MP4 is the fallback.
import { Muxer as WebMMuxer, ArrayBufferTarget as WebMTarget } from "webm-muxer";
import { Muxer as MP4Muxer, ArrayBufferTarget as MP4Target } from "mp4-muxer";

async function pickCodec(width, height, fps, bitrate) {
  const candidates = [
    {
      // H.264 first: universal hardware decode across every device/browser, so
      // the entrance plays smoothly even on a modest remote client over Tailscale.
      kind: "mp4",
      mime: "video/mp4",
      ext: "mp4",
      muxerCodec: "avc",
      codec: "avc1.640028", // H.264 High@4.0
    },
    {
      kind: "webm",
      mime: "video/webm",
      ext: "webm",
      muxerCodec: "V_VP9",
      codec: "vp09.00.40.08",
    },
  ];
  for (const c of candidates) {
    try {
      const { supported } = await VideoEncoder.isConfigSupported({
        codec: c.codec,
        width,
        height,
        bitrate,
        framerate: fps,
      });
      if (supported) return c;
    } catch {
      /* try next */
    }
  }
  throw new Error("No supported WebCodecs video codec (need a recent Chromium).");
}

export async function createEncoder({ width, height, fps, bitrate }) {
  if (typeof VideoEncoder === "undefined") {
    throw new Error("WebCodecs VideoEncoder unavailable — use Chrome/Edge.");
  }
  const choice = await pickCodec(width, height, fps, bitrate);

  let muxer;
  if (choice.kind === "webm") {
    muxer = new WebMMuxer({
      target: new WebMTarget(),
      video: { codec: choice.muxerCodec, width, height, frameRate: fps },
    });
  } else {
    muxer = new MP4Muxer({
      target: new MP4Target(),
      video: { codec: choice.muxerCodec, width, height },
      fastStart: "in-memory",
    });
  }

  const encoder = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (e) => console.error("[capture] encoder error:", e),
  });
  encoder.configure({
    codec: choice.codec,
    width,
    height,
    bitrate,
    framerate: fps,
    latencyMode: "quality",
  });

  const frameDur = 1e6 / fps; // microseconds

  return {
    info: choice,
    addFrame(canvas, i) {
      const frame = new VideoFrame(canvas, {
        timestamp: Math.round(i * frameDur),
        duration: Math.round(frameDur),
      });
      // Keyframe every 1s keeps seeking/scrubbing cheap.
      encoder.encode(frame, { keyFrame: i % fps === 0 });
      frame.close();
    },
    async finish() {
      await encoder.flush();
      muxer.finalize();
      const { buffer } = muxer.target;
      return { blob: new Blob([buffer], { type: choice.mime }), ext: choice.ext };
    },
  };
}
