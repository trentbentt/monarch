// Guided real-mic capture for the hey_loki eval set. Token comes from the URL.
const TOKEN = new URLSearchParams(location.search).get("token") || "";
// Built-in eval script; replaced at init by the server's active profile (/script).
let SCRIPT = [
  { label: "positive",                  prompt: 'Say:  "hey loki"',        target: 40 },
  { label: "hard_negative/hey_low_key", prompt: 'Say:  "hey low key"',     target: 20 },
  { label: "speech_negative",           prompt: "Say a normal sentence (NOT the wake word)", target: 10 },
  { label: "fa_audio",                  prompt: "Stay quiet — capture ~10s of your room", target: 6 },
];

async function loadScript() {
  try {
    const r = await fetch(`/script?token=${encodeURIComponent(TOKEN)}`);
    if (r.ok) {
      const body = await r.json();
      if (Array.isArray(body.steps) && body.steps.length) SCRIPT = body.steps;
    }
  } catch (e) { /* keep the built-in eval script */ }
}

const $ = (id) => document.getElementById(id);
let stream, recorder, chunks = [], blob = null, counts = {};

function err(m) { $("err").textContent = m || ""; }

async function refreshCounts() {
  const r = await fetch(`/status?token=${encodeURIComponent(TOKEN)}`);
  if (!r.ok) { err("status failed (bad token?)"); return; }
  counts = await r.json();
  $("counts").innerHTML = SCRIPT.map(
    (s) => `<tr><td>${s.label}</td><td>${counts[s.label] || 0} / ${s.target}</td></tr>`
  ).join("");
}

function currentStep() {
  return SCRIPT.find((s) => (counts[s.label] || 0) < s.target) || null;
}

function render() {
  const step = currentStep();
  if (!step) {
    $("prompt").textContent = "All done — thank you!";
    $("sub").textContent = "You can close this tab.";
    $("rec").hidden = $("keep").hidden = $("redo").hidden = true;
    return;
  }
  $("prompt").textContent = step.prompt;
  $("sub").textContent = `${step.label}  —  ${counts[step.label] || 0}/${step.target}`;
  $("rec").hidden = false; $("keep").hidden = true; $("redo").hidden = true;
  $("play").hidden = true;
}

async function ensureMic() {
  if (stream) return;
  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
}

$("rec").onclick = async () => {
  try {
    await ensureMic();
  } catch (e) {
    err("Microphone blocked. Allow mic access, and make sure you opened the https:// tailnet URL."); return;
  }
  if ($("rec").classList.contains("recording")) {
    recorder.stop();
    return;
  }
  err(""); chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.onstop = () => {
    blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    $("play").src = URL.createObjectURL(blob); $("play").hidden = false;
    $("rec").hidden = true; $("keep").hidden = false; $("redo").hidden = false;
  };
  recorder.start();
  $("rec").classList.add("recording"); $("rec").textContent = "■ Stop";
};

function resetRecBtn() {
  $("rec").classList.remove("recording"); $("rec").textContent = "● Record";
}

$("redo").onclick = () => { blob = null; resetRecBtn(); render(); };

$("keep").onclick = async () => {
  const step = currentStep();
  if (!step || !blob) return;
  const fd = new FormData();
  fd.append("audio", blob, "clip.webm");
  fd.append("label", step.label);
  try {
    const r = await fetch(`/upload?token=${encodeURIComponent(TOKEN)}`, { method: "POST", body: fd });
    if (!r.ok) { err(`upload failed (${r.status}) — clip kept, press Keep to retry`); return; }
  } catch (e) {
    err("network error — clip kept, press Keep to retry"); return;
  }
  blob = null; resetRecBtn();
  await refreshCounts();
  render();
};

(async function init() {
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    err("This browser can't record (needs MediaRecorder + an https:// context)."); return;
  }
  await loadScript();
  await refreshCounts();
  render();
})();
