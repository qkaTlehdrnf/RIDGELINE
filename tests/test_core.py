"""Run: python tests/test_core.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline.engine import Game, small_game
from ridgeline.iface import Session, PolicyApi
from ridgeline.match import run_match
from ridgeline.mapgen import gen_map
from ridgeline import render


def test_random_asymmetric_start():
    gm = lambda s: gen_map(s, 126, 78, 22, 14, players=2)
    a, b = gm(1), gm(2)
    assert a.cell != b.cell and a.capitals != b.capitals, "different seeds give different maps"
    assert gm(1).cell == a.cell and gm(1).start_units == a.start_units, "same seed reproduces"
    diff = sum(1 for s in range(12) for m in [gm(s)] if len(m.start_provs[0]) != len(m.start_provs[1])
               or len(m.start_units[0]) != len(m.start_units[1]))
    assert diff >= 8, "starts should usually be unequal (%d/12)" % diff


def test_territory_income_and_supply():
    g = small_game(3); p = g.players[0]
    for u in list(g.units.values()): g._die(u, None)
    own = [i for i in range(g.n) if g.owner[i] == 0]
    g.step(); base = p.income
    assert base == sum(g.provs[i].y for i in own) and base > 0, "income = yield of supplied provinces"
    # walk a unit into a neutral neighbour: income rises
    cap = p.capital; tgt = next(b for i in own for b in g.provs[i].nbrs if g.owner[b] == -1)
    src = next(i for i in own if tgt in g.provs[i].nbrs)
    u = g.spawn(0, "inf", src); g.order_move(0, [u.id], tgt)
    for _ in range(80): g.step()
    assert g.owner[tgt] == 0 and p.income == base + g.provs[tgt].y
    # cut it off: give every province between it and the capital to nobody
    for i in own:
        if i != cap: g.owner[i] = -1
    g._own_dirty = True; g.step(); g.step()
    if cap not in g.provs[tgt].nbrs:
        assert tgt not in p.supplied and p.income == g.provs[cap].y, "cut-off provinces pay nothing"
        s0 = u.str
        for _ in range(10): g.step()
        if not any(b in p.supplied for b in g.provs[u.prov].nbrs): assert u.str < s0, "out-of-supply attrition"


def test_battle_and_capture():
    g = small_game(3)
    for u in list(g.units.values()): g._die(u, None)
    a = g.players[0].capital; b = g.provs[a].nbrs[0]; g.owner[b] = 1; g._own_dirty = True
    d = g.spawn(1, "inf", b); att = [g.spawn(0, "inf", a) for _ in range(3)]
    assert g.order_move(0, [u.id for u in att], b) is None
    for _ in range(400): g.step()
    assert g.owner[b] == 0 and all(u.prov == b for u in att if u.id in g.units), "attackers advance after winning"


def test_forts_and_manpower():
    g = small_game(3); p = g.players[0]
    for u in list(g.units.values()): g._die(u, None)
    a = p.capital; b = next(x for x in g.provs[a].nbrs); g.owner[b] = 1; g._own_dirty = True
    d = [g.spawn(1, "inf", b) for _ in range(2)]; eng = g.spawn(1, "eng", b)
    assert g.order_fortify(1, [u.id for u in d] + [eng.id]) is None
    for _ in range(200): g.step()
    assert g.fort_level(b) >= 2, "engineers and infantry dig in over time (level %d)" % g.fort_level(b)
    # the same attack hurts a fortified defender less
    def loss(fort):
        h = small_game(3)
        for u in list(h.units.values()): h._die(u, None)
        h.owner[b] = 1; h.fort[b] = fort; dd = h.spawn(1, "inf", b); at = [h.spawn(0, "inf", a) for _ in range(3)]
        h.order_move(0, [u.id for u in at], b)
        for _ in range(30): h.step()
        return 100 - dd.str
    assert loss(3.0) < loss(0.0) * 0.7, (loss(3.0), loss(0.0))
    # manpower: recruiting needs it, and it is spent
    p.res = 1000; p.mp = 5
    assert "manpower" in g.order_recruit(0, "inf")
    p.mp = 100; assert g.order_recruit(0, "inf") is None and p.mp == 100 - p.stats["inf"]["mp"]


def test_fog_and_estimates():
    g = small_game(5); s = Session(g, 0); p = g.players[0]
    ecap = g.players[1].capital
    assert ecap not in p.visible and not p.known_caps, "enemy capital starts unknown"
    assert "enemy capital not found" in s.act("move all enemy")
    far = [i for i in range(g.n) if g.owner[i] == 1]
    assert all(g.estimate(0, i) is None for i in far if i not in p.visible)


def test_delta_commands_policy():
    g = small_game(1); s = Session(g, 0)
    full = s.obs("full"); assert full.startswith("t0 res")
    r = s.act("recruit inf\nbogus 1\nmove all P999\nhold all")
    assert "ok 2" in r and "E2 bogus" in r and "E3 move" in r, r
    g.step(); d = s.obs(); assert d.count("\n") <= 2, d
    assert "installed" in s.set_policy("p", "def tick(api):\n    api.mem['n'] = api.mem.get('n', 0) + 1\n", 1)
    assert "error" in s.set_policy("bad", "import os\ndef tick(api): pass")
    for _ in range(5): s.pre_tick(); g.step()
    assert s.policies["p"]["mem"]["n"] == 5


def test_render_protocol_and_determinism():
    g = small_game(2); sc = render.scene(g); fr = render.frame(g)
    assert len(sc["cells"]) == sc["gw"] * sc["gh"] and len(fr["owner"]) == len(sc["provs"]) == len(fr["fort"]) and len(fr["units"][0]) == 19 and len(fr["stock"]) == len(fr["owner"])
    terr = [p["terrain"] for p in sc["provs"]]
    assert len(terr) >= 280 and terr.count("water") >= 20 and terr.count("mountain") >= 10, "big map with sea and mountains"
    D2 = dict(factions=('aurum', 'sable'), size='small')
    a = run_match(seed=2, max_ticks=600, **D2); b = run_match(seed=2, max_ticks=600, **D2)
    a.pop('policy_ms'); b.pop('policy_ms')          # wall-clock timing, not game state
    assert a == b, (a, b)


def test_preparation_frontage_and_battle_log():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
    from scenario import run
    kw = dict(att={"inf": 9, "art": 3, "arm": 3}, dfd={"inf": 5}, fort=2, terrain="plain")
    worn = run(rdy=30, prep=0, **kw); log = []; planned = run(rdy=100, prep=48, log=log, **kw)
    assert planned[0] and planned[2] < worn[2] / 2, ("a rested, planned 3:1 attack takes the trench far more cheaply", worn, planned)
    assert not run(att={"inf": 10}, dfd={"inf": 5}, fort=2, terrain="hill", rdy=30)[0], "a worn 2:1 rush at a hill trench fails"
    # frontage: doubling the infantry on one direction adds little; a second direction adds a lot
    one = run(att={"inf": 12}, dfd={"inf": 6}, fort=1, terrain="hill", hours=150)
    two = run(att={"inf": 12}, dfd={"inf": 6}, fort=1, terrain="hill", hours=150, dirs=2)
    assert two[3] < one[3] or (two[0] and two[1] < one[1]), (one, two)
    ep = log[-1]
    assert ep["won"] == 1 and ep["att_bonus"] >= 40 and ep["att_rdy"] >= 90 and ep["fort"] == 2 and ep["att_types"]["art"] == 3, ep


def test_three_factions_big_map_four_heights():
    g = Game(seed=4); m = g.map
    land = [p for p in g.provs if p.terrain != "water"]
    assert len(g.players) == 3 and len(set(m.capitals)) == 3 and len(g.provs) == 88 * 56 and len(land) > 3000
    assert sorted(set(p.elev for p in land)) == [0, 1, 2, 3], "four height levels"
    assert all(p.elev == 3 for p in land if p.terrain == "mountain") and any(p.elev == 1 for p in land if p.terrain == "plain")
    lo = next(p for p in land if p.elev == 0 and any(g.provs[b].elev == 3 for b in p.nbrs)); hi = next(b for b in lo.nbrs if g.provs[b].elev == 3)
    u = g.spawn(0, "inf", lo.id); up = g._atk(u, lo.id, hi); u2 = g.spawn(0, "inf", hi); down = g._atk(u2, hi, lo.id)
    assert down > up * 1.5, "three levels of height difference matter a lot"
    s = Session(g, 0); b = s.brief()
    assert "P1 (sable)" in b and "P2 (cinder)" in b and len(b) < 60000, len(b)
    assert g.sight_from(hi, 1 + 3) > g.sight_from(hi, 1), "height adds sight"
    # capitulation: when a capital falls the faction is out and its land passes to the captor
    cap = g.players[2].capital
    for x in list(g.pos[cap]): g._die(x, None)
    g.owner[cap] = 0; g._own_dirty = True; g._check_end()
    assert not g.players[2].alive and g.owner.count(2) == 0 and not any(x.owner == 2 for x in g.units.values()) and not g.over
    api = PolicyApi(s, {}); assert api.players == 3 and all(v["who"] != 2 for v in api.provs.values())


def test_commander_trials_strategies_without_touching_the_war():
    from ridgeline import wargame
    g = small_game(3); ss = [Session(g, 0), Session(g, 1)]
    basic = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "policies", "basic.py")).read()
    for s in ss: s.set_policy("main", basic)
    for _ in range(500):
        for s in ss: s.pre_tick()
        g.step()
    s = ss[0]; before = (g.tick, list(g.owner), sorted((u.id, u.prov, round(u.str, 3)) for u in g.units.values()), g.rng.getstate())
    b, _ = wargame.belief_game(s)
    hidden = [u for u in g.units.values() if u.owner == 1 and u.prov not in s.p.visible]
    assert hidden and not any(b.pos[u.prov] for u in hidden), "the forecast holds no enemy unit the commander cannot see"
    assert sum(1 for u in b.units.values() if u.owner == 0) == sum(1 for u in g.units.values() if u.owner == 0)
    assert "stored" in s.set_candidate("turtle", "def tick(api):\n    api.cmd('fortify all')\n")
    r = s.act("trial 48 current turtle evolved nosuch")
    assert r.count("provinces") == 3 and "nosuch: unknown" in r and "turtle: provinces +" in r, r
    assert before == (g.tick, list(g.owner), sorted((u.id, u.prov, round(u.str, 3)) for u in g.units.values()), g.rng.getstate()), "the real war is untouched"
    assert "adopted turtle" in s.act("adopt turtle") and s.sources["main"][0].startswith("def tick")


def test_units_move_freely_and_key_point_decides_ownership():
    import ridgeline.data as D
    g = small_game(3)
    for u in list(g.units.values()): g._die(u, None)
    a = g.players[0].capital; b = next(n for n in g.provs[a].nbrs if g.provs[n].terrain != "water")
    for i in range(g.n): g.owner[i] = -1
    g.owner[a] = 0; g.owner[b] = 1; g._own_dirty = True; g.players[1].capital = b; g.players[1].mp = g.players[0].mp = 1e6
    A = g.provs[a]; Bp = g.provs[b]
    us = [g.spawn(0, "inf", a) for _ in range(12)]
    assert len(set((round(u.x, 2), round(u.y, 2)) for u in us)) == 12, "a group takes up room: no two units on one spot"
    scout = us[0]; g.order_move(0, [scout.id], b); seen = set()
    for _ in range(60):
        g.step(); seen.add((round(scout.x, 1), round(scout.y, 1)))
        if scout.prov == b and g.owner[b] == 1:
            d = ((scout.x - Bp.cx) ** 2 + (scout.y - Bp.cy) ** 2) ** 0.5
            assert d > D.CAP_R, "being inside the province is not enough"
        if g.owner[b] == 0: break
    assert len(seen) > 8 and g.owner[b] == 0 and ((scout.x - Bp.cx) ** 2 + (scout.y - Bp.cy) ** 2) ** 0.5 <= D.CAP_R, "taken at the key point"
    # artillery outranges infantry: it hurts a defender on the next key point without being hit back
    g.owner[b] = 1; g._own_dirty = True; g.order_move(0, [scout.id], a)
    for _ in range(40): g.step()
    for u in us: g._die(u, None)
    d = g.spawn(1, "inf", b); art = g.spawn(0, "art", a); art.x = Bp.cx + (A.cx - Bp.cx) * 0.9 * D.RANGE["art"] / max(D.RANGE["art"], ((A.cx - Bp.cx) ** 2 + (A.cy - Bp.cy) ** 2) ** 0.5)
    art.y = Bp.cy + (A.cy - Bp.cy) * 0.9 * D.RANGE["art"] / max(D.RANGE["art"], ((A.cx - Bp.cx) ** 2 + (A.cy - Bp.cy) ** 2) ** 0.5); art.ox = art.x - A.cx; art.oy = art.y - A.cy
    s0 = d.str; g._combat()
    assert d.str == s0 and not art.fighting, "a front where nobody advances or prepares stays quiet"
    g.order_prepare(0, [art.id], b); g._combat()
    assert d.str < s0 and art.str == 100 and art.fighting == 2 and d.fighting == 2, (d.str, art.str)



def test_fog_is_per_faction_and_scouts_explore_but_cannot_capture():
    import re
    from ridgeline.wargame import belief_game
    g = Game(seed=5, gmap=gen_map(5, 252, 156, 44, 28, 3)); ss = [Session(g, i) for i in range(3)]
    land = sum(1 for pr in g.provs if pr.terrain != "water")
    for s in ss: s.brief()
    def audit():
        for s in ss:
            p = s.p; ex = p.explored; api = PolicyApi(s, {})
            assert p.visible <= ex and set(api.provs) <= ex
            assert all(i in p.visible for i in api.enemy)
            for e in g.players:                                     # another side's capital is known only once seen
                if e.id != s.pid and e.capital not in ex: assert e.id not in p.known_caps
            txt = s.brief() + "\n" + s.obs("full") + "\n" + s.query("enemy") + "\n" + s.query("front") + "\n" + s.query("near P%d 6" % p.capital)
            ids = set(int(x) for x in re.findall(r"\bP(\d+)", txt)) - {0, 1, 2}        # P0..P2 also name the players
            ok = set(ex)
            for i in ex: ok.update(g.provs[i].nbrs)                 # neighbours of known land are named, nothing more
            assert ids <= ok, sorted(ids - ok)[:5]
            for i in range(g.n):                                    # hidden enemy units appear nowhere
                if i not in p.visible and any(u.owner != s.pid for u in g.pos[i]):
                    assert g.estimate(s.pid, i) is None
            far = next(i for i in range(g.n) if i not in ok and g.provs[i].terrain != "water")
            assert "unexplored" in s.act("move all P%d" % far) and "unexplored" in s.query("prov %d" % far)
            assert api.path(p.capital, far) is None
            bg, _ = belief_game(s)                                  # the staff wargame holds no hidden enemy either
            assert all(u.owner == s.pid or u.prov in p.visible for u in bg.units.values())
    audit()
    assert all(len(s.p.explored) < land // 3 for s in ss)          # at the start each side knows only its own corner
    a = ss[0]; cap = a.p.capital
    assert "ok" in a.act("recruit rec 2"); n0 = len(a.p.explored)
    for _ in range(40): [s.pre_tick() for s in ss]; g.step()
    recs = [u for u in g.units.values() if u.owner == 0 and u.type == "rec"]; assert len(recs) >= 2
    assert recs[0].st["spd"] > max(v["spd"] for k, v in a.p.stats.items() if k != "rec")       # the fastest unit
    out = a.act("expand rec"); assert "explore" in out and recs[0].id in a.explore and recs[0].id not in a.expand
    own0 = g.owner.count(0); crossed = set()
    for _ in range(120):
        [s.pre_tick() for s in ss]; g.step()
        for u in recs:
            if u.id in g.units and g.owner[u.prov] != 0: crossed.add(u.prov)
    assert len(a.p.explored) > n0 + 40, (n0, len(a.p.explored))    # they opened up the map ...
    assert crossed and all(g.owner[i] != 0 for i in crossed) and g.owner.count(0) == own0      # ... without taking any of it
    audit()
    tgt = max((i for i in a.p.explored if g.owner[i] == -1 and g.provs[i].terrain != "water" and i in crossed), key=lambda i: g.provs[i].y)
    assert "ok" in a.act("expand inf P%d" % tgt)                   # the commander picks the land: infantry takes it
    for _ in range(200):
        [s.pre_tick() for s in ss]; g.step()
        if g.owner[tgt] == 0: break
    assert g.owner[tgt] == 0
    audit()


def test_unit_state_experience_morale_suppression_formations():
    from ridgeline import data as D
    g = small_game(seed=3, max_ticks=10 ** 6)
    for u in list(g.units.values()): g._die(u, None)
    a = g.players[0].capital; b = next(x for x in g.provs[a].nbrs if g.provs[x].terrain == "plain" or True)
    for i in range(g.n): g.owner[i] = -1
    rear = next(x for x in g.provs[b].nbrs if x != a and x not in g.provs[a].nbrs)
    g.owner[a] = 0; g.owner[b] = 1; g.owner[rear] = 1; g._own_dirty = True; g.players[1].capital = rear; g.players[0].mp = g.players[1].mp = 1e6; g._supply()
    green = g.spawn(0, "inf", a); vet = g.spawn(0, "inf", a); vet.xp = 85.0
    assert g._atk(vet, a, b) > g._atk(green, a, b) * 1.25                         # experience tells
    shaky = g.spawn(0, "inf", a); shaky.mor = 20.0
    assert g._atk(shaky, a, b) < g._atk(green, a, b)                              # so does morale
    assert g.state(shaky) == "shaken" and g.state(green) == "ready"
    # replacements dilute experience
    vet.str = 40.0
    for _ in range(120): g.step()
    assert vet.str > 60 and vet.xp < 70, (vet.str, vet.xp)
    assert green.xp > 10                                                          # drill at home, slowly
    # a fight: experience grows, morale falls with losses, fire suppresses, a unit whose morale goes runs with men left
    s = Session(g, 0); ids = [g.spawn(0, "inf", a).id for _ in range(8)]
    assert s.act("group storm %s" % ",".join(map(str, ids))).startswith("ok")
    dfd = [g.spawn(1, "inf", b) for _ in range(3)]; coward = g.spawn(1, "inf", b); coward.mor = 16.0
    x0 = [g.units[i].xp for i in ids]; m0 = [d.mor for d in dfd]
    g.order_move(0, ids, b); seen_sup = False; ran = False
    for _ in range(60):
        g.step(); seen_sup = seen_sup or any(d.sup > 5 for d in dfd if d.id in g.units)
        ran = ran or (coward.id in g.units and coward.rout and coward.str > D.RETREAT_AT)
        if g.owner[b] == 0: break
    live = [g.units[i] for i in ids if i in g.units]
    assert live and all(u.hours > 0 for u in live) and sum(u.xp for u in live) / len(live) > sum(x0) / len(x0)
    assert seen_sup, 'no suppression seen'
    assert ran, 'the shaky unit never broke'
    assert any(d.id not in g.units or d.mor < m for d, m in zip(dfd, m0))
    # the formation that fought together has formation experience; newcomers dilute it
    fx = g.players[0].fxp.get("storm", 0); assert fx > 0, g.players[0].fxp
    more = [g.spawn(0, "inf", a).id for _ in range(len(live))]
    s.act("group storm + %s" % ",".join(map(str, more)))
    assert abs(g.players[0].fxp["storm"] - fx / 2) < fx * 0.15
    assert PolicyApi(s, {}).formations["storm"] > 0 and all(k in PolicyApi(s, {}).units[0] for k in ("xp", "mor", "sup", "state"))
    # cut off and broken: surrender
    lone = g.spawn(1, "inf", b) if g.owner[b] == 1 else None


def test_world_map_thirty_factions_and_indexes():
    from ridgeline.worldgen import gen_world
    from ridgeline import data as D
    m = gen_world(2, scale=0.5); land = [p for p in m.provs if p.terrain != "water"]
    assert len(m.capitals) == len(set(m.capitals)) == len(D.WORLD) == 31
    assert sum(1 for p in land if p.biome == "desert") > 20 and sum(1 for p in land if p.biome == "tundra") > 20
    assert sum(1 for p in land if p.terrain == "mountain") > 20 and any(p.sea for p in land)
    seen = {land[0].id}; q = [land[0].id]
    for x in q:
        for y in m.provs[x].nbrs:
            if y not in seen: seen.add(y); q.append(y)
    assert len(seen) == len(land)                                   # every land mass can be reached (sea links)
    assert all(len(x) >= 2 for x in m.start_provs) and all(m.provs[c].city for c in m.capitals)
    g = Game("world", seed=2, gmap=m, max_ticks=400); n = len(g.players); assert n == 31
    ss = [Session(g, i) for i in range(n)]; basic = open(os.path.join(os.path.dirname(__file__), "..", "policies", "basic.py")).read()
    for s in ss: assert "installed" in s.set_policy("main", basic)
    assert "REAL WORLD" in ss[7].brief() and "EXPERIENCE" in ss[7].brief()
    n0 = len(g.units)
    for _ in range(120):
        for s in ss: s.pre_tick()
        g.step()
    assert all("main" in s.policies and not s.policies["main"]["err"] for s in ss), [s.policies.get("main", {}).get("err") for s in ss]
    # the indexes agree with the plain state
    assert sum(len(d) for d in g.punits) == len(g.units) == sum(len(l) for l in g.grid.values()) == sum(len(x) for x in g.pos)
    for pid in range(n):
        assert g.owned[pid] == set(i for i in range(g.n) if g.owner[i] == pid)
        assert g.players[pid].n_units == len(g.punits[pid]) and abs(g.players[pid].upkeep - sum(u.st["upkeep"] for u in g.punits[pid].values())) < 1e-6
    for u in g.units.values(): assert u.bk == (int(u.x / D.BUCKET), int(u.y / D.BUCKET)) and u in g.pos[u.prov]
    for p in g.players:                                             # incremental vision equals vision from scratch
        vis = set()
        for i in g.owned[p.id]: vis.add(i); vis.update(g.provs[i].nbrs)
        for u in g.punits[p.id].values(): vis.update(g.sight_from(u.prov, u.st["sight"] + g.provs[u.prov].elev))
        assert vis == p.visible, p.faction
    assert len(g.units) > n0 * 0.5 and len(g.battle_log) > 0 and sum(g.owner.count(i) for i in range(n)) > sum(len(x) for x in m.start_provs)


def test_resources_new_units_and_blind_upgrades():
    from ridgeline import data as D
    from ridgeline.wargame import belief_game
    g = small_game(seed=4, max_ticks=10 ** 6); s = Session(g, 0); p = g.players[0]
    assert len(D.UNITS) == 14 and sum(1 for pr in g.provs if pr.steel) > 5 and sum(1 for pr in g.provs if pr.oil) > 3
    # several resources: deposits pay only while supplied, and units need them
    g.step(); own = [i for i in p.supplied]
    assert abs(p.inc["steel"] - sum(g.provs[i].steel for i in own)) < 1e-9
    p.res = 1e5; p.mp = 1e5; p.bank.update(steel=0.0, oil=0.0, rare=0.0)
    assert "steel" in s.act("recruit hvt") and s.act("recruit inf").startswith("ok")
    p.bank.update(steel=500.0, oil=500.0, rare=50.0); st0 = p.bank["steel"]
    assert s.act("recruit hvt").startswith("ok") and p.bank["steel"] == st0 - p.stats["hvt"]["steel"]
    # armour: soft weapons do little to it, anti-tank guns a lot
    assert D.UNITS["atg"]["ap"] > 2 and D.UNITS["inf"]["ap"] < 1 and D.UNITS["hvt"]["hard"] == 1.0
    # upgrades: the faction sees lines, levels, costs; never the hidden depth or size
    api = PolicyApi(s, {}); assert len(api.tech) == 14 * 3 + len(D.TECH_GENERAL)
    seen = s.brief() + s.query("tech") + repr(api.tech) + repr(s.obs_json())
    assert "_depth" not in seen and "_size" not in seen and all(t["status"] == "open" and t["level"] == 0 for t in api.tech.values())
    assert all(set(t) == {"level", "status", "cost", "hours"} for t in api.tech.values())
    deep = next(l for l in g.tech_lines() if p._depth[l] >= 2 and l.endswith(".weapons")); dud = next(l for l in g.tech_lines() if p._depth[l] == 0)
    code = deep.split(".")[0]; a0 = p.stats[code]["atk"]; u = g.spawn(0, code, p.capital); r0 = p.res
    assert s.act("research %s" % deep).startswith("ok") and s.act("research %s" % dud).startswith("ok") and p.res < r0
    assert "busy" in s.act("research %s" % next(l for l in D.TECH_GENERAL if l != dud)) and "being researched" in s.act("research %s" % deep)
    for _ in range(D.TECH_HOURS + 1): g.step()
    assert p.tech.get(deep) == 1 and abs(p.stats[code]["atk"] / a0 - 1 - p._size[deep][0]) < 0.01 and u.st["atk"] == a0   # the unit in the field is still the old model
    api = PolicyApi(s, {}); mine = next(x for x in api.units if x["id"] == u.id)
    assert mine["old"] and mine["mark"] == 1 and api.marks[code] == 2 and api.old_units >= 1 and "old models" in s.obs("full")
    new = g.spawn(0, code, p.capital); assert new.st["atk"] == p.stats[code]["atk"] and new.st["mark"] == 2     # new recruits are the new model
    c = g.refit_cost(0, code); p.res = 0
    assert "need" in s.act("refit %d" % u.id) and u.st["atk"] == a0                                              # refit is not free
    p.res = 10000.0; [p.bank.__setitem__(k, 10000.0) for k in p.bank]; rd = u.rdy
    assert s.act("refit old:%s" % code).startswith("ok") and u.st is p.stats[code] and abs(10000.0 - p.res - c["res"] * sum(1 for x in g.punits[0].values() if x.type == code and x.id != new.id)) < 1e-6
    assert u.rdy <= rd and "already" in s.act("refit %d" % u.id)
    assert dud in p.dead and "dead end" in s.act("research %s" % dud) and g.tech_status(0, dud)[1] == "dead end"
    log = PolicyApi(s, {}).tech_log; assert [x["ok"] for x in sorted(log, key=lambda x: x["line"] != deep)] == [True, False]
    assert "BREAKTHROUGH" in s.obs("full") + s.query("tech") and "DEAD END" in s.query("tech")
    assert g.players[1].stats[code]["atk"] != p.stats[code]["atk"] or g.players[1].faction != p.faction      # nobody else gained from it
    assert g.players[0]._depth != g.players[1]._depth                                                       # every faction has its own table
    assert Game(("aurum", "sable"), seed=4, gmap=g.map).players[0]._depth == p._depth                       # ... fixed by the seed
    # a staff wargame cannot be used to peek: it rolls its own research dice and never touches the real stats
    bg, _ = belief_game(s); bp = bg.players[0]
    assert bp._depth != p._depth and bp.stats[code] is not p.stats[code] and bp.stats[code]["atk"] == p.stats[code]["atk"]
    for l in g.tech_lines():
        if bg.tech_status(0, l)[1] == "open" and len(bp.research) < D.TECH_SLOTS: bp.res = 1e6; bp.bank.update(steel=1e6, oil=1e6, rare=1e6); bg.order_research(0, l)
    assert all(tw.st["mark"] == g.units[i].st["mark"] and tw.st is not g.units[i].st for i, tw in bg.units.items() if tw.owner == 0) if "bg" in dir() else True
    a1 = {c: dict(v) for c, v in p.stats.items()}
    for _ in range(D.TECH_HOURS * 2 + 2): bg.step()
    assert a1 == p.stats and len(p.tech_log) == 2
    # the enemy's upgrades are not visible
    e = Session(g, 1); assert deep not in repr(PolicyApi(e, {}).tech_log) and all(t["level"] == 0 for t in PolicyApi(e, {}).tech.values())
    # general lines work too
    gen = next((l for l in D.TECH_GENERAL if p._depth[l] >= 1 and l in ("farming", "mining", "drilling", "refining", "conscription")), None)
    if gen:
        key = dict(farming="res", mining="steel", drilling="oil", refining="rare", conscription="mp")[gen]
        assert s.act("research %s" % gen).startswith("ok")
        for _ in range(D.TECH_HOURS + 1): g.step()
        assert p.mult[key] > 1.0

def test_refit_and_diplomacy_are_mechanics_only():
    from ridgeline import data as D
    from ridgeline.iface import PolicyApi
    g = Game(seed=11); a, b, c = (Session(g, i) for i in range(3)); pa, pb = g.players[0], g.players[1]
    na, nb = pa.faction, pb.faction
    assert "have not come across" in a.act("say %s hello" % nb)                 # strangers cannot be reached
    cb = pb.capital; pa.known_owner[cb] = 1                                      # a's scouts find b's land
    assert a.act("say %s peace for steel?" % nb).startswith("ok") and pb.mail[-1]["text"] == "peace for steel?"
    assert na in PolicyApi(b, {}).met and PolicyApi(b, {}).inbox[-1]["frm"] == na and PolicyApi(c, {}).inbox == []
    pa.res = 500.0; r0 = pb.res
    assert a.act("give %s 200 res" % nb).startswith("ok") and pa.res == 300.0 and pb.res == r0 + 200
    assert "need" in a.act("give %s 9999 res" % nb)
    # trade
    pa.bank["steel"] = 50.0; pb.bank["oil"] = 40.0; oa = pa.bank["oil"]; sb = pb.bank["steel"]
    assert "offer" in a.act("offer %s trade 30 steel for 20 oil" % nb)
    o = PolicyApi(b, {}).offers_in[0]; assert o["they_give"] == {"steel": 30} and o["you_give"] == {"oil": 20} and o["frm"] == na
    assert PolicyApi(c, {}).offers_in == [] and "no such offer" in c.act("accept %d" % o["id"])        # nobody else sees or takes it
    assert b.act("accept %d" % o["id"]).startswith("ok") and pa.bank["oil"] == oa + 20 and pb.bank["steel"] == sb + 30 and pa.bank["steel"] == 20
    # pact: no fire, no capture, no prepared attack; break gives notice
    a.act("offer %s pact" % nb); oid = PolicyApi(b, {}).offers_in[0]["id"]; assert b.act("accept %d" % oid).startswith("ok")
    assert nb in PolicyApi(a, {}).pacts and (0, 1) in g.peace and PolicyApi(c, {}).pacts == {}
    tgt = next(i for i in g.owned[1] if any(g.owner[n] == 1 for n in g.provs[i].nbrs) and not g.pos[i])
    u = g.spawn(0, "inf", tgt); u.x, u.y = g.provs[tgt].cx, g.provs[tgt].cy; d = g.spawn(1, "inf", tgt); s0 = (u.str, d.str)
    for _ in range(12): g.step()
    assert g.owner[tgt] == 1 and d.str == s0[1] and not u.fighting and not d.fighting and not g.enemy_at(tgt, 1)
    assert "pact" in a.act("prepare %d P%d" % (u.id, g.provs[tgt].nbrs[0])) or g.owner[g.provs[tgt].nbrs[0]] != 1
    t0 = g.tick; assert a.act("break %s" % nb).startswith("ok") and g.pacts[(0, 1)]["ends"] == t0 + D.PACT_NOTICE
    assert any(k == "pact" and "BROKE" in x for _, k, x in pb.events)
    for _ in range(D.PACT_NOTICE + 12): g.step()
    assert (0, 1) not in g.peace and (d.id not in g.units or d.str < s0[1] or g.owner[tgt] == 0)
    assert any(e["kind"] == "break" for e in g.dip_log)

def test_depots_are_the_factions_choice():
    from ridgeline import data as D
    from ridgeline.wargame import belief_game
    g = Game("world", seed=1); s = Session(g, 0); p = g.players[0]; g.step()
    cap = p.capital; assert list(p.depots) == [cap] and p.depots[cap] == 1.0, "everything in one place is only where a faction starts"
    assert "DEPOTS:" in s.brief() and "depot P" in s.brief()
    far = max(p.supplied, key=lambda i: (g.hops[0][i], i)); h0 = g.hops[0][far]; f0 = g.stock_flow(0, far); assert h0 >= 2
    p.res = 1000.0; p.bank["steel"] = 500.0; r0 = p.res
    assert s.act("depot P%d 1" % far).startswith("ok") and p.res == r0 - D.DEPOT_COST and far in p.depot_build
    for _ in range(D.DEPOT_HOURS + 2): g.step()
    assert far not in p.depot_build and g.hops[0][far] == 0 and g.stock_flow(0, far) > f0, "a second depot shortens the supply line"
    assert 0 < p.depots[far] < 0.1 and abs(sum(p.depots.values()) - 1) < 1e-6, "the treasury is carried there at a limited rate"
    for _ in range(40): g.step()
    assert abs(p.depots[far] - 0.5) < 0.01 and "P%d 50%%" % far in s.query("depots")
    api = PolicyApi(s, {}); assert api.depots[far]["share"] == 0.5 and api.depots[cap]["output"] <= 1.0 and api.depot_cost == D.DEPOT_COST
    b = belief_game(s)[0] if isinstance(belief_game(s), tuple) else belief_game(s); assert b.players[0].depots == p.depots
    # the capital falls: the faction lives on from its other depot, and the captor gets only what was kept in the capital
    p.res = 1000.0; p.bank["steel"] = 500.0; w = g.players[1]; w0 = w.res; ws = w.bank["steel"]
    for x in list(g.pos[cap]): g._die(x, None)
    g.owner[cap] = 1; g._own_dirty = True; g._check_end()
    assert p.alive and p.capital == far and list(p.depots) == [far] and abs(p.res - 500) < 6 and abs(w.res - w0 - 500) < 6 and abs(w.bank["steel"] - ws - 250) < 3
    assert "need at least one" in s.act("depot P%d 0" % far)
    for x in list(g.pos[far]): g._die(x, None)
    g.owner[far] = 1; g._own_dirty = True; g._check_end()
    assert not p.alive and g.owner.count(0) == 0, "a faction with no depot left is out"
    # one depot can only push so much: a wide empire on a single depot is served slower than the same land on two
    g = Game("world", seed=1); g.step(); p = g.players[0]; cap = p.capital; seen = {cap}; q = [cap]
    for a in q:
        for b_ in g.provs[a].nbrs:
            if b_ not in seen and g.provs[b_].terrain != "water" and len(seen) < 400: seen.add(b_); q.append(b_)
    for i in seen: g.owner[i] = 0
    g._own_dirty = True; g.sdirty[0] = True; g.step()
    assert g.throttle[0][cap] < 0.6 and g.load[0][cap] > D.HUB_LOAD_CITY
    t1 = g.throttle[0][cap]; p.res = 1e4; mid = q[-1]
    assert g.order_depot(0, mid) is None
    for _ in range(D.DEPOT_HOURS + 2): g.step()
    assert g.throttle[0][cap] > t1 * 1.2, "a second depot takes load off the first"
    # an open-ended pact is possible again: how long peace lasts is the factions' choice
    g.players[0].met.add(1); g.players[1].met.add(0)
    e, oid = g.order_offer(0, 1, "pact"); assert e is None and g.offers[oid]["hours"] == 0


def test_v8_resources_relations_and_climate():
    from ridgeline import data as D
    g = Game("world", seed=1); g.step(); n = len(g.players); names = [p.faction for p in g.players]
    assert "haedong" in names and g.provs[g.players[names.index("haedong")].capital].name == "Hanseong"
    # strategic resources lie in fields: most factions start without some kinds, and the oil is where the oil is
    have = [{k for k in D.STRAT if any(getattr(g.provs[i], k) for i in g.owned[p.id])} for p in g.players]
    assert sum(1 for h in have if len(h) < 5) > n * 0.8 and "oil" in have[names.index("persia")] and "oil" not in have[names.index("yamato")]
    # an upgrade needs more kinds of resource the further it goes; the price is public, the result is not
    c1, c3 = g.tech_cost("arm.weapons", 1), g.tech_cost("arm.weapons", 3)
    assert set(c1) == {"res", "steel"} and set(c3) == {"res", "steel", "coal", "rare"}
    a, b = g.players[0], g.players[1]; a.bank = dict.fromkeys(D.STRAT, 0.0); a.res = 5000.0; a.bank["steel"] = 500.0
    assert g.order_research(0, "arm.weapons") is None and "need" in g.order_research(0, "inf.mobility")
    sa, sb = Session(g, 0), Session(g, 1); a.met.add(1); b.met.add(0)
    assert "coal" in sa.brief() and "SEASONS AND CLIMATE" in sa.brief() and "_depth" not in sa.brief()
    # a standing delivery runs every day until someone cuts it off, and the neighbours hear who did
    b.bank["oil"] = 100.0; a.res = 1000.0
    assert sa.act("offer %s supply 20 res for 5 oil" % b.faction).startswith("ok"); oid = max(g.offers)
    assert sb.act("accept %d" % oid).startswith("ok") and oid in g.deals
    o0 = a.bank["oil"]
    for _ in range(48): g.step()
    assert a.bank["oil"] >= o0 + 9 and PolicyApi(sa, {}).deals[0]["they_give"] == {"oil": 5}
    g.players[2].met.add(1); assert sb.act("cancel %d" % oid).startswith("ok") and not g.deals
    assert any(k == "news" and "cut off" in x for _, k, x in g.players[2].events) and any(k == "deal" for _, k, x in a.events)
    # land can change hands by agreement (the price of peace, a sale): a truce follows; a depot province cannot be given
    mine = next(i for i in g.owned[0] if i not in a.depots)
    assert "depot" in sa.act("offer %s trade P%d for 10 res" % (b.faction, a.capital))
    assert sa.act("offer %s trade P%d for 10 res" % (b.faction, mine)).startswith("ok"); r0 = a.res
    assert sb.act("accept %d" % max(g.offers)).startswith("ok") and g.owner[mine] == 1 and a.res == r0 + 10 and g.pacts[(0, 1)].get("truce")
    # an alliance is a pact in which each side sees what the other sees
    assert sa.act("offer %s alliance" % b.faction).startswith("ok") and sb.act("accept %d" % max(g.offers)).startswith("ok")
    g.step(); far = next(i for i in g.owned[1] if i not in g.ownvis[0] and all(x not in g.owned[0] for x in g.provs[i].nbrs))
    for _ in range(25): g.step()
    assert (0, 1) in g.allies and far in a.visible and PolicyApi(sa, {}).pacts[b.faction]["kind"] == "alliance"
    pw = PolicyApi(sa, {}).powers; assert pw[b.faction]["relation"] == "alliance" and pw[b.faction]["land"] > 0 and pw[a.faction]["me"]
    # engines burn oil; without it they fight at reduced power
    a.bank["oil"] = 0.0; a.inc["oil"] = 0.0
    for i in list(g.owned[0]):
        g.provs[i].oil = 0
    for _ in range(26): g.step()
    assert a.fuel > 0 and a.nofuel and "NO-FUEL" in sa.obs("full").split("\n")[0]
    # winter: the north freezes, moving there is slower, and an army far from home melts away unless it knows winter
    north = next(i for i, pr in enumerate(g.provs) if pr.terrain == "plain" and pr.lat > 50 and not pr.biome); south = next(i for i, pr in enumerate(g.provs) if pr.terrain == "plain" and -40 > pr.lat)
    u = g.spawn(0, "inf", north); c0 = g.move_cost(u, north)
    assert north not in g.cold and g.season_at(g.tick, 50) == 0
    g.tick = 24 * D.SEASON_DAYS * 3; g._seasons()
    assert north in g.cold and south not in g.cold and g.move_cost(u, north) == c0 * D.COLD_MOVE and g.season_at(g.tick, -30) == 1
    soft = next(p for p in g.players if not p.hardy and p.alive); hard = next(p for p in g.players if p.hardy)
    x = g.spawn(soft.id, "inf", north); y = g.spawn(hard.id, "inf", north); g.owner[north] = -1
    s0 = (x.str, y.str); g._unit_hour(x, 10); g._unit_hour(y, 10)
    assert s0[0] - x.str > (s0[1] - y.str) + 0.5 > 0.5, "frost hurts, and hurts strangers to winter more"
    jung = next(iter(g.jungle)); eu = next(p for p in g.players if not p.tropic); tr = next(p for p in g.players if p.tropic)
    x = g.spawn(eu.id, "inf", jung); y = g.spawn(tr.id, "inf", jung); g.owner[jung] = -1; s0 = (x.str, y.str); g._unit_hour(x, 10); g._unit_hour(y, 10)
    assert x.str < y.str, "fever"


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)
