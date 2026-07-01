import { useRef, useEffect } from "react";

// Ported verbatim from neuro-portfolio (Tailwind → inline styles). A raw-WebGL
// topographic neon ground that fades in over the final stretch of the journey
// (progress 0.83 → 1.0) behind the ending overlay.
const VS = `
  attribute vec2 position;
  void main() { gl_Position = vec4(position, 0.0, 1.0); }
`;

const FS = `
  precision highp float;
  uniform float u_time;
  uniform vec2 u_resolution;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i + vec2(0.0, 0.0)), hash(i + vec2(1.0, 0.0)), u.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
      u.y
    );
  }

  void main() {
    vec2 uv = (gl_FragCoord.xy * 2.0 - u_resolution.xy) / min(u_resolution.x, u_resolution.y);

    float depth = 1.0 / (uv.y + 1.15);
    vec2 gridUv = vec2(uv.x * depth, depth + u_time * 0.15);

    float n = noise(gridUv * 3.5);
    float ripples = sin(gridUv.y * 18.0 + n * 8.0 + u_time * 0.5);
    float topoLine = smoothstep(0.03, 0.0, abs(ripples));

    vec3 baseColor   = vec3(0.016, 0.016, 0.059);
    vec3 accentColor = vec3(0.02,  0.05,  0.20);
    vec3 neonColor   = vec3(0.0,   0.831, 1.0);

    vec3 finalColor = mix(baseColor, accentColor, n * 0.6);
    finalColor += topoLine * neonColor * depth * 0.4;

    float fade = smoothstep(0.1, -1.0, uv.y);
    finalColor *= (1.0 - length(uv) * 0.45) * (1.0 - fade);

    gl_FragColor = vec4(finalColor, 1.0);
  }
`;

export default function ProceduralGroundBackground({ progressRef }) {
  const canvasRef = useRef(null);
  const wrapperRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl");
    if (!gl) return;

    const mkShader = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };

    const prog = gl.createProgram();
    gl.attachShader(prog, mkShader(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, mkShader(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const vbuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbuf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const posLoc = gl.getAttribLocation(prog, "position");
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    const timeLoc = gl.getUniformLocation(prog, "u_time");
    const resLoc = gl.getUniformLocation(prog, "u_resolution");

    let rafId;
    const render = (t) => {
      // The ground only becomes visible over the final stretch (progress > 0.83).
      // Skip the fullscreen shader draw entirely while it's invisible so it isn't
      // saturating the GPU underneath the brain canvas for the whole journey.
      if (progressRef.current < 0.8) {
        rafId = requestAnimationFrame(render);
        return;
      }
      const w = window.innerWidth;
      const h = window.innerHeight;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
      gl.uniform1f(timeLoc, t * 0.001);
      gl.uniform2f(resLoc, w, h);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      rafId = requestAnimationFrame(render);
    };
    rafId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(rafId);
  }, []);

  useEffect(() => {
    let rafId;
    const tick = () => {
      if (wrapperRef.current) {
        const p = progressRef.current;
        const opacity = Math.max(0, Math.min(1, (p - 0.83) / 0.17));
        wrapperRef.current.style.opacity = String(opacity);
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [progressRef]);

  return (
    <div
      ref={wrapperRef}
      style={{ position: "fixed", inset: 0, zIndex: 5, pointerEvents: "none", opacity: 0 }}
    >
      <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />
    </div>
  );
}
