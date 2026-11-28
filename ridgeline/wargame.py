"""Staff wargame: a commander tests strategies during a live game without touching it.

trial() builds a private copy of the war AS THE COMMANDER BELIEVES IT TO BE and plays each candidate policy
forward for some hours:
  - own provinces, units, stocks, forts, bank: exact
  - enemy units: only those currently visible, with the same strength estimates the observation shows
    (exact next to your units or under a rec; otherwise the rough estimate, assumed to be infantry)
  - enemy land: last known owner; everything never seen is treated as neutral and empty
  - enemy capitals: the real one only if found, otherwise their known province farthest from you
  - research in the forecast is rolled afresh: the real hidden results of upgrades are never used, enemies are assumed un-upgraded
  - the enemies are assumed to follow the stock policy (policies/basic.py); their bank is assumed equal to yours
Nothing here reads hidden state, so a trial cannot leak through the fog. It is a forecast under stated
assumptions, not the truth: use it to compare candidates against each other, not to predict the war.
"""
import copy
import os
import random
import time

from . import data as D
from .engine import Game, Player, Unit

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "policies")


def library(name):
    """Source of a ready-made policy in policies/ (basic, immediate, learned, evolved, ...), or None."""
    if not name.replace("_", "").isalnum(): return None
    f = os.path.join(LIB, name + ".py")
    return open(f, encoding="utf-8").read() if os.path.exists(f) else None


