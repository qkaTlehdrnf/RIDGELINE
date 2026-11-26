"""Real-time server. The game advances on a wall clock; agents talk to it over HTTP whenever they are ready.

  python -m ridgeline.server --speed 1 --p1 bot            # P0 is driven over HTTP, P1 by the scripted bot
  open http://localhost:8765/                               # live spectator view

Player endpoints (text/plain; add ?p=0|1 and &key=<player key> when --keys is on):
  GET  /brief                 static rules, map regions and command grammar (send once)
  GET  /obs?mode=delta|full   compact observation; delta = changed lines + new events since your last call
  GET  /wait?timeout=20&min=2 long-poll: returns a delta as soon as something important happens
                              (attacked, contact, found, lost, warn) or at timeout; never sooner than `min` seconds
  POST /act                   body = command lines; response = result lines (queries are answered inline)
  POST /turn                  body = command lines; response = results + blank line + fresh delta (one round trip)
  POST /script?name=x&every=5 body = python source defining tick(api); empty body removes it
  GET  /json                  verbose JSON state (for programmatic bots)
Spectator / control:
  GET  /  /spectate  /mapdata        POST /control?speed=4 | pause=1 | pause=0
"""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .engine import Game
from .iface import Session
from .match import map_json

HERE = os.path.dirname(os.path.abspath(__file__))


class Live:
    def __init__(self, factions=("aurum", "sable"), speed=1.0, bots=(None, None), replay=None, max_ticks=18000, start_paused=False):
        self.g = Game(factions=factions, max_ticks=max_ticks)
        self.sess = [Session(self.g, 0), Session(self.g, 1)]
        self.bots = [mk(self.sess[i]) if mk else None for i, mk in enumerate(bots)]
        self.speed = speed; self.paused = start_paused
        self.cv = threading.Condition()
        self.replay = replay; self.frames = []
        self.io = [dict(obs_calls=0, obs_chars=0, act_calls=0, act_chars=0) for _ in range(2)]
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self): self.thread.start()

    def _loop(self):
        g = self.g; nxt = time.perf_counter()
        while not g.over:
            if self.paused: time.sleep(0.05); nxt = time.perf_counter(); continue
            with self.cv:
                if g.tick % 10 == 0:
                    for b in self.bots:
                        if b: b.step()
                for s in self.sess: s.pre_tick()
                g.step()
                if self.replay is not None and g.tick % 10 == 0: self.frames.append(g.snapshot())
                self.cv.notify_all()
            nxt += 0.1 / self.speed
            d = nxt - time.perf_counter()
            if d > 0: time.sleep(d)
            else: nxt = time.perf_counter()
        with self.cv: self.cv.notify_all()
        if self.replay:
            with open(self.replay, "w") as f:
                json.dump(dict(map=map_json(g), frames=self.frames,
                               result=dict(winner=g.winner, ticks=g.tick)), f, separators=(",", ":"))

    # --- player API (thread safe) ---
    def obs(self, p, mode="delta"):
        with self.cv:
            o = self.sess[p].obs(mode)
        self.io[p]["obs_calls"] += 1; self.io[p]["obs_chars"] += len(o)
        return o

    def wait(self, p, timeout=20.0, min_s=0.0):
        """Block (in game time scaled to wall time) until an important event is pending, then return a delta."""
        end = time.time() + timeout; t0 = time.time()
        with self.cv:
            while not self.g.over:
                now = time.time()
                if now >= end: break
                if now - t0 >= min_s and self.sess[p].pending_events(): break
                self.cv.wait(min(0.25, end - now))
        return self.obs(p)

    def act(self, p, text):
        with self.cv:
            r = self.sess[p].act(text)
        self.io[p]["act_calls"] += 1; self.io[p]["act_chars"] += len(text)
        return r

    def script(self, p, name, code, every):
        with self.cv:
            return self.sess[p].set_script(name, code, every)


