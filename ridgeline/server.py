"""Real-time server. The game advances on a wall clock; agents may command once every --cmd-interval seconds.

  python -m ridgeline.server --seed 7 --tps 2 --policy0 policies/basic.py --policy1 policies/basic.py --policy2 policies/basic.py
  open http://127.0.0.1:8765/            live spectator (a consumer of /scene and /frame, see ridgeline/render.py)

Player endpoints (text/plain, ?p=0|1):
  GET  /brief                 rules, province table, command grammar (send once)
  GET  /obs?mode=delta|full   compact observation
  POST /turn                  body = command lines. Waits until this player's command window opens (once every
                              --cmd-interval seconds), runs the commands, returns results + blank line + delta.
  POST /policy?name=main&every=6   body = python defining tick(api): replace the standing-order program. Empty body removes.
  GET  /json                  verbose JSON state
Spectator / control:
  GET /scene   GET /frame     POST /control?tps=4 | pause=1 | pause=0
"""
import argparse
import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .engine import Game
from . import wargame
from .iface import Session
from .render import frame, scene

HERE = os.path.dirname(os.path.abspath(__file__))


class Live:
    def __init__(self, factions=("aurum", "sable", "cinder"), seed=0, tps=2.0, policies=(None, None, None), replay=None, max_ticks=4800,
                 paused=False, cmd_interval=5.0):
        self.g = Game(factions=factions, seed=seed, max_ticks=max_ticks)
        self.sess = [Session(self.g, i) for i in range(len(self.g.players))]
        pol = [f for f in policies if f]                      # fewer policy files than factions (world map): they are dealt out in turn
        for s in self.sess:
            f = policies[s.pid] if s.pid < len(policies) else (pol[s.pid % len(pol)] if pol else None)
            if f: print("P%d policy:" % s.pid, s.set_policy("main", open(f, encoding="utf-8").read()))
        self.tps = tps; self.paused = paused; self.cmd_interval = cmd_interval
        self.cv = threading.Condition(); self.replay = replay; self.frames = [frame(self.g, compact=True)]
        self.next_cmd = [0.0] * len(self.g.players)
        self.io = [dict(turns=0, obs_chars=0, act_chars=0) for _ in self.g.players]
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self): self.thread.start()

    def _loop(self):
        g = self.g; nxt = time.perf_counter()
        while not g.over:
            if self.paused: time.sleep(0.05); nxt = time.perf_counter(); continue
            with self.cv:
                for s in self.sess: s.pre_tick()
                g.step()
                if self.replay is not None and g.tick % 24 == 0: self.frames.append(frame(g, compact=True))
                self.cv.notify_all()
            nxt += 1.0 / self.tps
            d = nxt - time.perf_counter()
            if d > 0: time.sleep(d)
            else: nxt = time.perf_counter()
        if self.replay:
            with open(self.replay, "w") as f:
                json.dump(dict(scene=scene(g), frames=self.frames, result=dict(winner=g.winner, ticks=g.tick)), f, separators=(",", ":"))

    def turn(self, p, text):
        """Enforces the command cadence: blocks until this player's window opens."""
        while not self.g.over:
            d = self.next_cmd[p] - time.time()
            if d <= 0: break
            time.sleep(min(d, 0.2))
        self.next_cmd[p] = time.time() + self.cmd_interval
        lines = [l for l in text.replace(";", "\n").split("\n") if l.strip()]
        trials = [l.split() for l in lines if l.split()[0].lower() == "trial"]
        rest = "\n".join(l for l in lines if l.split()[0].lower() != "trial")
        preps = []
        with self.cv:
            r = self.sess[p].act(rest) if rest.strip() else ""
            for t in trials[:1]:                              # one staff wargame per turn; forked here, played outside the lock
                hours = int(t[1]) if len(t) > 1 and t[1].isdigit() else 48
                preps.append((wargame.prepare(self.sess[p], [x for x in t[1:] if not x.isdigit()]), hours))
        for prep, hours in preps:
            try: r = (r + "\n" if r else "") + wargame.run(prep, hours)
            except Exception as ex: r = (r + "\n" if r else "") + "trial failed: %s" % ex
        with self.cv:
            o = self.sess[p].obs()
        self.io[p]["turns"] += 1; self.io[p]["obs_chars"] += len(o); self.io[p]["act_chars"] += len(text)
        return (r + "\n\n" if r else "") + o