def belief_game(sess):
    """A new Game holding only what sess's player knows. Returns (game, {unit id in the real game: unit in the copy})."""
    g0 = sess.g; pid = sess.pid; p0 = sess.p
    g = Game.__new__(Game)
    g.map = g0.map; g.seed = g0.seed; g.rng = random.Random(g0.tick * 7919 + pid)
    g.provs = g0.provs; g.n = g0.n; g.stock_hop = g0.stock_hop
    g.sea0 = g0.sea0; g.seacell = g0.seacell; g.nb2 = g0.nb2; g.ages = g0.ages; g.strikes = []; g._seadirty = True
    g.hostile = {k: v for k, v in g0.hostile.items() if pid in k}
    g.tick = g0.tick; g.max_ticks = 10 ** 9; g.over = False; g.winner = None
    ko = p0.known_owner
    g.owner = [ko.get(i, -1) for i in range(g.n)]
    for i in range(g.n):
        if g0.owner[i] == pid: g.owner[i] = pid
    g.stock = [g0.stock[i] if g.owner[i] == pid else (100.0 if g.owner[i] >= 0 else 0.0) for i in range(g.n)]
    g.fort = [(g0.fort[i] if g.owner[i] == pid else float(p0.known_fort.get(i, 0))) for i in range(g.n)]
    g.cold = set(g0.cold); g.jungle = g0.jungle; g.deals = {}; g.allies = set()
    kd = p0.known_dev                              # cities and roads: its own exactly, others' as last seen
    g.dev = [(g0.dev[i] if g.owner[i] == pid else kd.get(i, (0.0, 0.0))[0]) for i in range(g.n)]
    g.infra = [(g0.infra[i] if g.owner[i] == pid else kd.get(i, (0.0, 0.0))[1]) for i in range(g.n)]
    g._note = ""; g.lk = [dict() for _ in range(g.n)]; g._lkmax = 1.0
    g.join = {}; g.cut = {}; g.local0 = list(g0.local0); g.local_era = g0.local_era; g.local = [(float(p0.known_local.get(i, 0.0)) if g.owner[i] < 0 else 0.0) for i in range(g.n)]      # local peoples as last seen
    for (a_, b_), l_ in p0.known_link.items(): g.lk[a_][b_] = g.lk[b_][a_] = l_; g._lkmax = max(g._lkmax, D.RAIL_MOVE if l_ == 2 else D.ROAD_MOVE)      # roads and railways as last seen
    g.access = set(k for k in g0.access if pid in k); g.prod = [float(pr.y) for pr in g.provs]; g.prod_mp = [float(pr.mp) for pr in g.provs]; g.agg = [1.0] * g.n
    g.hops = [{} for _ in g0.players]; g.hub = [{} for _ in g0.players]; g.throttle = [{} for _ in g0.players]; g.load = [{} for _ in g0.players]
    g.units = {}; g.next_id = g0.next_id; g.pos = [[] for _ in range(g.n)]
    g.battles = {}; g.contacts = []; g.assaults = {}; g.battle_log = []
    g.pacts = {}; g.peace = set(); g.offers = {}; g.next_offer = 10 ** 6; g.dip_log = []
    g._sight = g0._sight; g._pfree = g0._pfree; g._pown = {}          # sight tables depend only on the map: share them
    g.players = []
    pc = g.provs[p0.capital]
    for q0 in g0.players:
        q = Player(q0.id, q0.faction); q.alive = q0.alive; q.hardy = q0.hardy; q.tropic = q0.tropic
        q.explored = set(p0.explored)              # everyone in the forecast knows exactly the land this commander knows
        if q0.id == pid:
            q.capital = q0.capital; q.depots = dict(q0.depots); q.depot_want = dict(q0.depot_want); q.depot_build = dict(q0.depot_build); q.known_depots = dict(p0.known_depots); q.res = q0.res; q.mp = q0.mp; q.queue = [list(x) for x in q0.queue]
            q.marks = {c: [dict(st) for st in v] for c, v in q0.marks.items()}; q.stats = {c: v[-1] for c, v in q.marks.items()}; q.bank = dict(q0.bank); q.mult = dict(q0.mult); q.mor0 = q0.mor0
            q.works = [list(w) for w in q0.works]; q.maint = q0.maint
            q.tech = dict(q0.tech); q.dead = set(q0.dead); q.research = [list(r) for r in q0.research]; q.tech_log = list(q0.tech_log)
        else:
            held = [i for i in range(g.n) if g.owner[i] == q0.id]
            if q0.id in p0.known_caps: q.capital = p0.known_caps[q0.id]
            elif held: q.capital = max(held, key=lambda i: ((g.provs[i].cx - pc.cx) ** 2 + (g.provs[i].cy - pc.cy) ** 2, i))
            else: q.capital = -1; q.alive = False          # never met: not part of this forecast
            kd = [d for d, o in p0.known_depots.items() if o == q0.id and g.owner[d] == q0.id]
            if kd: q.depots = {d: 1.0 / len(kd) for d in kd}; q.depot_want = dict(q.depots); q._cap = q.capital if q.capital in kd else kd[0]      # depots it has seen stand in for the ones it has not
            q.res = p0.res; q.mp = p0.mp; q.bank = dict(p0.bank)
        # what has been discovered: its own exactly; of the others the forecast assumes what the commander has itself
        q.base = q0.base if q0.id == pid else p0.base; q.known = set(p0.known); q.gen = dict(p0.gen); q.lmul = {c: dict(v) for c, v in p0.lmul.items()} if q0.id == pid else {}
        q.gmul = dict(p0.gmul) if q0.id == pid else dict(dig=1.0, cost=1.0); q.gadd = dict(p0.gadd) if q0.id == pid else dict(xp0=0)
        for k in ("fort_cap", "sail", "sea_reach", "ocean", "sat", "missile", "aa"): setattr(q, k, getattr(p0, k))
        q._q = {}                                              # how good a model not yet built will be is unknown here too
        if q0.id != pid: q.marks = {c: [dict(v[-1])] for c, v in p0.marks.items()}; q.stats = {c: v[-1] for c, v in q.marks.items()}
        g.hide_tech(q, g0.tick * 7919 + pid * 31 + q0.id)      # the forecast does not know what research would find: it rolls its own dice
        g.players.append(q)
    g.blockade = [set() for _ in g.players]; g.searange = [{} for _ in g.players]
    g.pacts = {k: dict(v) for k, v in g0.pacts.items() if pid in k}; g._peace()      # only the commander's own pacts are known to it
    twin = {}; g._index(); g._own_dirty = True
    g._wealth()
    me = g.players[pid]; me.fxp = dict(p0.fxp)
    for u0 in g0.punits[pid].values():
        u = Unit(u0.id, pid, u0.type, me.marks[u0.type][u0.st["mark"] - 1], u0.prov)        # the copy's own stats table: research in the forecast must not touch the real one
        for k in ("path", "prog", "str", "group", "fighting", "supplied", "born", "contact", "dig", "rdy", "plan_t", "plan_b", "dry", "x", "y", "ox", "oy", "last", "rout",
                  "xp", "mor", "sup", "settled", "hours", "base"):
            setattr(u, k, getattr(u0, k))
        u.path = list(u0.path); g.pos[u.prov].append(u); g._add(u); twin[u0.id] = u; me.upkeep += u.st["upkeep"]; me.n_units += 1
        if u0.id in g0.active: g.active.add(u.id)
    for i in sorted(p0.visible):
        e = g0.estimate(pid, i)
        if not e or not e[3]: continue
        owner = next(u.owner for u in g0.pos[i] if u.owner != pid)                      # whose units they are is visible; how strong is an estimate
        if not g.players[owner].alive: continue
        lvl, types, strength, n = e
        kinds = [t for t, c in sorted(types.items()) for _ in range(c)] if types else ["inf"] * n
        kinds = [t if t in g.players[owner].stats else "inf" for t in kinds]
        if i >= g.sea0:
            for t in kinds:
                if D.UNITS[t]["dom"]: u = g.spawn(owner, t, i); u.str = max(1.0, min(100.0, strength / float(len(kinds))))
            continue
        for t in kinds:
            u = g.spawn(owner, t, i); u.str = max(1.0, min(100.0, strength / float(len(kinds))))
        g.owner[i] = owner; g._own_dirty = True
    for q in g.players:
        if not q.alive and q.id != pid:
            for i in range(g.n):
                if g.owner[i] == q.id: g.owner[i] = -1
    g._sea_update(); g._supply(); g._vision()
    return g, twin


