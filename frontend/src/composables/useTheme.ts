import { computed, nextTick, reactive, ref, watch, type ComputedRef, type Ref } from "vue";

type Theme = "dark" | "light";
export type PourPresetId = "off" | "crisp" | "standard" | "lush" | "custom";

export interface PourConfig {
  enabled: boolean;
  duration: number;
  fallEnd: number;
  streamWidth: number;
  waveAmp: number;
  splash: number;
}

const STORAGE_KEY = "hd-theme";
const POUR_CONFIG_KEY = "hd-theme-pour";
const SURF_SAMPLES = 96;

export const POUR_PRESETS: Record<Exclude<PourPresetId, "custom">, PourConfig> = {
  off: { enabled: false, duration: 1050, fallEnd: 0.26, streamWidth: 4.5, waveAmp: 15, splash: 1 },
  crisp: { enabled: true, duration: 760, fallEnd: 0.22, streamWidth: 3.8, waveAmp: 10, splash: 0.6 },
  standard: { enabled: true, duration: 1050, fallEnd: 0.26, streamWidth: 4.5, waveAmp: 15, splash: 1 },
  lush: { enabled: true, duration: 1480, fallEnd: 0.28, streamWidth: 5.6, waveAmp: 24, splash: 1.5 },
};

const clampNum = (v: unknown, min: number, max: number, fb: number) => {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fb;
};

function readPourConfig(): PourConfig {
  const def = POUR_PRESETS.standard;
  try {
    const raw = localStorage.getItem(POUR_CONFIG_KEY);
    if (!raw) return { ...def };
    const p = JSON.parse(raw) as Partial<PourConfig>;
    return {
      enabled: typeof p.enabled === "boolean" ? p.enabled : def.enabled,
      duration: Math.round(clampNum(p.duration, 400, 2400, def.duration)),
      fallEnd: clampNum(p.fallEnd, 0.14, 0.42, def.fallEnd),
      streamWidth: clampNum(p.streamWidth, 2, 12, def.streamWidth),
      waveAmp: Math.round(clampNum(p.waveAmp, 0, 36, def.waveAmp)),
      splash: Number(clampNum(p.splash, 0, 2, def.splash).toFixed(2)),
    };
  } catch {
    return { ...def };
  }
}

const pourConfig = reactive<PourConfig>(readPourConfig());

watch(
  pourConfig,
  (val) => {
    try {
      localStorage.setItem(POUR_CONFIG_KEY, JSON.stringify(val));
    } catch {}
  },
  { deep: true },
);

const activePreset = computed<PourPresetId>(() => {
  if (!pourConfig.enabled) return "off";
  const match = (["crisp", "standard", "lush"] as const).find((k) => {
    const p = POUR_PRESETS[k];
    return (
      Math.abs(pourConfig.duration - p.duration) <= 10 &&
      Math.abs(pourConfig.waveAmp - p.waveAmp) <= 0.5 &&
      Math.abs(pourConfig.splash - p.splash) <= 0.05 &&
      Math.abs(pourConfig.streamWidth - p.streamWidth) <= 0.2 &&
      Math.abs(pourConfig.fallEnd - p.fallEnd) <= 0.015
    );
  });
  return match ?? "custom";
});

function applyPreset(id: Exclude<PourPresetId, "custom">) {
  if (id === "off") {
    pourConfig.enabled = false;
    return;
  }
  Object.assign(pourConfig, POUR_PRESETS[id]);
}