def make_handler(live, keys=None, viewer_html=""):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a): pass

        def _send(self, body, ctype="text/plain; charset=utf-8", code=200):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(b)

        def _player(self, q):
            p = int(q.get("p", ["0"])[0])
            if p not in (0, 1): raise ValueError("p must be 0 or 1")
            if keys and q.get("key", [""])[0] != keys[p]: raise PermissionError("bad key")
            return p

        def _route(self, method):
            u = urlparse(self.path); q = parse_qs(u.query); path = u.path
            body = ""
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            try:
                if path in ("/", "/index.html"): return self._send(viewer_html, "text/html; charset=utf-8")
                if path == "/mapdata": return self._send(json.dumps(map_json(live.g)), "application/json")
                if path == "/spectate":
                    with live.cv:
                        s = live.g.snapshot(); s["over"] = live.g.over; s["winner"] = live.g.winner
                        s["speed"] = live.speed; s["io"] = live.io
                    return self._send(json.dumps(s, separators=(",", ":")), "application/json")
                if path == "/control" and method == "POST":
                    if "speed" in q: live.speed = max(0.1, min(200.0, float(q["speed"][0])))
                    if "pause" in q: live.paused = q["pause"][0] == "1"
                    return self._send("speed %g paused %d" % (live.speed, live.paused))
                p = self._player(q)
                if path == "/brief": return self._send(live.sess[p].brief())
                if path == "/obs": return self._send(live.obs(p, q.get("mode", ["delta"])[0]))
                if path == "/wait":
                    return self._send(live.wait(p, float(q.get("timeout", ["20"])[0]), float(q.get("min", ["0"])[0])))
                if path == "/json":
                    with live.cv: d = live.sess[p].obs_json()
                    return self._send(json.dumps(d), "application/json")
                if path == "/act" and method == "POST": return self._send(live.act(p, body))
                if path == "/turn" and method == "POST":
                    r = live.act(p, body) if body.strip() else ""
                    return self._send((r + "\n\n" if r else "") + live.obs(p))
                if path == "/script" and method == "POST":
                    return self._send(live.script(p, q.get("name", ["main"])[0], body, int(q.get("every", ["5"])[0])))
                return self._send("not found", code=404)
            except PermissionError as ex: return self._send(str(ex), code=403)
            except Exception as ex: return self._send("error: %s: %s" % (type(ex).__name__, ex), code=400)

        def do_GET(self): self._route("GET")
        def do_POST(self): self._route("POST")
    return H


def serve(live, port=8765, keys=None):
    html = open(os.path.join(HERE, "..", "tools", "viewer.html"), encoding="utf-8").read()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(live, keys, html))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765); ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--p0", default="http", help="http | bot"); ap.add_argument("--p1", default="bot")
    ap.add_argument("--factions", default="aurum,sable"); ap.add_argument("--replay", default=None)
    ap.add_argument("--keys", action="store_true", help="require a per-player key (printed at start)")
    ap.add_argument("--paused", action="store_true", help="start paused; POST /control?pause=0 to begin")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(HERE, ".."))
    from bots.basic import Bot
    mk = lambda kind: (lambda s: Bot(s)) if kind == "bot" else None
    live = Live(tuple(a.factions.split(",")), a.speed, (mk(a.p0), mk(a.p1)), a.replay, start_paused=a.paused)
    keys = None
    if a.keys:
        import secrets
        keys = [secrets.token_hex(4), secrets.token_hex(4)]; print("keys: p0=%s p1=%s" % tuple(keys))
    serve(live, a.port, keys); live.start()
    print("Ridgeline live on http://127.0.0.1:%d/  speed x%g" % (a.port, a.speed), flush=True)
    while not live.g.over: time.sleep(0.5)
    time.sleep(1.0)
    print("game over: winner", live.g.winner, "tick", live.g.tick, "io", live.io)


if __name__ == "__main__":
    main()
