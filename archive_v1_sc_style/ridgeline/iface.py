"""LLM-facing interface: one Session per player.

  brief()            static rules + map + command grammar. Send once (cacheable prompt prefix).
  obs("full")        compact text snapshot of everything the player knows.
  obs("delta")       only the lines that changed since the previous obs() call, plus new events.
  act(text)          run command lines, returns a terse result string.
  query(text)        on-demand detail (map window, unit, path, site, ...): pay tokens only when needed.
  set_script(...)    install a reflex script that runs inside the engine every few ticks.
  obs_json()         full structured state for programmatic bots / baselines.

The design goal is that the per-decision prompt stays small and stable in size no matter how
many units exist: units are aggregated into squads, numbers are bucketed, and unchanged lines are
never re-sent.
"""
import math
import time

from . import data as D
from .mapgen import ascii_map

UNIT_CODES = tuple(D.UNITS)
STRUCT_CODES = tuple(D.STRUCTS)


def _ids(ids):
    """[3,4,5,9] -> '3-5,9'"""
    ids = sorted(ids); out = []; i = 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1: j += 1
        out.append(str(ids[i]) if i == j else "%d-%d" % (ids[i], ids[j]))
        i = j + 1
    return ",".join(out)


def _counts(units):
    c = {}
    for u in units: c[u.type] = c.get(u.type, 0) + 1
    order = {k: i for i, k in enumerate(UNIT_CODES + STRUCT_CODES)}
    return " ".join("%s×%d" % (k, c[k]) for k in sorted(c, key=lambda k: order.get(k, 99)))


def _cluster(units, radius):
    out = []
    for u in sorted(units, key=lambda e: e.id):
        for c in out:
            if (c[0].x - u.x) ** 2 + (c[0].y - u.y) ** 2 <= radius * radius: c.append(u); break
        else: out.append([u])
    return out


class CmdError(Exception):
    pass


