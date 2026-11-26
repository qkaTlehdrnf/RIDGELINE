"""Render protocol: everything a front end needs, as plain JSON. No drawing code lives in the engine.

scene (static, once per game)
  {"version": 2, "gw", "gh",            grid size in cells
   "cells": [prov_id per cell, row-major],   province shapes; a renderer may trace polygons or draw cells
   "provs": [{"id","terrain","elev","yield","manpower","city","cx","cy","nbrs"}],
   "factions": [name per player], "capitals": [province per player], "seed"}      elev is 0..3
frame (one per tick or per sample)
  {"t", "owner": [owner per province, -1 neutral],
   "units": [[id, owner, type, prov, next_prov or -1, progress 0..1, strength 0..100, fighting 0|1|2, supplied 0|1,
              readiness 0..100, prepared-attack target or -1, prepared bonus %, x, y,       x, y in grid cells: where the unit really is
              experience 0..100, morale 0..100, suppression 0..100, state word, group name]],
   "fxp": [{group name: formation experience} per player],
   "battles": [[target_prov, [from_provs], attacking_side]],     assaults (a move order into a defended province)
   "contacts": [[prov_a, prov_b]],                               borders where both sides are trading fire right now
   "fort": [fort level 0..3 per province], "stock": [supplies per province],
   "bank": [[steel, oil, rare] per player], "tech": [[upgrade levels gained, dead ends hit, projects running] per player],
   "res": [r0, r1], "mp": [manpower0, manpower1], "income": [net0, net1], "visible": [[provs seen by P0], [provs seen by P1]],
   "queue": [[[type, prov, hours_left]...], ...], "alive": [bool per player], "over", "winner"}
   (res, mp, income, visible, queue are lists with one entry per player)
compact frame (frame(g, compact=True), used for replays of big games): no "units", "stock" or "visible"; instead
   "stacks": [[prov, owner, next_prov or -1, units, avg strength, avg readiness, fighting, supplied, plan target, plan bonus, 0, mean x, mean y]]
   "dotsb": base64 of 5 bytes per unit: x*20 (uint16 little-endian), y*20 (uint16), owner | 64 if firing | 128 if routing,
   "counts": [{type: n} per player], "xp" / "mor": average experience / morale per player, and "queue" holds only the
   number in training per player. frame(g, compact=True, stacks=False) leaves "stacks" empty (very large games).
scene provs carry "steel", "oil", "rare" (deposit yield per day, 0 if none).
scene provs also carry "biome" ("" | "desert" | "tundra"), "sea" (neighbours across water) and "name" (real city name or "").
Units move freely: draw them at (x, y). A province is taken at its key point (cx, cy). The bundled tools/viewer.html is one
consumer; a 3D client, sprite renderer or video exporter can read the same two objects.
"""


import base64


def scene(g):
    m = g.map
    return dict(version=2, gw=m.gw, gh=m.gh, cells=m.cell, seed=g.seed, factions=[p.faction for p in g.players],
                capitals=list(m.capitals),
                provs=[dict(id=p.id, terrain=p.terrain, elev=p.elev, city=p.city, cx=round(p.cx, 2), cy=round(p.cy, 2),
                            nbrs=p.nbrs, manpower=p.mp, biome=p.biome, sea=list(p.sea), name=p.name, steel=p.steel, oil=p.oil, rare=p.rare, **{"yield": p.y}) for p in g.provs])


def frame(g, compact=False, stacks=True):
    f = dict(t=g.tick, owner=list(g.owner),
             battles=[[k, b["frm"], b["side"]] for k, b in g.battles.items()], contacts=[list(c) for c in g.contacts],
             fort=[g.fort_level(i) for i in range(g.n)], res=[int(p.res) for p in g.players], mp=[int(p.mp) for p in g.players],
             income=[round(p.income - p.upkeep, 1) for p in g.players], alive=[p.alive for p in g.players],
             bank=[[int(p.bank[k]) for k in ("steel", "oil", "rare")] for p in g.players],
             tech=[[sum(p.tech.values()), len(p.dead), len(p.research)] for p in g.players],
             over=g.over, winner=g.winner)
    if not compact:
        f.update(units=[[u.id, u.owner, u.type, u.prov, u.path[0] if u.path else -1, round(u.prog, 2), round(u.str),
                         u.fighting, int(u.supplied), round(u.rdy), u.plan_t, round(u.plan_b), round(u.x, 2), round(u.y, 2),
                         round(u.xp), round(u.mor), round(u.sup), g.state(u), u.group] for u in g.units.values()],
                 fxp=[{k: round(v) for k, v in p.fxp.items()} for p in g.players],
                 stock=[int(x) for x in g.stock], visible=[sorted(p.visible) for p in g.players],
                 queue=[[list(q) for q in p.queue] for p in g.players])
        return f
    n = len(g.players); counts = [{} for _ in range(n)]; xp = [0.0] * n; mor = [0.0] * n; cnt = [0] * n
    buf = bytearray(5 * len(g.units)); j = 0; st = {}
    for u in g.units.values():
        o = u.owner; c = counts[o]; c[u.type] = c.get(u.type, 0) + 1; xp[o] += u.xp; mor[o] += u.mor; cnt[o] += 1
        x = max(0, min(65535, int(u.x * 20))); y = max(0, min(65535, int(u.y * 20))); buf[j] = x & 255; buf[j + 1] = x >> 8; buf[j + 2] = y & 255; buf[j + 3] = y >> 8
        buf[j + 4] = o | (64 if u.fighting else 0) | (128 if u.rout else 0); j += 5
        if stacks:
            nx = u.path[0] if u.path else -1; k = (u.prov, o, nx, u.plan_t if nx < 0 else -1)
            a = st.get(k)
            if a is None: a = st[k] = [u.prov, o, nx, 0, 0.0, 0.0, 0, 1, k[3], 0.0, 0.0, 0.0, 0.0]
            a[3] += 1; a[4] += u.str; a[5] += u.rdy; a[6] = max(a[6], u.fighting); a[7] = min(a[7], int(u.supplied))
            a[9] += u.plan_b; a[11] += u.x; a[12] += u.y
    f["dotsb"] = base64.b64encode(bytes(buf)).decode("ascii")
    f.update(stacks=[[a[0], a[1], a[2], a[3], round(a[4] / a[3]), round(a[5] / a[3]), a[6], a[7], a[8], round(a[9] / a[3]), 0, round(a[11] / a[3], 1), round(a[12] / a[3], 1)]
                     for a in st.values()], counts=counts, queue=[len(p.queue) for p in g.players],
             xp=[round(xp[i] / cnt[i]) if cnt[i] else 0 for i in range(n)], mor=[round(mor[i] / cnt[i]) if cnt[i] else 0 for i in range(n)])
    return f