function resetPourConfig() {
  Object.assign(pourConfig, POUR_PRESETS.standard);
}

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
const smooth = (a: number, b: number, v: number) => {
  const t = clamp01((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};

const NOISE = (() => {
  let s = 0x2f6bff;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  return Array.from({ length: 256 }, rnd);
})();

function noise1(x: number): number {
  const i = Math.floor(x);
  const f = x - i;
  const a = NOISE[((i % 256) + 256) % 256]!;
  const b = NOISE[(((i + 1) % 256) + 256) % 256]!;
  return a + (b - a) * (f * f * (3 - 2 * f));
}

function smoothCurveThrough(pts: [number, number][]): string {
  const n = pts.length;
  if (n < 2) return "";
  let d = `M${pts[0]![0].toFixed(1)} ${pts[0]![1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const p0 = pts[i > 0 ? i - 1 : 0]!;
    const p1 = pts[i]!;
    const p2 = pts[i + 1]!;
    const p3 = pts[i + 2 < n ? i + 2 : n - 1]!;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += `C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

function teardrop(cx: number, cy: number, r: number, vx: number, vy: number): string {
  const speed = Math.hypot(vx, vy);
  const stretch = Math.min(1.42, 1 + speed / 520);
  const ux = speed > 1 ? vx / speed : 0;
  const uy = speed > 1 ? vy / speed : 1;
  const px = -uy;
  const py = ux;
  const a = r * stretch;
  const b = r * (1 / Math.sqrt(stretch)) * 0.96;
  const k = 0.552;

  const fx = cx + ux * a * 0.96;
  const fy = cy + uy * a * 0.96;
  const bx = cx - ux * a * 1.08;
  const by = cy - uy * a * 1.08;
  const lx = cx + px * b;
  const ly = cy + py * b;
  const rx = cx - px * b;
  const ry = cy - py * b;

  return (
    `M${fx.toFixed(1)} ${fy.toFixed(1)}` +
    `C${(fx + px * b * k).toFixed(1)} ${(fy + py * b * k).toFixed(1)} ${(lx + ux * a * k).toFixed(1)} ${(ly + uy * a * k).toFixed(1)} ${lx.toFixed(1)} ${ly.toFixed(1)}` +
    `C${(lx - ux * a * k).toFixed(1)} ${(ly - uy * a * k).toFixed(1)} ${(bx + px * b * 0.42).toFixed(1)} ${(by + py * b * 0.42).toFixed(1)} ${bx.toFixed(1)} ${by.toFixed(1)}` +
    `C${(bx - px * b * 0.42).toFixed(1)} ${(by - py * b * 0.42).toFixed(1)} ${(rx - ux * a * k).toFixed(1)} ${(ry - uy * a * k).toFixed(1)} ${rx.toFixed(1)} ${ry.toFixed(1)}` +
    `C${(rx + ux * a * k).toFixed(1)} ${(ry + uy * a * k).toFixed(1)} ${(fx - px * b * k).toFixed(1)} ${(fy - py * b * k).toFixed(1)} ${fx.toFixed(1)} ${fy.toFixed(1)}Z`
  );
}

interface PourEnv {
  W: number;
  H: number;
  x0: number;
  y0: number;
  seed: number;
  cfg: PourConfig;
}

function makeGeometry(env: PourEnv) {
  const { H, x0, y0, seed, cfg } = env;
  const fallEnd = cfg.fallEnd;
  const riseStart = fallEnd * 0.94;
  const RISE_END = 0.96;
  const START_DEPTH = 0.07;
  const OVERSHOOT = 0.16;

  const spanY = H * (1 + START_DEPTH + OVERSHOOT);
  const coverAt = (t: number) => Math.pow(clamp01((t - riseStart) / (RISE_END - riseStart)), 0.92);
  const surfaceBase = (t: number) => H * (1 + START_DEPTH) - spanY * coverAt(t);

  const surfaceAt = (x: number, t: number) => {
    const cover = coverAt(t);
    const base = surfaceBase(t);
    const grow = smooth(0.08, 0.42, cover);
    const fadeOut = 1 - 0.84 * cover;
    const amp = cfg.waveAmp * grow * fadeOut;
    const ph1 = seed * 6.1;
    const ph2 = seed * 3.7;
    const ph3 = seed * 9.3;

    const s1 = Math.sin(x * 0.0048 + ph2 - t * 3.1);
    const s2 = Math.sin(x * 0.0122 + ph1 + t * 6.2);
    const s3 = Math.sin(x * 0.029 + ph3 - t * 11.4);
    const wave =
      (s1 + 0.22 * s1 * s1) * 0.56 +
      (s2 + 0.28 * s2 * s2) * 0.88 +
      s3 * 0.18;

    let y = base - wave * amp;

    const dt = t - fallEnd * 0.96;
    if (dt > 0 && dt < 0.5) {
      const dist = Math.abs(x - x0);
      const front = dt * 680;
      const packet = Math.exp(-Math.pow((dist - front * 0.6) / (135 + front * 0.55), 2));
      const decay = Math.exp(-dt * 4.8) * smooth(0, 0.06, dt);
      const ring = Math.cos((dist - front) * 0.032) * 7.0 + 4.5 * Math.exp(-Math.pow(dist / 95, 2));
      y -= ring * packet * decay * (0.45 + 0.45 * cfg.splash);
    }
    return y;
  };

  const headY = (t: number) => y0 + (H - y0) * Math.pow(clamp01(t / fallEnd), 1.55);

  return { env, surfaceAt, headY };
}

function buildPaths(g: ReturnType<typeof makeGeometry>, t: number) {
  const { W, H, x0, y0, seed, cfg } = g.env;
  const sw = cfg.streamWidth;
  const spStrength = cfg.splash;

  const surfPts: [number, number][] = [];
  for (let i = 0; i <= SURF_SAMPLES; i++) {
    const x = (i / SURF_SAMPLES) * W;
    surfPts.push([x, g.surfaceAt(x, t)]);
  }
  const surfCurve = smoothCurveThrough(surfPts);
  const pool =
    `M0 ${H.toFixed(1)}L0 ${surfPts[0]![1].toFixed(1)}` +
    surfCurve.slice(surfCurve.indexOf("C")) +
    `L${W.toFixed(1)} ${H.toFixed(1)}Z`;

  const surfAtStream = g.surfaceAt(x0, t);
  const rawHead = g.headY(t);
  const submerged = rawHead >= surfAtStream - 2 && surfAtStream <= H + 6;
  const streamBottom = submerged ? surfAtStream + 6 : Math.min(rawHead, H + 4);
  const streamLen = streamBottom - y0;

  let stream = "";
  const airDrops: string[] = [];

  if (streamLen > 1.5) {
    const SEG = 22;
    const left: [number, number][] = [];
    const right: [number, number][] = [];
    for (let i = 0; i <= SEG; i++) {
      const u = i / SEG;
      const y = y0 + streamLen * u;
      const taper = 1 - 0.34 * u + 0.14 * u * u;
      const neck = 1 - 0.22 * Math.sin(u * Math.PI);
      const bulge = submerged ? 0 : 0.48 * Math.exp(-Math.pow((u - 0.95) / 0.09, 2));
      const gnarl = 0.82 + 0.36 * noise1(u * 4.2 + seed * 13 + t * 3.0);
      const sway = Math.sin(u * 3.8 + seed * 5.3 + t * 6.6) * 1.6 * u;
      let hw = sw * taper * neck * gnarl + sw * bulge;

      if (submerged && u > 0.88) {
        const m = smooth(0.88, 1.0, u);
        hw += sw * (0.95 * m * m);
      }
      const cx = x0 + sway;
      left.push([cx - hw, y]);
      right.push([cx + hw, y]);
    }

    const leftCurve = smoothCurveThrough(left);
    const rightRev = right.slice().reverse();
    const rightCurve = smoothCurveThrough(rightRev);
    const hc = (left[SEG]![0] + right[SEG]![0]) / 2;
    const hr = (right[SEG]![0] - left[SEG]![0]) / 2;
    const capY = submerged ? streamBottom + 2 : streamBottom + hr * 1.75;

    stream =
      leftCurve +
      `Q${hc.toFixed(1)} ${capY.toFixed(1)} ${rightRev[0]![0].toFixed(1)} ${rightRev[0]![1].toFixed(1)}` +
      rightCurve.slice(rightCurve.indexOf("C")) +
      "Z";

    const emit = (frac: number, side: number, size: number) => {
      const uy = y0 + streamLen * frac;
      if (uy < y0 + 8 || uy > surfAtStream - 6) return;
      const n = noise1(frac * 29 + seed * 7 + t * 1.2);
      const cx = x0 + side * (sw * 1.55 + n * 5.5);
      const r = size * (0.75 + 0.5 * n);
      airDrops.push(teardrop(cx, uy, r, 0, 140));
    };
    emit(0.28, -1, 1.5);
    emit(0.48, 1, 1.7);
    emit(0.68, -1, 1.4);
    emit(0.84, 1, 1.8);
  }

  let drops = airDrops.join("");
  const splashSpan = 0.22;
  const sp = (t - cfg.fallEnd * 0.96) / splashSpan;
  if (sp > 0 && sp < 1 && spStrength > 0) {
    const SPECS: [number, number, number, number, number][] = [
      [-42, 54, 3.1, 0.0, 0.72],
      [48, 50, 2.9, 0.04, 0.74],
      [-78, 42, 2.5, 0.06, 0.78],
      [86, 38, 2.4, 0.02, 0.8],
      [-24, 64, 2.6, 0.05, 0.66],
      [28, 60, 2.5, 0.08, 0.68],
      [-108, 28, 1.9, 0.1, 0.76],
      [114, 26, 1.8, 0.12, 0.76],
    ];
    for (let k = 0; k < SPECS.length; k++) {
      const [dxMax, peakH, baseR, delay, dur] = SPECS[k]!;
      const u = (sp - delay) / dur;
      if (u <= 0 || u >= 1) continue;
      const jit = 0.88 + 0.24 * noise1(k * 5.7 + seed * 2.1);
      const startX = x0 + Math.sign(dxMax) * (sw * 1.5);
      const x = startX + dxMax * jit * u * Math.sqrt(spStrength);
      const arc = 4 * u * (1 - u);
      const surfHere = Math.min(H, g.surfaceAt(x, t));
      const y = surfHere - peakH * jit * spStrength * arc + u * 6;
      if (y > surfHere - 1.2) continue;

      const vx = dxMax * jit;
      const vy = -peakH * 4 * (1 - 2 * u);
      const r = baseR * Math.sin(u * Math.PI) * (0.78 + 0.28 * jit);
      if (r < 0.75) continue;
      drops += teardrop(x, y, r, vx, vy);
    }
  }

  return { pool, stream, drops };
}

let clipSlots: { pool: SVGPathElement; stream: SVGPathElement; drops: SVGPathElement } | null = null;

function ensureClipSvg() {
  if (clipSlots) return clipSlots;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", "0");
  svg.setAttribute("height", "0");
  svg.setAttribute("aria-hidden", "true");
  svg.style.cssText = "position:fixed;width:0;height:0;pointer-events:none;z-index:-1";

  const defs = document.createElementNS(ns, "defs");
  const clip = document.createElementNS(ns, "clipPath");
  clip.setAttribute("id", "hd-liquid-clip");
  clip.setAttribute("clipPathUnits", "userSpaceOnUse");

  const mkPath = () => {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("clip-rule", "evenodd");
    p.setAttribute("d", "");
    clip.appendChild(p);
    return p;
  };
  const pool = mkPath();
  const stream = mkPath();
  const drops = mkPath();

  defs.appendChild(clip);
  svg.appendChild(defs);
  document.body.appendChild(svg);
  clipSlots = { pool, stream, drops };
  return clipSlots;
}

function readStored(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "dark" || stored === "light") return stored;
  // Respect OS preference; default to dark
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function apply(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  // Element Plus dark mode class
  root.classList.toggle("dark", theme === "dark");

  // Set a meta theme-color for browser chrome
  const meta = (
    document.querySelector('meta[name="theme-color"]') ??
    (() => {
      const m = document.createElement("meta");
      m.name = "theme-color";
      document.head.appendChild(m);
      return m;
    })()
  ) as HTMLMetaElement;
  meta.content = theme === "dark" ? "#050914" : "#f5f7fa";
}

const current = ref<Theme>(readStored());

// Apply on first load
apply(current.value);

let pouring = false;
let pourRaf = 0;

function resolveOrigin(trigger?: Event | HTMLElement | null): { x0: number; y0: number } {
  let el: HTMLElement | null = null;
  if (trigger instanceof HTMLElement) {
    el = trigger;
  } else if (trigger && typeof trigger === "object" && "currentTarget" in trigger) {
    const ct = trigger.currentTarget;
    const tgt = trigger.target;
    if (ct instanceof HTMLElement) el = ct;
    else if (tgt instanceof Element) el = tgt.closest("button") ?? (tgt as HTMLElement);
  }
  if (!el) {
    el = document.querySelector<HTMLElement>("[data-theme-toggle]");
  }
  if (el) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 || r.height > 0) {
      return { x0: r.left + r.width / 2, y0: r.bottom + 3 };
    }
  }
  return { x0: window.innerWidth - 96, y0: 44 };
}

/** Toggle between light and dark with liquid pour reveal when supported. */
function toggle(trigger?: Event | HTMLElement | null): Theme {
  const next: Theme = current.value === "dark" ? "light" : "dark";
  const root = document.documentElement;
  const startVT = (document as Document & {
    startViewTransition?: (cb: () => Promise<void> | void) => {
      ready: Promise<void>;
      finished: Promise<void>;
    };
  }).startViewTransition;

  const canPour =
    pourConfig.enabled &&
    !pouring &&
    typeof startVT === "function" &&
    typeof CSS !== "undefined" &&
    CSS.supports("clip-path", "url(#hd-liquid-clip)") &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!canPour) {
    current.value = next;
    return next;
  }

  pouring = true;
  const cfgSnapshot: PourConfig = { ...pourConfig };
  const durationMs = cfgSnapshot.duration;
  const slots = ensureClipSvg();
  const { x0, y0 } = resolveOrigin(trigger);
  const g = makeGeometry({
    W: window.innerWidth,
    H: window.innerHeight,
    x0,
    y0,
    seed: 2 + Math.random() * 8,
    cfg: cfgSnapshot,
  });

  const renderAt = (t: number) => {
    const { pool, stream, drops } = buildPaths(g, clamp01(t));
    slots.pool.setAttribute("d", pool);
    slots.stream.setAttribute("d", stream);
    slots.drops.setAttribute("d", drops);
  };

  root.style.setProperty("--hd-pour-ms", `${durationMs}ms`);
  root.classList.add("is-theme-pouring");
  renderAt(0);

  const cleanup = () => {
    if (pourRaf) cancelAnimationFrame(pourRaf);
    pourRaf = 0;
    pouring = false;
    root.classList.remove("is-theme-pouring");
  };

  try {
    const vt = startVT.call(document, async () => {
      current.value = next;
      apply(next);
      await nextTick();
    });

    const t0 = performance.now();
    vt.ready
      .then(() => {
        const tick = () => {
          const t = clamp01((performance.now() - t0) / durationMs);
          renderAt(t);
          if (t < 1) pourRaf = requestAnimationFrame(tick);
        };
        tick();
      })
      .catch(() => {});

    vt.finished.then(cleanup, cleanup);
  } catch {
    cleanup();
    current.value = next;
  }

  return next;
}

/** Set a specific theme. */
function set(theme: Theme) {
  current.value = theme;
}

// Persist changes
watch(current, (val) => {
  localStorage.setItem(STORAGE_KEY, val);
  apply(val);
});

export function useTheme(): {
  current: Ref<Theme>;
  toggle: (trigger?: Event | HTMLElement | null) => Theme;
  set: (t: Theme) => void;
  pourConfig: PourConfig;
  activePreset: ComputedRef<PourPresetId>;
  applyPreset: (id: Exclude<PourPresetId, "custom">) => void;
  resetPourConfig: () => void;
} {
  return {
    current,
    toggle,
    set,
    pourConfig,
    activePreset,
    applyPreset,
    resetPourConfig,
  };
}