class Session:
    def __init__(self, game, pid):
        self.g = game; self.pid = pid; self.p = game.players[pid]
        self._last = {}; self._ev = 0
        self.auto = dict(gather=True, wrk=0, sup=False)
        self.scripts = {}          # name -> dict(fn, every, mem, ms, err)
        self.script_budget_ms = 4.0
        self.stats = dict(cmds=0, errors=0)

    # ================================================================ brief
    def brief(self):
        g, p = self.g, self.p; st = p.stats; ep = g.players[1 - self.pid]
        L = []
        L.append("RIDGELINE. You are P%d, faction %s. Enemy is P%d, faction %s." % (self.pid, p.faction, ep.id, ep.faction))
        L.append(D.FACTIONS[p.faction]["blurb"]); L.append(D.FACTIONS[ep.faction]["blurb"])
        L.append("Time: 10 ticks = 1 s. Map %dx%d tiles, x right, y down. The game does not wait for you." % (g.W, g.H))
        L.append("TERRAIN: levels 0 low, 1 mid, 2 high. Ground units change level only on ramps. "
                 "A unit sees a tile only if the tile is not higher than itself and nothing higher or brush is in between: "
                 "high ground sees down, low ground cannot see up. Ranged shots at a higher target do 75% damage and need vision "
                 "(any ally seeing it counts). Firing reveals the shooter for 2 s. fly ignores terrain and sees everything in range. "
                 "tow sees one level higher than its tile. Terrain is known; enemy units are hidden unless seen.")
        L.append("WIN: destroy all enemy structures. At tick %d the higher army+bank value wins." % g.max_ticks)
        L.append("UNITS code cost/sec/supply hp dmg/cooldown-s range speed sight notes")
        notes = dict(wrk="mines 5 ore per trip, builds", inf="ranged, hits air", hvy="melee, armor %d" % st["hvy"]["armor"],
                     art="min range 2.5, splash, ground only", fly="scout" + (", weak gun" if st["fly"]["dmg"] else ", unarmed"))
        for c in UNIT_CODES:
            s = st[c]
            L.append(" %s %d/%d/%d hp%d %d/%.1f r%g v%.1f s%d %s" % (c, s["cost"], s["time"] // 10, s["sup"], s["hp"], s["dmg"],
                                                                    s["cd"] / 10, s["rng"], s["spd"] * 10, s["sight"], notes[c]))
        L.append("STRUCTURES code cost/sec size hp notes")
        sn = dict(hq="trains wrk, ore drop-off, +12 supply", dep="+8 supply", bar="trains inf hvy",
                  wks="trains art fly, needs bar", tow="defence 12 dmg r7, hits air, needs bar")
        for c in STRUCT_CODES:
            s = st[c]
            L.append(" %s %d/%d %dx%d hp%d %s" % (c, s["cost"], s["time"] // 10, s["size"], s["size"], s["hp"], sn[c]))
        L.append("REGIONS id level center size ore ramps(->neighbour)")
        for r in g.regions:
            links = []
            for rid in r["ramps"]:
                rp = g.ramps[rid]; other = [o for o in rp["link"] if o != r["id"]]
                links.append("r%d@%d,%d>R%s" % (rid, rp["cx"], rp["cy"], other[0] if other else "?"))
            tag = r["tag"].replace("P%d" % self.pid, "your").replace("P%d" % ep.id, "enemy")
            L.append(" R%d L%d %d,%d n%d ore%d %s%s" % (r["id"], r["level"], r["cx"], r["cy"], r["size"], r["ore"],
                                                       " ".join(links), (" [" + tag + "]") if tag else ""))
        L.append("OBSERVATION LINES")
        L.append(" t<tick> ore<bank>+<income per 10s> sup<used>/<cap>")
        L.append(" B <type>#<id> x,y [con0|con50 = under construction, less/more than half] [hp<pct>] [q <queued units>] [rep <unit> = repeating]")
        L.append(" W <n>: mine<n> build<n> idle<n>[ids] other<n>   (your workers)")
        L.append(" A <group|-> <type×n..> @x,y/<region> hp<pct> <order> ids <ids>   (your squads; order ends with ! when fighting)")
        L.append(" E <type×n..> @x,y/<region> hp<pct> ids <ids>   (visible enemy units)   E! <type>#<id> x,y hp<pct> (visible enemy structure)")
        L.append(" M <type>#<id> x,y t<tick last seen>   (remembered enemy structure, not visible now)")
        L.append(" X <tick> <event> | ...   events: ready lost kill attacked contact found warn")
        L.append(" Delta updates repeat only changed lines. '-B#7' / '-M#7' = gone. If any A (or E) line appears, "
                 "all current A (or E) lines are restated; 'A none' / 'E none' = empty.")
        L.append("COMMANDS (one per line; reply with commands only)")
        L.append(" move|amove <sel> <loc>      amove = attack-move")
        L.append(" atk <sel> <enemyId>         hold <sel>      stop <sel>")
        L.append(" gather <sel> [oreId]        default: nearest free patch")
        L.append(" build <struct> <loc>        nearest worker goes; site auto-snaps to a legal spot near loc")
        L.append(" train <structId|structType> <unit> [n]      repeat <structId|structType> <unit|off>  keep producing")
        L.append(" rally <structId|structType> <loc>           cancel <structId>")
        L.append(" group <name> <sel>          name a squad (a-z word); 'group a + <sel>' adds")
        L.append(" auto gather on|off | auto wrk <N> (keep training workers up to N) | auto sup on|off (auto-build dep)")
        L.append(" q <query>                   answered in the reply, e.g. q map 20 40 44 60 | q unit 12 | q near 30 30 6 | "
                 "q path 10 54 54 10 | q site bar 12 50 | q tile 31 31 | q ore | q regions")
        L.append(" <sel> = ids '12,15-20' | group name | unit type | army (all non-workers) | idle (idle workers) | all ; join with ','")
        L.append(" <loc> = 'x y' | R<id> | r<id> (ramp) | #<entityId> | home | enemy (enemy start)")
        return "\n".join(L)

    # ================================================================ observation
    def _order_str(self, e):
        o = e.order; k = o[0]
        if k in ("move", "amove"):
            gx, gy = e.goal or (o[1], o[2]); s = "%s>%d,%d" % (k, gx, gy)   # squad goal, not the unit's formation slot
        elif k == "attack": s = "atk#%d" % o[1]
        else: s = k
        return s

    def _lines(self):
        g, p, pid = self.g, self.p, self.pid
        used, cap = g.supply(pid)
        inc = sum(a for (t, a) in p.income_log if t > g.tick - 100)
        p.income_log = [x for x in p.income_log if x[0] > g.tick - 100]
        L = {}
        L["H"] = "t%d ore%d+%d sup%d/%d" % (g.tick, p.ore, inc, used, cap)
        mine = [e for e in g.ents.values() if e.owner == pid]
        for s in mine:
            if not s.struct: continue
            t = "B %s#%d %d,%d" % (s.type, s.id, s.x, s.y)
            if s.prog < 1.0: t += " con%d" % (int(s.prog * 2) * 50)
            hp = s.hp / s.st["hp"]
            if s.prog >= 1.0 and hp < 0.95: t += " hp%d" % (math.ceil(hp * 10) * 10)
            if s.queue and not (s.repeat and all(u == s.repeat for u in s.queue)):
                qc = {}
                for u in s.queue: qc[u] = qc.get(u, 0) + 1
                t += " q " + ",".join("%s×%d" % kv if kv[1] > 1 else kv[0] for kv in qc.items())
            if s.repeat: t += " rep %s" % s.repeat
            L["B%d" % s.id] = t
        ws = [e for e in mine if e.type == "wrk"]
        if ws:
            c = dict(mine=0, build=0, idle=0, other=0); idle = []
            for w in ws:
                k = w.order[0]
                if k == "gather": c["mine"] += 1
                elif k in ("build", "construct"): c["build"] += 1
                elif k == "idle": c["idle"] += 1; idle.append(w.id)
                else: c["other"] += 1
            t = "W %d: mine%d" % (len(ws), c["mine"])
            if c["build"]: t += " build%d" % c["build"]
            if c["idle"]: t += " idle%d[%s]" % (c["idle"], _ids(idle))
            if c["other"]: t += " other%d" % c["other"]
            L["W"] = t
        army = [e for e in mine if not e.struct and e.type != "wrk"]
        al = []
        buckets = {}
        for e in army:
            o = self._order_str(e)
            buckets.setdefault((e.group or "-", o if e.order[0] != "attack" else "atk"), []).append(e)
        for (label, o) in sorted(buckets):
            for c in _cluster(buckets[(label, o)], 7):
                hp = sum(u.hp for u in c) / sum(u.st["hp"] for u in c)
                cx = sum(u.x for u in c) / len(c); cy = sum(u.y for u in c) / len(c)
                o2 = self._order_str(c[0]) + ("!" if any(u.tgt or u.cd > 0 for u in c) else "")
                al.append("A %s %s @%d,%d/%s hp%d %s ids %s" % (label, _counts(c), cx, cy, g.region_at(cx, cy),
                                                              math.ceil(hp * 10) * 10, o2, _ids([u.id for u in c])))
        L["A"] = "\n".join(al) if al else "A none"
        el = []
        vis = [g.ents[i] for i in p.vis_ents if i in g.ents]
        for c in _cluster([e for e in vis if not e.struct], 4):
            hp = sum(u.hp for u in c) / sum(u.st["hp"] for u in c)
            cx = sum(u.x for u in c) / len(c); cy = sum(u.y for u in c) / len(c)
            el.append("E %s @%d,%d/%s hp%d ids %s" % (_counts(c), cx, cy, g.region_at(cx, cy), math.ceil(hp * 10) * 10,
                                                     _ids([u.id for u in c])))
        for s in sorted((e for e in vis if e.struct), key=lambda e: e.id):
            el.append("E! %s#%d %d,%d hp%d%s" % (s.type, s.id, s.x, s.y, math.ceil(10 * s.hp / s.st["hp"]) * 10,
                                                 " con" if s.prog < 1 else ""))
        L["E"] = "\n".join(el) if el else "E none"
        for sid, m in p.mem.items():
            if sid not in p.vis_ents:
                L["M%d" % sid] = "M %s#%d %d,%d t%d" % (m["type"], sid, m["x"], m["y"], m["t"])
        return L

    def _events(self):
        ev = self.p.events[self._ev:]; self._ev = len(self.p.events)
        if not ev: return None
        # collapse repeats: "ready inf#5 from bar#3" x3 -> one entry per kind where possible
        parts = []; agg = {}
        for (t, kind, text) in ev:
            if kind in ("lost", "kill", "ready"):
                typ = text.split("#")[0]
                if kind == "ready" and "built" in text: parts.append("%d built %s" % (t, text.split(" built")[0])); continue
                a = agg.setdefault(kind, {}); a[typ] = a.get(typ, 0) + 1
            else:
                parts.append("%d %s %s" % (t, kind, text) if kind != "contact" and kind != "found" else "%d %s" % (t, text))
        for kind in ("ready", "lost", "kill"):
            if kind in agg:
                parts.append("%s %s" % (kind, " ".join("%s×%d" % kv for kv in agg[kind].items())))
        return "X " + " | ".join(parts)

    def pending_events(self, kinds=("attacked", "contact", "found", "lost", "warn")):
        return sum(1 for (t, k, x) in self.p.events[self._ev:] if k in kinds)

    def obs(self, mode="delta"):
        L = self._lines(); last = self._last; out = []
        if mode == "full" or not last:
            out.append(L["H"])
            out += [v for k, v in L.items() if k[0] == "B"]
            for k in ("W", "A", "E"):
                if k in L: out.append(L[k])
            out += [v for k, v in L.items() if k[0] == "M"]
        else:
            out.append(L["H"])
            for k, v in L.items():
                if k != "H" and last.get(k) != v: out.append(v)
            for k in last:
                if k not in L and k[0] in "BM": out.append("-%s#%s" % (k[0], k[1:]))
        ev = self._events()
        if ev: out.append(ev)
        if self.g.over:
            out.append("GAME OVER: " + ("draw" if self.g.winner is None else ("you win" if self.g.winner == self.pid else "you lose")))
        self._last = L
        return "\n".join(out)

    def obs_json(self):
        """Verbose structured state (baseline for token comparisons, and for scripted bots)."""
        g, p, pid = self.g, self.p, self.pid
        used, cap = g.supply(pid)

        def ent(e, own):
            d = dict(id=e.id, type=e.type, x=round(e.x, 1), y=round(e.y, 1), hp=round(e.hp), max_hp=e.st["hp"],
                     region=g.region_at(e.x, e.y))
            if own:
                d.update(order=list(e.order), group=e.group, cooldown=e.cd, target=e.tgt)
                if e.struct: d.update(progress=round(e.prog, 2), queue=list(e.queue), repeat=e.repeat)
                if e.type == "wrk": d.update(carry=e.carry)
            else:
                d.update(is_structure=e.struct)
            return d
        return dict(tick=g.tick, ore=p.ore, supply_used=used, supply_cap=cap,
                    own=[ent(e, True) for e in g.ents.values() if e.owner == pid],
                    enemy_visible=[ent(g.ents[i], False) for i in sorted(p.vis_ents) if i in g.ents],
                    enemy_structures_remembered=[dict(id=k, **v) for k, v in p.mem.items() if k not in p.vis_ents],
                    ore_patches=[dict(id=e.id, x=e.tx, y=e.ty, amount=e.amt) for e in g.ents.values() if e.type == "ore"
                                 and p.explored[g.idx(e.tx, e.ty)]])

    # ================================================================ commands
    def _sel(self, tok):
        g, pid = self.g, self.pid; ids = []
        mine = [e for e in g.ents.values() if e.owner == pid]
        for part in tok.split(","):
            part = part.strip().lstrip("#")
            if not part: continue
            if part.isdigit(): ids.append(int(part))
            elif "-" in part and all(x.isdigit() for x in part.split("-", 1)):
                a, b = part.split("-", 1); ids += list(range(int(a), int(b) + 1))
            elif part in UNIT_CODES or part in STRUCT_CODES: ids += [e.id for e in mine if e.type == part]
            elif part == "army": ids += [e.id for e in mine if not e.struct and e.type != "wrk"]
            elif part == "idle": ids += [e.id for e in mine if e.type == "wrk" and e.order[0] == "idle"]
            elif part == "all": ids += [e.id for e in mine if not e.struct]
            elif part in self.p.groups: ids += list(self.p.groups[part])
            else: raise CmdError("bad selector '%s'" % part)
        ids = [i for i in dict.fromkeys(ids) if i in g.ents and g.ents[i].owner == pid]
        if not ids: raise CmdError("selector '%s' matches nothing" % tok)
        return ids

    def _loc(self, toks):
        """Consume a location from the token list; returns (x, y)."""
        g = self.g
        if not toks: raise CmdError("missing location")
        t = toks.pop(0)
        try:
            if "," in t:
                a, b = t.split(","); return float(a), float(b)
            if t[0] == "R" and t[1:].isdigit():
                r = g.regions[int(t[1:])]; return r["cx"] + 0.5, r["cy"] + 0.5
            if t[0] == "r" and t[1:].isdigit():
                r = g.ramps[int(t[1:])]; return r["cx"] + 0.5, r["cy"] + 0.5
            if t[0] == "#":
                e = g.ents[int(t[1:])]
                if e.owner != self.pid and e.owner >= 0 and not g.visible(self.pid, e):
                    m = self.p.mem.get(e.id)
                    if not m: raise CmdError("entity %s not known" % t)
                    return m["x"] + 0.5, m["y"] + 0.5
                return e.x, e.y
            if t in ("home", "enemy"):
                pid = self.pid if t == "home" else 1 - self.pid
                sx, sy = g.map.starts[pid]; return sx + 1.5, sy + 1.5
            x = float(t); y = float(toks.pop(0)); return x, y
        except CmdError: raise
        except Exception:
            raise CmdError("bad location '%s'" % t)

    def _structs(self, tok, need_done=True):
        g = self.g; tok = tok.lstrip("#")
        if tok.isdigit():
            e = g.ents.get(int(tok))
            if e is None or e.owner != self.pid or not e.struct: raise CmdError("no structure #%s" % tok)
            return [e]
        if tok in STRUCT_CODES:
            ss = [e for e in g.ents.values() if e.owner == self.pid and e.type == tok and (e.prog >= 1 or not need_done)]
            if not ss: raise CmdError("you have no finished %s" % tok)
            return ss
        raise CmdError("bad structure '%s'" % tok)

    def act(self, text):
        """Execute command lines. Returns a terse report: 'ok N' plus one 'E<line> <reason>' per failure."""
        ok = 0; out = []; n = 0
        for raw in text.replace(";", "\n").split("\n"):
            line = raw.strip().strip("`").strip()
            if not line or line.startswith(("#", "//")): continue
            n += 1; self.stats["cmds"] += 1
            try:
                r = self._one(line)
                if r: out.append(r)
                else: ok += 1
            except CmdError as ex:
                self.stats["errors"] += 1; out.append("E%d %s: %s" % (n, line.split()[0], ex))
            except Exception as ex:  # never let a malformed line crash the game
                self.stats["errors"] += 1; out.append("E%d %s: bad syntax (%s)" % (n, line.split()[0], type(ex).__name__))
        return "\n".join((["ok %d" % ok] if ok else []) + out) or "no commands"

    def _one(self, line):
        g, pid = self.g, self.pid
        toks = line.split(); verb = toks.pop(0).lower()
        if verb == "q": return self.query(" ".join(toks))
        if verb in ("move", "amove"):
            ids = self._sel(toks.pop(0)); x, y = self._loc(toks)
            err = g.order_units(pid, ids, (verb, x, y))
        elif verb in ("atk", "attack"):
            ids = self._sel(toks.pop(0)); tid = int(toks.pop(0).lstrip("#"))
            err = g.order_units(pid, ids, ("attack", tid))
        elif verb in ("hold", "stop"):
            err = g.order_units(pid, self._sel(toks.pop(0)), (verb,))
        elif verb == "gather":
            ids = self._sel(toks.pop(0)); err = None
            if toks:
                err = g.order_units(pid, ids, ("gather", int(toks[0].lstrip("#"))))
            else:
                for i in ids:
                    e = g.ents[i]; hq = g._nearest_hq(e) or e
                    o = g.nearest_ore(hq.x, hq.y, 14, count_workers=True) or g.nearest_ore(e.x, e.y, count_workers=True)
                    if o is None: raise CmdError("no ore left")
                    err = g.order_units(pid, [i], ("gather", o.id)) or err
        elif verb == "build":
            code = toks.pop(0)
            if code not in STRUCT_CODES: raise CmdError("unknown structure '%s' (%s)" % (code, " ".join(STRUCT_CODES)))
            x, y = self._loc(toks)
            wid = None
            if toks and toks[0] == "by": wid = int(toks[1].lstrip("#"))
            site = g.find_site(pid, code, x, y)
            if site is None: raise CmdError("no legal site near %d,%d (try q site %s x y)" % (x, y, code))
            if wid is None:
                ws = [e for e in g.ents.values() if e.owner == pid and e.type == "wrk" and e.order[0] in ("idle", "gather", "move")]
                if not ws: raise CmdError("no free worker")
                wid = min(ws, key=lambda e: (e.x - x) ** 2 + (e.y - y) ** 2 + (0 if e.order[0] == "idle" else 9) + (25 if e.carry else 0)).id
            err = g.order_build(pid, wid, code, site[0], site[1])
        elif verb == "train":
            ss = self._structs(toks.pop(0)); u = toks.pop(0); n = int(toks[0]) if toks else 1
            if u not in UNIT_CODES: raise CmdError("unknown unit '%s'" % u)
            err = None; done = 0
            for _ in range(n):
                s = min(ss, key=lambda s: len(s.queue))
                err = g.order_train(pid, s.id, u)
                if err: break
                done += 1
            if err and done: err = "%d/%d queued, then: %s" % (done, n, err)
        elif verb == "repeat":
            ss = self._structs(toks.pop(0)); u = toks.pop(0)
            if u != "off" and any(u not in s.st["trains"] for s in ss): raise CmdError("cannot train %s there" % u)
            for s in ss: s.repeat = None if u == "off" else u
            err = None
        elif verb == "rally":
            ss = self._structs(toks.pop(0)); x, y = self._loc(toks)
            for s in ss: s.rally = (x, y)
            err = None
        elif verb == "cancel":
            err = None
            for s in self._structs(toks.pop(0)): err = g.order_cancel(pid, s.id) or err
        elif verb == "group":
            name = toks.pop(0); add = False
            if toks and toks[0] in ("+", "="): add = toks.pop(0) == "+"
            if not name.isalpha() or name in UNIT_CODES + STRUCT_CODES + ("army", "idle", "all"): raise CmdError("bad group name")
            ids = [i for i in self._sel(",".join(toks)) if not g.ents[i].struct]
            for gn, s in self.p.groups.items(): s.difference_update(ids)
            cur = self.p.groups.setdefault(name, set())
            if not add:
                for i in cur:
                    if i in g.ents: g.ents[i].group = ""
                cur.clear()
            cur.update(ids)
            for i in ids: g.ents[i].group = name
            err = None
        elif verb == "auto":
            k = toks.pop(0); v = toks.pop(0) if toks else "on"
            if k == "wrk": self.auto["wrk"] = int(v) if v.isdigit() else (0 if v == "off" else 16)
            elif k in ("gather", "sup"): self.auto[k] = v != "off"
            else: raise CmdError("auto gather|wrk|sup")
            err = None
        else:
            raise CmdError("unknown command")
        if err: self.stats["errors"] += 1; raise CmdError(err)
        return None

    # ================================================================ queries
    def query(self, text):
        g, p, pid = self.g, self.p, self.pid
        toks = text.split()
        if not toks: return "q map|unit|near|path|site|tile|ore|regions|stats"
        k = toks.pop(0)
        try:
            if k == "map":
                x0, y0, x1, y1 = (int(float(t)) for t in toks[:4]) if len(toks) >= 4 else (0, 0, g.W - 1, g.H - 1)
                x0, y0 = max(0, x0), max(0, y0); x1, y1 = min(g.W - 1, x1), min(g.H - 1, y1)
                ov = {}
                for e in g.ents.values():
                    if e.type == "ore":
                        continue
                    if e.owner == pid or e.id in p.vis_ents:
                        ch = (e.type[0].upper() if e.struct else e.type[0]) if e.owner == pid else ("X" if e.struct else "x")
                        if e.size:
                            for t in g._foot(e.tx, e.ty, e.size): ov[t] = ch
                        else: ov.setdefault(g.idx(int(e.x), int(e.y)), ch)
                return ("map %d,%d-%d,%d  . : ^ = level 0 1 2, / ramp, \" brush, # rock, $ ore, UPPER your structure, "
                        "lower your unit, X/x enemy\n" % (x0, y0, x1, y1)) + ascii_map(g.map, x0, y0, x1, y1, ov)
            if k == "unit":
                e = g.ents.get(int(toks[0].lstrip("#")))
                if e is None or (e.owner != pid and e.id not in p.vis_ents): return "unit: not visible"
                s = "%s#%d P%d %.1f,%.1f/%s hp%d/%d" % (e.type, e.id, e.owner, e.x, e.y, g.region_at(e.x, e.y), e.hp, e.st["hp"])
                if e.owner == pid:
                    s += " order=%s" % " ".join(str(int(v) if isinstance(v, float) else v) for v in e.order)
                    if e.group: s += " group=%s" % e.group
                    if e.queue: s += " queue=%s" % ",".join(e.queue)
                    if e.carry: s += " carry=%d" % e.carry
                return s
            if k == "near":
                x, y = float(toks[0]), float(toks[1]); r = float(toks[2]) if len(toks) > 2 else 6
                out = []
                for e in g.ents.values():
                    if (e.x - x) ** 2 + (e.y - y) ** 2 > r * r: continue
                    if e.type == "ore": out.append("ore#%d %d,%d left%d" % (e.id, e.x, e.y, e.amt))
                    elif e.owner == pid: out.append("%s#%d %d,%d hp%d %s" % (e.type, e.id, e.x, e.y, e.hp, e.order[0]))
                    elif e.id in p.vis_ents: out.append("ENEMY %s#%d %d,%d hp%d" % (e.type, e.id, e.x, e.y, e.hp))
                return "near %d,%d r%g: " % (x, y, r) + ("; ".join(out) if out else "nothing known")
            if k == "path":
                x1, y1, x2, y2 = (int(float(t)) for t in toks[:4])
                a = g.idx(x1, y1); b = g.idx(x2, y2)
                if g.occ[a] or g.block[a]: a = g._free_tile_near(x1, y1)
                if g.occ[b] or g.block[b]: b = g._free_tile_near(x2, y2)
                f = g.field((b,)); d = f[a]
                if d == float("inf"): return "path: unreachable by ground"
                # walk the field to list the ramps crossed
                t = a; seq = []
                for _ in range(400):
                    if g.ramp[t]:
                        tag = "r%d" % g.ramp_id[t]
                        if not seq or seq[-1] != tag: seq.append(tag)
                    elif g.region[t] >= 0:
                        tag = "R%d" % g.region[t]
                        if not seq or seq[-1] != tag: seq.append(tag)
                    nb = [(f[n], n) for n, c, o1, o2 in g.nbrs[t] if f[n] < f[t]]
                    if not nb: break
                    t = min(nb)[1]
                return "path %.0f tiles (inf %.0fs, hvy %.0fs, art %.0fs) via %s" % (
                    d, d / p.stats["inf"]["spd"] / 10, d / p.stats["hvy"]["spd"] / 10, d / p.stats["art"]["spd"] / 10, " ".join(seq))
            if k == "site":
                code = toks[0]; x, y = float(toks[1]), float(toks[2])
                s = g.find_site(pid, code, x, y, 8)
                return "site %s: %s" % (code, "none within 8" if s is None else "%d,%d (top-left), level %d" % (s[0], s[1], g.level[g.idx(*s)]))
            if k == "tile":
                x, y = int(float(toks[0])), int(float(toks[1])); t = g.idx(x, y)
                kind = "rock" if g.block[t] else ("ramp" if g.ramp[t] else ("brush" if g.brush[t] else "open"))
                return "tile %d,%d %s L%d %s %s%s" % (x, y, g.region_at(x, y), g.level[t], kind,
                                                     "visible" if p.vis[t] else ("explored" if p.explored[t] else "unexplored"),
                                                     " occupied" if g.occ[t] else "")
            if k == "ore":
                out = {}
                for e in g.ents.values():
                    if e.type == "ore": out.setdefault(g.region_at(e.x, e.y), []).append(e)
                res = []
                for r, v in sorted(out.items()):
                    seen = [o for o in v if p.vis[g.idx(o.tx, o.ty)]]      # amounts only for patches you can see now
                    res.append("%s %d patches%s (ids %s)" % (r, len(v), " %d left" % sum(o.amt for o in seen) if len(seen) == len(v)
                                                              else " ?", _ids([o.id for o in v])))
                return "ore: " + "; ".join(res)
            if k == "regions":
                return "\n".join(l for l in self.brief().split("\n") if l.startswith(" R"))
            if k == "stats":
                s = p.stats[toks[0]]
                return "stats %s: %s" % (toks[0], " ".join("%s=%s" % kv for kv in s.items() if kv[0] not in ("struct", "code")))
        except (IndexError, ValueError, KeyError):
            return "q %s: bad arguments" % k
        return "q: unknown query '%s'" % k

    # ================================================================ automation (runs inside the engine loop)
    def set_script(self, name, code, every=5):
        """Install a reflex script: python source defining tick(api). Runs every `every` ticks at engine speed.
        api: .t .ore .sup .units .enemies .mem (dict that persists) .cmd(line) .q(query) .dist(a,b)"""
        if not code or not code.strip():
            self.scripts.pop(name, None); return "script %s removed" % name
        safe = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k) for k in (
            "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "len", "list", "map", "max", "min",
            "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip", "isinstance", "print")}
        env = {"__builtins__": safe, "math": math}
        try:
            exec(compile(code, "<script %s>" % name, "exec"), env)
        except Exception as ex:
            return "script error: %s: %s" % (type(ex).__name__, ex)
        if not callable(env.get("tick")): return "script error: define tick(api)"
        self.scripts[name] = dict(fn=env["tick"], every=max(1, int(every)), mem={}, ms=0.0, calls=0, err=None)
        return "script %s installed (every %d ticks)" % (name, every)

    def pre_tick(self):
        g = self.g
        if g.over: return
        if g.tick % 10 == self.pid: self._auto()
        for name, sc in list(self.scripts.items()):
            if g.tick % sc["every"]: continue
            api = _Api(self, sc["mem"]); t0 = time.perf_counter()
            try: sc["fn"](api)
            except Exception as ex:
                sc["err"] = "%s: %s" % (type(ex).__name__, ex)
                g.event(self.pid, "warn", "script %s crashed: %s" % (name, sc["err"]), key=("script", name), gap=300)
            dt = (time.perf_counter() - t0) * 1000; sc["ms"] += dt; sc["calls"] += 1
            if sc["calls"] > 20 and sc["ms"] / sc["calls"] > self.script_budget_ms:
                del self.scripts[name]
                g.event(self.pid, "warn", "script %s removed: over %.0fms budget" % (name, self.script_budget_ms))

    def _auto(self):
        g, pid, p = self.g, self.pid, self.p
        mine = [e for e in g.ents.values() if e.owner == pid]
        if self.auto["gather"]:
            for e in mine:
                if e.type == "wrk" and e.order[0] == "idle" and g.tick - e.born > 5:
                    hq = g._nearest_hq(e)
                    if hq is None: break
                    o = g.nearest_ore(hq.x, hq.y, 14, count_workers=True)
                    if o is None: break
                    g.order_units(pid, [e.id], ("gather", o.id))
        if self.auto["wrk"]:
            n = sum(1 for e in mine if e.type == "wrk") + sum(s.queue.count("wrk") for s in mine if s.struct)
            for s in mine:
                if s.type == "hq" and s.prog >= 1 and not s.queue and n < self.auto["wrk"]:
                    if g.order_train(pid, s.id, "wrk") is None: n += 1
        if self.auto["sup"]:
            used, cap = g.supply(pid)
            pending = sum(1 for e in mine if (e.type == "dep" and e.prog < 1) or (e.order[0] == "build" and e.order[1] == "dep"))
            if cap - used <= 3 and not pending and p.ore >= p.stats["dep"]["cost"]:
                hq = next((s for s in mine if s.type == "hq"), None)
                if hq: self.act("build dep %d %d" % (hq.x, hq.y))