def _measure(g, pid):
    p = g.players[pid]
    return dict(prov=g.owner.count(pid), y=sum(g.provs[i].y for i in range(g.n) if g.owner[i] == pid),
                units=len(g.punits[pid]), strength=sum(u.str for u in g.punits[pid].values()),
                enemy=sum(u.str for u in g.units.values() if u.owner != pid), losses=p.losses, kills=p.kills)


def prepare(sess, names, enemy_policy="basic"):
    """Phase 1 (needs the live game to hold still): fork one belief copy per candidate."""
    from .iface import Session
    foe = library(enemy_policy); jobs = []
    for name in names[:4]:
        src = sess.source(name)
        if src is None:
            jobs.append((name, " %s: unknown (define it with a 'candidate %s' block, or use current/%s)" % (
                name, name, "/".join(sorted(f[:-3] for f in os.listdir(LIB) if f.endswith(".py")))))); continue
        code, every = src
        g, twin = belief_game(sess); pid = sess.pid; ss = []; bad = None
        for q in g.players:
            s = Session(g, q.id); s.model = sess.model if q.id == pid else {}
            if q.id == pid:
                r = s.set_policy("main", code, every)
                if "installed" not in r: bad = " %s: %s" % (name, r); break
                s.front = set(sess.front); s.resting = set(sess.resting); s.expand = set(sess.expand); s.expand_to = dict(sess.expand_to); s.explore = set(sess.explore); s.p.groups = dict(sess.p.groups)
                if name == "current" and "main" in sess.policies:
                    try: s.policies["main"]["mem"] = copy.deepcopy(sess.policies["main"]["mem"])
                    except Exception: pass
            elif q.alive and foe: s.set_policy("main", foe)
            ss.append(s)
        jobs.append((name, bad or (g, ss)))
    return dict(jobs=jobs, pid=sess.pid, tick=sess.g.tick, enemy=enemy_policy)


def run(prep, hours):
    """Phase 2 (independent of the live game): play every fork forward and report."""
    hours = max(6, min(240, int(hours))); out = []; t0 = time.time(); pid = prep["pid"]
    for name, job in prep["jobs"]:
        if isinstance(job, str): out.append(job); continue
        g, ss = job; a = _measure(g, pid); err = None
        for _ in range(hours):
            for s in ss: s.pre_tick()
            g.step()
            if g.over:
                if not g.players[pid].alive or any(q.alive for q in g.players if q.id != pid): break
                g.over = False                               # no enemy known (yet): keep forecasting the expansion
        ran = g.tick - prep["tick"]
        me = ss[pid]
        if "main" not in me.policies: err = "removed (crash or time budget)"
        elif me.policies["main"]["err"]: err = me.policies["main"]["err"]
        b = _measure(g, pid); mine = [x for x in g.battle_log if x["side"] == pid]
        line = " %s: provinces %+d, yield %+d/day, own strength %+d (units lost %d), enemy strength seen %+d, assaults won %d/%d" % (
            name, b["prov"] - a["prov"], b["y"] - a["y"], b["strength"] - a["strength"], b["losses"], b["enemy"] - a["enemy"],
            sum(x["won"] for x in mine), len(mine))
        if not g.players[pid].alive: line += ", CAPITAL LOST after %d h" % ran
        elif ran < hours: line += ", enemy capital (as guessed) taken after %d h" % ran
        if err: line += ", POLICY ERROR %s" % err
        out.append(line)
    return ("trial %d h from t%d (forecast from what you know; enemies assumed to play '%s'; %.1fs)\n" % (
        hours, prep["tick"], prep["enemy"], time.time() - t0)) + "\n".join(out)


def trial(sess, names, hours, enemy_policy="basic"):
    return run(prepare(sess, names, enemy_policy), hours)
