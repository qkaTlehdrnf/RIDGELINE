// Turn a recorded replay (.rlr) into an MP4 with the WebGL viewer (tools/viewer_gl.html) in headless Chromium + ffmpeg.
//
//   npm i playwright && npx playwright install chromium        (once; ffmpeg must be on PATH)
//   node tools/make_video.mjs runs/replays/world_s1.rlr out.mp4 [options]
//
//   --from H --to H        game hours to cover (default: whole replay)
//   --speed X              game hours per video second; 2 = 1x (the live server speed), 48 = a day every half second
//   --fps 30  --size 1920x1080  --crf 20
//   --cam world            whole map (default)
//   --cam follow           follow the largest cluster of assaults, smoothly, at --zoom pixels per cell (default 16)
//   --cam X,Y,S            fixed camera: centre in map cells and pixels per cell
//   --focus <faction> [--fog]   highlight one faction; --fog shows only what that faction sees
//   --mode political|terrain|supply|forts   --no-labels   --no-fire
//   --gpu                  use the real GPU (on a 4090 this renders far faster than real time). Default: software GL
import { createRequire } from "module";
import { spawn } from "child_process";
import http from "http";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const { chromium } = createRequire(import.meta.url)("playwright");     // a local npm install or a global one on NODE_PATH
const here = path.dirname(fileURLToPath(import.meta.url));
const a = process.argv.slice(2);
if (a.length < 2 || a.includes("-h") || a.includes("--help")) { console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("\nimport")[0]); process.exit(0); }
const opt = (k, d) => { const i = a.indexOf(k); return i >= 0 ? a[i + 1] : d; };
const [src, out] = a;
const fps = +opt("--fps", 30), speed = +opt("--speed", 2), crf = opt("--crf", "20");
const [W, H] = opt("--size", "1920x1080").split("x").map(Number);
const camArg = opt("--cam", "world"), zoom = +opt("--zoom", 16);
const MODES = { political: 0, terrain: 1, supply: 2, forts: 3 };

const server = http.createServer((req, res) => {
  const f = req.url.startsWith("/replay.rlr") ? path.resolve(src) : path.join(here, "viewer_gl.html");
  res.writeHead(200, { "content-type": f.endsWith(".html") ? "text/html" : "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
}).listen(0, "127.0.0.1");
await new Promise(r => server.once("listening", r));
const port = server.address().port;

const args = a.includes("--gpu") ? ["--ignore-gpu-blocklist", "--enable-gpu", "--use-angle=default"] : ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"];
const browser = await chromium.launch({ args });
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
page.on("pageerror", e => console.error("page error:", e.message));
await page.goto(`http://127.0.0.1:${port}/viewer_gl.html?video=1`);
const info = await page.evaluate(() => RL.load("/replay.rlr"));
await page.evaluate(v => RL.setView(v), {
  focus: opt("--focus", null), fog: a.includes("--fog"), mode: MODES[opt("--mode", "political")] ?? 0,
  labels: !a.includes("--no-labels"), shots: !a.includes("--no-fire"),
});
const t0 = +opt("--from", info.t0), t1 = +opt("--to", info.t1);
const n = Math.max(1, Math.floor((t1 - t0) / speed * fps));
console.log(`replay hours ${info.t0}-${info.t1}; rendering ${t0}-${t1} at ${speed} h/s -> ${n} frames, ${(n / fps).toFixed(1)} s of video`);

const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg", "-r", String(fps), "-i", "-",
  "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], { stdio: ["pipe", "inherit", "inherit"] });

let cam = await page.evaluate(() => RL.fit());
if (camArg.includes(",")) { const [x, y, s] = camArg.split(",").map(Number); cam = { x, y, s }; }
const started = Date.now();
for (let f = 0; f < n; f++) {
  const T = t0 + f * speed / fps;
  if (camArg === "follow") {
    const h = await page.evaluate(() => RL.hotspot());
    if (h) { const k = f === 0 ? 1 : 0.03; cam = { x: cam.x + (h.x - cam.x) * k, y: cam.y + (h.y - cam.y) * k, s: cam.s + (zoom - cam.s) * (f === 0 ? 1 : 0.05) }; }
  }
  const url = await page.evaluate(([T, c, vt]) => RL.renderAt(T, c, 0.92, vt), [T, cam, f / fps]);
  const buf = Buffer.from(url.slice(url.indexOf(",") + 1), "base64");
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once("drain", r));
  if (f % 50 === 0) { const s = (Date.now() - started) / 1000; console.log(`frame ${f}/${n}  hour ${T.toFixed(1)}  ${(f / Math.max(s, 1e-3)).toFixed(1)} fps`); }
}
ff.stdin.end();
await new Promise(r => ff.on("close", r));
await browser.close(); server.close();
console.log("wrote", out);