class _Api:
    """What a reflex script can see and do. Snapshots are plain dicts so scripts cannot touch engine state."""

    def __init__(self, sess, mem):
        g = sess.g; self._s = sess; self.mem = mem; self.t = g.tick; self.ore = sess.p.ore; self.sup = g.supply(sess.pid)
        self.units = [dict(id=e.id, type=e.type, x=e.x, y=e.y, hp=e.hp, max_hp=e.st["hp"], order=e.order[0], cd=e.cd,
                           group=e.group, struct=e.struct, queue=len(e.queue), rng=e.st.get("rng", 0),
                           level=g.vis_h[g.idx(int(e.x), int(e.y))])
                      for e in g.ents.values() if e.owner == sess.pid]
        self.enemies = [dict(id=e.id, type=e.type, x=e.x, y=e.y, hp=e.hp, max_hp=e.st["hp"], struct=e.struct,
                             rng=e.st.get("rng", 0), dmg=e.st.get("dmg", 0), level=g.vis_h[g.idx(int(e.x), int(e.y))])
                        for e in (g.ents.get(i) for i in sess.p.vis_ents) if e is not None]

    def cmd(self, line): return self._s.act(line)
    def q(self, text): return self._s.query(text)

    @staticmethod
    def dist(a, b):
        """Distance between two things, each a unit dict or an (x, y) pair."""
        ax, ay = (a["x"], a["y"]) if isinstance(a, dict) else a
        bx, by = (b["x"], b["y"]) if isinstance(b, dict) else b
        return math.hypot(ax - bx, ay - by)
