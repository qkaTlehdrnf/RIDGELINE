"""Record a match into a compact binary replay (.rlr) for tools/viewer3.html (WebGL viewer) and tools/make_video.py.

Every game hour is one frame and holds EVERY unit with its full state (position, type, strength, experience, morale,
suppression, readiness, state word, mark, group, destination) plus who fires at whom, province owners, forts, supply
stocks and per-faction numbers. Frames are delta-coded against the previous one (a key frame every KEY frames) and
zlib-compressed, so a 3,000-hour world war with ~20k units stays a few hundred MB.

This file only READS the game through public attributes after each g.step(); it never changes the engine.

  python tools/record_replay.py --world --seed 1 --hours 3000 --pol-dir runs/league_world --out runs/replays/world_s1.rlr
  python tools/record_replay.py --seed 7 --hours 1500 --out runs/replays/s7.rlr          # 3 factions, policies/basic.py

--pol-dir: a folder holding <faction>.py or <faction>/genN.py (the newest gen is used); missing factions use basic.py.

File layout (little endian):
  "RLR1" | blob_0 | blob_1 | ... | header JSON (utf-8) | uint32 header offset | uint32 header length | "RLR1"
  header = {scene, factions, types, states, frames: [[offset, length, t, key], ...], cells: [offset, length], timeline, result}
  cells blob = zlib(int16 province id per map cell, row-major, -1 = no province)
  frame blob = zlib(
     int32 x 8: t, key(1/0), N units, P provinces, S shots, meta length, G groups, reserved
     ids      int32[N]  sorted; delta-coded (first value raw, then differences)
     cols     per unit, each column as its own byte plane; on non-key frames value - previous value of the same id
              (previous = 0 for a new unit), wrapping:  x*20 lo, x*20 hi, y*20 lo, y*20 hi, owner, type, str, xp, mor,
              sup, rdy, state, flags, mark, dest lo, dest hi, group
              flags: 1 firing while advancing (assault), 2 firing while holding, 4 supplied, 8 routing, 16 digging,
                     32 old mark (a newer version of its type exists), 64 preparing an attack
              dest = final province of its path, 65535 = none; group = index into meta.groups + 1, 0 = none
     prov     owner+1, fort, stock/2 per province, as byte planes, delta-coded like units
     vis      per faction: visible-now bitset, explored-ever bitset, ceil(P/8) bytes each (bit p&7 of byte p>>3);
              XOR with the previous frame on non-key frames
     shots    uint16 shooter index, uint16 target index (indexes into this frame's unit arrays), S pairs
     meta     JSON: players [{res, mp, inc, bank, tech, alive, n, kills}], battles, contacts, groups, fxp, ev)
"""
import json
import os
import struct
import sys
import time
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ridgeline import data as D                     # noqa: E402
from ridgeline.engine import Game                  # noqa: E402
from ridgeline.iface import Session                # noqa: E402
from ridgeline.render import scene                 # noqa: E402

KEY = 24
EV_KINDS = ("took", "lostprov", "tech", "surrender", "fall", "pact", "offer", "intel", "cut", "mail", "gift", "news")
STATES = ["ready", "moving", "assault", "defending", "pinned", "routing", "shaken", "preparing", "digging", "refitting"]
SIDX = {s: i for i, s in enumerate(STATES)}
TYPES = list(D.UNITS)
TIDX = {t: i for i, t in enumerate(TYPES)}


def _planes(cols):
    return b"".join(np.ascontiguousarray(c, dtype=np.uint8).tobytes() for c in cols)


