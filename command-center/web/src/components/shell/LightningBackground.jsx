import { useRef, useEffect } from "react";

/**
 * Ambient cyan lightning — a code-generated WebGL fragment shader (fbm noise
 * forks into a forked bolt) used as a living backdrop behind the console. Only
 * the lightning is kept from the original hero; locked to our cyan (hue ~190).
 *
 * Composited with `mix-blend-mode: screen` (set in CSS) so the mostly-black
 * shader output adds light over the aurora rather than covering it.
 *
 * Guards for a backdrop that runs the whole session:
 *   • render at a capped resolution (fbm is per-pixel expensive)
 *   • pause the RAF loop when the tab is hidden
 *   • honor prefers-reduced-motion (paint one static frame, no loop)
 *   • cancel the RAF + free GL resources on unmount
 */
const VERT = `
  attribute vec2 aPosition;
  void main() { gl_Position = vec4(aPosition, 0.0, 1.0); }
`;

const FRAG = `
  precision mediump float;
  uniform vec2 iResolution;
  uniform float iTime;
  uniform float uHue;
  uniform float uXOffset;
  uniform float uSpeed;
  uniform float uIntensity;
  uniform float uSize;
  #define OCTAVE_COUNT 10

  vec3 hsv2rgb(vec3 c) {
    vec3 rgb = clamp(abs(mod(c.x * 6.0 + vec3(0.0,4.0,2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return c.z * mix(vec3(1.0), rgb, c.y);
  }
  float hash11(float p) { p = fract(p * .1031); p *= p + 33.33; p *= p + p; return fract(p); }
  float hash12(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
  mat2 rotate2d(float theta) { float c = cos(theta); float s = sin(theta); return mat2(c, -s, s, c); }
  float noise(vec2 p) {
    vec2 ip = floor(p); vec2 fp = fract(p);
    float a = hash12(ip);
    float b = hash12(ip + vec2(1.0, 0.0));
    float c = hash12(ip + vec2(0.0, 1.0));
    float d = hash12(ip + vec2(1.0, 1.0));
    vec2 t = smoothstep(0.0, 1.0, fp);
    return mix(mix(a, b, t.x), mix(c, d, t.x), t.y);
  }
  float fbm(vec2 p) {
    float value = 0.0; float amplitude = 0.5;
    for (int i = 0; i < OCTAVE_COUNT; ++i) {
      value += amplitude * noise(p);
      p *= rotate2d(0.45); p *= 2.0; amplitude *= 0.5;
    }
    return value;
  }
  void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    uv = 2.0 * uv - 1.0;
    uv.x *= iResolution.x / iResolution.y;
    uv.x += uXOffset;
    uv += 2.0 * fbm(uv * uSize + 0.8 * iTime * uSpeed) - 1.0;
    float dist = abs(uv.x);
    vec3 baseColor = hsv2rgb(vec3(uHue / 360.0, 0.7, 0.8));
    vec3 col = baseColor * pow(mix(0.0, 0.07, hash11(iTime * uSpeed)) / dist, 1.0) * uIntensity;
    fragColor = vec4(col, 1.0);
  }
  void main() { mainImage(gl_FragColor, gl_FragCoord.xy); }
`;

export default function LightningBackground({
  hue = 190,        // our cyan #00D4FF ≈ 190°
  xOffset = 0,
  speed = 1.3,
  intensity = 0.7,
  size = 2,
  maxDim = 1280,    // resolution cap for the fbm-heavy shader
}) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, powerPreference: "low-power" });
    if (!gl) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const w = canvas.clientWidth || 1;
      const h = canvas.clientHeight || 1;
      const scale = Math.min(1, maxDim / Math.max(w, h));
      canvas.width = Math.max(1, Math.round(w * scale));
      canvas.height = Math.max(1, Math.round(h * scale));
    };
    resize();
    window.addEventListener("resize", resize);

    const compile = (src, type) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        console.error("lightning shader:", gl.getShaderInfoLog(s));
        gl.deleteShader(s);
        return null;
      }
      return s;
    };
    const vs = compile(VERT, gl.VERTEX_SHADER);
    const fs = compile(FRAG, gl.FRAGMENT_SHADER);
    if (!vs || !fs) return;
    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error("lightning link:", gl.getProgramInfoLog(program));
      return;
    }
    gl.useProgram(program);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const aPosition = gl.getAttribLocation(program, "aPosition");
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 2, gl.FLOAT, false, 0, 0);

    const u = (n) => gl.getUniformLocation(program, n);
    const uRes = u("iResolution"), uTime = u("iTime"), uHue = u("uHue"),
      uX = u("uXOffset"), uSpeed = u("uSpeed"), uInt = u("uIntensity"), uSize = u("uSize");

    const start = performance.now();
    let raf = 0;
    let running = true;

    const draw = (t) => {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uTime, ((t ?? performance.now()) - start) / 1000);
      gl.uniform1f(uHue, hue);
      gl.uniform1f(uX, xOffset);
      gl.uniform1f(uSpeed, speed);
      gl.uniform1f(uInt, intensity);
      gl.uniform1f(uSize, size);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };

    const loop = (t) => {
      if (!running) return;
      resize();
      draw(t);
      raf = requestAnimationFrame(loop);
    };

    if (reduced) {
      draw();                       // one static frame, no animation
    } else {
      raf = requestAnimationFrame(loop);
    }

    const onVisibility = () => {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!reduced) {
        running = true;
        raf = requestAnimationFrame(loop);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.deleteBuffer(buf);
    };
  }, [hue, xOffset, speed, intensity, size, maxDim]);

  return <canvas ref={canvasRef} className="lightning-bg" aria-hidden="true" />;
}