def make_handler(live, viewer_html):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass

        def _send(self, body, ctype="text/plain; charset=utf-8", code=200):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(b)

        def _route(self, method):
            u = urlparse(self.path); q = parse_qs(u.query); path = u.path; body = ""
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            try:
                if path in ("/", "/index.html"): return self._send(viewer_html, "text/html; charset=utf-8")
                if path == "/scene": return self._send(json.dumps(scene(live.g)), "application/json")
                if path == "/frame":
                    with live.cv: f = frame(live.g)
                    f["tps"] = live.tps; f["io"] = live.io
                    return self._send(json.dumps(f, separators=(",", ":")), "application/json")
                if path == "/control" and method == "POST":
                    if "tps" in q: live.tps = max(0.2, min(500.0, float(q["tps"][0])))
                    if "pause" in q: live.paused = q["pause"][0] == "1"
                    return self._send("tps %g paused %d" % (live.tps, live.paused))
                p = int(q.get("p", ["0"])[0])
                if not (0 <= p < len(live.g.players)): raise ValueError("no such player")
                s = live.sess[p]
                if path == "/brief": return self._send(s.brief())
                if path == "/obs":
                    with live.cv: return self._send(s.obs(q.get("mode", ["delta"])[0]))
                if path == "/json":
                    with live.cv: return self._send(json.dumps(s.obs_json()), "application/json")
                if path == "/turn" and method == "POST": return self._send(live.turn(p, body))
                if path == "/policy" and method == "POST":
                    with live.cv:
                        if q.get("candidate", ["0"])[0] == "1": return self._send(s.set_candidate(q.get("name", ["a"])[0], body, int(q.get("every", ["6"])[0])))
                        return self._send(s.set_policy(q.get("name", ["main"])[0], body, int(q.get("every", ["6"])[0])))
                return self._send("not found", code=404)
            except Exception as ex:
                return self._send("error: %s: %s" % (type(ex).__name__, ex), code=400)

        def do_GET(self): self._route("GET")
        def do_POST(self): self._route("POST")
    return H


def serve(live, port=8765):
    html = open(os.path.join(HERE, "..", "tools", "viewer.html"), encoding="utf-8").read()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(live, html)); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--seed", type=int, default=None, help="map + start seed (default: random)")
    ap.add_argument("--tps", type=float, default=2.0, help="game hours per real second")
    ap.add_argument("--cmd-interval", type=float, default=5.0, help="seconds between command windows per player")
    ap.add_argument("--policy0", default=None); ap.add_argument("--policy1", default=None); ap.add_argument("--policy2", default=None)
    ap.add_argument("--factions", default="aurum,sable,cinder"); ap.add_argument("--replay", default=None)
    ap.add_argument("--world", action="store_true", help="the world map with about 30 factions; policies given are dealt out in turn")
    ap.add_argument("--max-ticks", type=int, default=3600); ap.add_argument("--paused", action="store_true")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.randrange(10 ** 6)
    live = Live("world" if a.world else tuple(a.factions.split(",")), seed, a.tps, (a.policy0, a.policy1, a.policy2), a.replay, a.max_ticks, a.paused, a.cmd_interval)
    serve(live, a.port); live.start()
    print("Ridgeline live on http://127.0.0.1:%d/  seed %d  %g ticks/s  commands every %gs" % (a.port, seed, a.tps, a.cmd_interval), flush=True)
    while not live.g.over: time.sleep(0.5)
    time.sleep(1.0)
    print("game over: winner", live.g.winner, "tick", live.g.tick, "io", live.io, flush=True)


if __name__ == "__main__":
    main()