class Recorder:
    def __init__(self, g, path):
        self.g = g; self.f = open(path, "wb"); self.f.write(b"RLR1"); self.index = []; self.n = 0
        self.prev_ids = np.zeros(0, np.int64); self.prev_cols = np.zeros((17, 0), np.int64); self.prev_prov = None
        self.timeline = []; self.ev_seen = [0] * len(g.players)
        cells = np.array([(-1 if c is None else c) for c in g.map.cell], dtype=np.int16).tobytes()
        self.cells = self._blob(zlib.compress(cells, 6))

    def _blob(self, b):
        off = self.f.tell(); self.f.write(b); return [off, len(b)]

    def _shots(self, units, pos):
        """Who fires at whom this hour. The engine does not keep its target lists, so take the nearest enemy in range of
        every firing unit (the engine's first target, from the positions after the step)."""
        g = self.g; B = D.BUCKET; out = []
        for u in units:
            if not u.fighting or u.rout: continue
            r = u.st["range"]; r2 = r * r; R = 1 if r <= B else 2; bx = int(u.x // B); by = int(u.y // B); best = None; bd = r2
            for dx in range(-R, R + 1):
                for dy in range(-R, R + 1):
                    for t in g.grid.get((bx + dx, by + dy), ()):
                        if t.owner == u.owner: continue
                        d = (t.x - u.x) ** 2 + (t.y - u.y) ** 2
                        if d <= bd: bd = d; best = t
            if best is not None and best.id in pos: out.append((pos[u.id], pos[best.id]))
        return out

    def frame(self):
        g = self.g; units = sorted(g.units.values(), key=lambda u: u.id); N = len(units)
        groups = {}; ids = np.fromiter((u.id for u in units), np.int64, N)
        pos = {u.id: i for i, u in enumerate(units)}
        cols = np.zeros((17, N), np.int64)
        for i, u in enumerate(units):
            x = max(0, min(65535, int(u.x * 20))); y = max(0, min(65535, int(u.y * 20)))
            st = g.state(u); fl = (1 if u.fighting == 1 else 2 if u.fighting == 2 else 0) | (4 if u.supplied else 0) | (8 if u.rout else 0) \
                | (16 if u.dig else 0) | (32 if u.st is not g.players[u.owner].stats[u.type] else 0) | (64 if u.plan_t >= 0 else 0)
            dest = u.path[-1] if u.path else 65535
            gi = 0
            if u.group:
                k = "%d:%s" % (u.owner, u.group); gi = groups.get(k)
                if gi is None: gi = groups[k] = len(groups) + 1
            cols[:, i] = (x & 255, x >> 8, y & 255, y >> 8, u.owner, TIDX.get(u.type, 0), max(0, min(100, round(u.str))), round(u.xp), round(u.mor),
                          round(u.sup), round(u.rdy), SIDX.get(st, 0), fl, u.st.get("mark", 1), dest & 255, dest >> 8, min(255, gi))
        prov = np.array([[o + 1 for o in g.owner], [g.fort_level(i) for i in range(g.n)], [min(255, int(s) // 2) for s in g.stock]], np.int64)
        nb = (g.n + 7) // 8; vis = np.zeros((2 * len(g.players), nb * 8), np.uint8)
        for i, p in enumerate(g.players):
            if p.visible: vis[2 * i, list(p.visible)] = 1
            if p.explored: vis[2 * i + 1, list(p.explored)] = 1
        vis = np.packbits(vis, axis=1, bitorder="little")
        key = self.n % KEY == 0
        if key: dc = cols; dp = prov; dv = vis
        else:
            prev = np.zeros((17, N), np.int64)
            if len(self.prev_ids):
                j = np.searchsorted(self.prev_ids, ids); j = np.minimum(j, len(self.prev_ids) - 1); hit = self.prev_ids[j] == ids
                prev[:, hit] = self.prev_cols[:, j[hit]]
            dc = cols - prev; dp = prov - self.prev_prov; dv = vis ^ self.prev_vis
        self.prev_ids = ids; self.prev_cols = cols; self.prev_prov = prov; self.prev_vis = vis
        shots = self._shots(units, pos)
        players = []
        for i, p in enumerate(g.players):
            players.append(dict(res=int(p.res), mp=int(p.mp), inc=round(p.income - p.upkeep, 1), bank=[int(p.bank[k]) for k in ("steel", "oil", "rare")],
                                tech=[sum(p.tech.values()), len(p.dead), len(p.research)], alive=p.alive, n=len(g.punits[i]), kills=p.kills))
        ev = []
        for i, p in enumerate(g.players):                 # new event lines (captures, losses, research results ...)
            new = p.events[self.ev_seen[i]:]; self.ev_seen[i] = len(p.events)
            for t, kind, text in new[-6:]:
                if kind in EV_KINDS: ev.append([i, kind, str(text)[:140]])
        gl = [None] * len(groups)
        for k, v in groups.items(): gl[v - 1] = k
        meta = json.dumps(dict(players=players, battles=[[k, b["frm"], b["side"], len(b["att"])] for k, b in g.battles.items()],
                               contacts=g.contacts, groups=gl, fxp=[{k: round(v) for k, v in p.fxp.items()} for p in g.players], ev=ev[:40]),
                          separators=(",", ":")).encode()
        idd = np.diff(ids, prepend=0).astype(np.int32)
        body = struct.pack("<8i", g.tick, int(key), N, g.n, len(shots), len(meta), len(groups), 0) + idd.tobytes() \
            + _planes(dc & 255) + _planes(dp & 255) + dv.tobytes() + np.array(shots, np.uint16).reshape(-1).tobytes() + meta
        off, ln = self._blob(zlib.compress(body, 6))
        self.index.append([off, ln, g.tick, int(key)]); self.n += 1
        if g.tick % 24 == 0:
            n = len(g.players)
            self.timeline.append(dict(t=g.tick, prov=[len(g.owned[i]) for i in range(n)], units=[len(g.punits[i]) for i in range(n)]))

    def close(self, result):
        g = self.g; sc = scene(g); sc.pop("cells", None)
        head = json.dumps(dict(scene=sc, factions=[p.faction for p in g.players], vis=True, types=TYPES, states=STATES, key=KEY,
                               frames=self.index, cells=self.cells, timeline=self.timeline, result=result,
                               unit_ranges={t: D.RANGE.get(t, 3) for t in TYPES}), separators=(",", ":")).encode()
        off = self.f.tell(); self.f.write(head); self.f.write(struct.pack("<II", off, len(head)) + b"RLR1"); self.f.close()


def main():
    a = sys.argv[1:]
    if "-h" in a or "--help" in a: print(__doc__); return
    def opt(k, d):
        return a[a.index(k) + 1] if k in a else d
    seed = int(opt("--seed", 1)); hours = int(opt("--hours", 3000)); out = opt("--out", os.path.join(ROOT, "runs", "replays", "replay.rlr"))
    every = int(opt("--every", 1)); pol_dir = opt("--pol-dir", None); basic = os.path.join(ROOT, "policies", "basic.py")
    if "--world" in a:
        from ridgeline.worldgen import gen_world
        factions = tuple(w[0] for w in D.WORLD); gmap = gen_world(seed, scale=float(opt("--scale", 1.0)))
    else:
        factions = tuple(opt("--factions", "aurum,sable,cinder").split(",")); gmap = None
    g = Game(factions=factions, seed=seed, gmap=gmap, max_ticks=hours); n = len(g.players)
    sess = [Session(g, i) for i in range(n)]
    bm = os.path.join(ROOT, "policies", "model.json")
    for s in sess:
        f = basic
        if pol_dir:
            fa = g.players[s.pid].faction; c1 = os.path.join(pol_dir, fa + ".py"); c2 = os.path.join(pol_dir, fa)
            if os.path.exists(c1): f = c1
            elif os.path.isdir(c2):
                gens = sorted((x for x in os.listdir(c2) if x.startswith("gen") and x.endswith(".py")), key=lambda x: int(x[3:-3]))
                if gens: f = os.path.join(c2, gens[-1])
        r = s.set_policy("main", open(f, encoding="utf-8").read())
        if os.path.exists(bm): s.model = json.load(open(bm))
        print(g.players[s.pid].faction, os.path.relpath(f, ROOT), r[:40], flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    rec = Recorder(g, out); rec.frame(); t0 = time.time()
    while not g.over:
        for s in sess: s.pre_tick()
        g.step()
        if g.tick % every == 0: rec.frame()
        if g.tick % 100 == 0:
            print("t%d units %d  %.0fs  %.1f MB" % (g.tick, len(g.units), time.time() - t0, rec.f.tell() / 1e6), flush=True)
    res = dict(seed=seed, winner=g.winner, ticks=g.tick, provinces=[len(g.owned[i]) for i in range(n)], alive=[p.alive for p in g.players])
    rec.close(res); print("wrote", out, "%.1f MB" % (os.path.getsize(out) / 1e6), res)


if __name__ == "__main__":
    main()
