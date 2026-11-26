"""Run: python tests/test_core.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline.engine import Game
from ridgeline.iface import Session
from ridgeline.match import run_match
from bots.basic import Bot


def spawn(g, pid, code, x, y):
    return g._spawn_unit(pid, code, g.idx(x, y))


def test_high_ground_vision():
    g = Game()
    low = spawn(g, 0, "inf", 20, 43)      # low ground just north of P0's natural shelf... P0's own, used as viewer
    g.update_vision()
    # P1 unit standing on P0's main shelf (level 2) right at the cliff edge above
    up = spawn(g, 1, "inf", 16, 46); down = spawn(g, 1, "inf", 22, 42)
    for e in [x for x in g.ents.values() if x.owner == 0 and x is not low]: g._kill(e)   # remove P0 base so only `low` sees
    g.update_vision()
    assert not g.visible(0, up), "low ground must not see a unit on the high shelf"
    assert g.visible(0, down), "low ground sees low ground"
    assert g.visible(1, low), "the unit on the shelf sees down"
    # a flyer lifts the fog
    fly = spawn(g, 0, "fly", 20, 43); g.update_vision()
    assert g.visible(0, up), "flyers see high ground"
    g._kill(fly); g.update_vision(); assert not g.visible(0, up)
    # shooting reveals the shooter
    g.order_units(1, [up.id], ("attack", low.id))
    for _ in range(4): g.step()
    assert g.visible(0, up), "firing reveals the shooter"


def test_ramp_only_crossing():
    g = Game()
    u = spawn(g, 0, "inf", 16, 50)                     # on the main shelf
    g.order_units(0, [u.id], ("move", 20.5, 43.5))     # low ground below the cliff
    seen_ramp = False
    for _ in range(600):
        g.step()
        if g.ramp[g.idx(int(u.x), int(u.y))]: seen_ramp = True
    assert seen_ramp and abs(u.x - 20.5) < 1 and abs(u.y - 43.5) < 1, (u.x, u.y)


def test_delta_and_commands():
    g = Game(); s = Session(g, 0)
    full = s.obs("full"); assert full.startswith("t0 ore50")
    r = s.act("auto wrk 12\ntrain hq wrk\nbogus 1 2\nbuild bar 12 50")
    assert "ok 2" in r and "E3 bogus" in r and "E4 build: need 150" in r, r
    for _ in range(100): s.pre_tick(); g.step()
    d = s.obs(); assert len(d) < len(full) + 40 and d.split("\n")[0].startswith("t100 "), d
    d2 = s.obs(); assert d2.count("\n") == 0, "nothing changed -> header only: %r" % d2
    assert "site bar" in s.query("site bar 12 50") and "via R7" in s.query("path 10 56 54 10")


def test_script():
    g = Game(); s = Session(g, 0)
    r = s.set_script("eco", "def tick(api):\n    if api.ore >= 50 and api.sup[0] < api.sup[1]:\n        api.cmd('train hq wrk')\n", 10)
    assert "installed" in r, r
    assert "error" in s.set_script("bad", "import os\ndef tick(api): pass")
    for _ in range(600): s.pre_tick(); g.step()
    assert sum(1 for e in g.ents.values() if e.owner == 0 and e.type == "wrk") > 6


def test_full_match_deterministic():
    a = run_match(lambda s: Bot(s), lambda s: Bot(s), max_ticks=3000)
    b = run_match(lambda s: Bot(s), lambda s: Bot(s), max_ticks=3000)
    assert a == b, (a, b)


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)
