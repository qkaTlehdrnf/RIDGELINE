"""Replays league wars with the full battle log kept, optionally with one rule switched off (analysis only; rules in data.py stay as they are).
  python tools/why_no_war.py <war number 1-5> <variant: base|nofort|flat|both|nopact> <max ticks> <out json>"""
import json, os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import league as L
from ridgeline import data as D
from ridgeline import engine as E
gen, var, ticks, out = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
L.WORLD = 1.0
if var in ("nofort", "both"): D.FORT_DFN = 0.0; D.FORT_FIRE = 0.0
if var in ("flat", "both"):
    D.CITY_DFN = 0.0; m0 = L._map
    def _m(*a, **k):
        m = m0(*a, **k)
        for p in m.provs:
            if p.terrain != "water": p.dfn = 1.0
        return m
    L._map = _m
if var == "nopact": E.Game.order_offer = lambda self, pid, to, kind, **k: (("offers are switched off in this run", None) if kind == "pact" else ("no", None))
for kv in var.split(","):                 # any data.py constant can be overridden: RDY_DEFEND=0,STOCK_FLOW=10
    if "=" in kv: setattr(D, kv.split("=")[0], float(kv.split("=")[1]))
# instrumentation: how failed assaults end, and what state the armies are in
EP = {}; ENDS = []; SNAP = []
step0 = E.Game.step
def step(g):
    step0(g)
    live = set(g.assaults)
    for key in live:
        prov = key[0]
        if key not in EP:
            a0 = [g.units[i] for i in g.assaults[key]["ids"] if i in g.units]
            EP[key] = dict(entered=False, ids=set(), t=g.tick, n0=len(a0), aimed=sum(1 for u in a0 if prov in u.path), rdy0=sum(u.rdy for u in a0) / max(1, len(a0)))
        e = EP[key]
        for i in g.assaults[key]["ids"]:
            e["ids"].add(i); u = g.units.get(i)
            if u is not None and u.prov == prov: e["entered"] = True
    for key in [k for k in EP if k not in live]:
        e = EP.pop(key); prov, side = key; us = [g.units[i] for i in e["ids"] if i in g.units]
        ENDS.append(dict(n0=e["n0"], aimed=e["aimed"], rdy0=e["rdy0"], t=e["t"], won=int(g.owner[prov] == side), n=len(e["ids"]), entered=int(e["entered"]), dead=len(e["ids"]) - len(us), rout=sum(1 for u in us if u.rout),
                         still=sum(1 for u in us if u.path and u.path[-1] == prov), elsewhere=sum(1 for u in us if u.path and u.path[-1] != prov and not u.rout),
                         halted=sum(1 for u in us if not u.path), halted_dry=sum(1 for u in us if not u.path and u.dry), def_left=sum(1 for o in g.pos[prov] if o.owner != side)))
    if g.tick % 240 == 0:
        us = list(g.units.values()); n = len(us); own = g.owner
        fr = [u for u in us if any(own[b] >= 0 and own[b] != u.owner for b in g.provs[u.prov].nbrs)]
        occ = {}
        for u in us: occ[u.prov] = occ.get(u.prov, 0) + 1
        fp = set(u.prov for u in fr)
        SNAP.append(dict(t=g.tick, units=n, front_units=len(fr), rdy0=sum(1 for u in us if u.rdy < 5) / n, rdy40=sum(1 for u in us if u.rdy >= 40) / n,
                         front_rdy0=sum(1 for u in fr if u.rdy < 5) / max(1, len(fr)), rear_rdy_mean=sum(u.rdy for u in us if u.prov not in fp) / max(1, n - len(fr)),
                         dry=sum(1 for u in us if u.dry) / n, front_dry=sum(1 for u in fr if u.dry) / max(1, len(fr)), fighting=sum(1 for u in us if u.fighting) / n, contact=sum(1 for u in us if u.contact) / n,
                         moving=sum(1 for u in us if u.path) / n, front_stock0=sum(1 for i in fp if g.stock[i] < 1) / max(1, len(fp)), per_front_prov=len(fr) / max(1, len(fp)),
                         inflow_front=sum(D.STOCK_FLOW / (1 + g.stock_hop * g.hops[own[i]].get(i, 30)) for i in fp) / max(1, len(fp)),
                         front_pairs_pact=sum(1 for i in fp for b in g.provs[i].nbrs if own[b] >= 0 and own[b] != own[i] and (own[i], own[b]) in g.peace),
                         front_pairs=sum(1 for i in fp for b in g.provs[i].nbrs if own[b] >= 0 and own[b] != own[i])))
E.Game.step = step
from ridgeline import iface as I
VERBS = {}; SESS = []; MOVER = []
one0 = I.Session._one
def one(self, line):
    v = line.split()[0].lower(); VERBS[v] = VERBS.get(v, 0) + 1
    return one0(self, line)
I.Session._one = one
init0 = I.Session.__init__
def init(self, *a, **k):
    init0(self, *a, **k); SESS.append(self)
I.Session.__init__ = init
step1 = E.Game.step
def step2(g):
    step1(g)
    if g.tick % 240 == 0:
        ss = [x for x in SESS if x.g is g]; c = dict(t=g.tick, front=0, expand=0, explore=0, direct=0, rout=0, all_front=0, all_expand=0, all_direct=0, rdy_front=0.0, rdy_direct=0.0)
        for x in ss:
            for u in g.punits[x.pid].values():
                k = "front" if u.id in x.front else "expand" if u.id in x.expand else "explore" if u.id in x.explore else "direct"
                if k != "explore": c["all_" + k] += 1
                if k in ("front", "direct"): c["rdy_" + k] += u.rdy
                if u.path: c["rout" if u.rout else k] += 1
        MOVER.append(c)
E.Game.step = step2
F = tuple(w[0] for w in D.WORLD)
pol = json.load(open(os.path.join(ROOT, "runs/league_world/log.json")))["gens"][gen - 1]["policies"]     # the policies that fought war number <gen>
r = L.play([os.path.join(ROOT, f) for f in pol], F, 1, os.path.join(ROOT, "policies/model.json"), ticks)
json.dump(dict(verbs=VERBS, mover=MOVER, ends=ENDS, snap=SNAP, gen=gen, var=var, result=r["result"], battles=r["battles"], dip=r["dip"], timeline=r["timeline"], kinds=r["kinds"], bank=r["bank"], old=r["old"], tech=r["tech"]), open(out, "w"))
print(var, gen, "assaults", sum(b["won"] for b in r["battles"]), len(r["battles"]), "prov", sorted(r["result"]["provinces"])[-3:], "alive", sum(r["result"]["alive"]))
