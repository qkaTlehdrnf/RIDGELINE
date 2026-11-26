"""Scripted baseline. It plays through the same text command interface an LLM uses."""


class Bot:
    def __init__(self, sess, wave=10, style="mixed"):
        self.s = sess; self.wave = wave; self.style = style; self.started = False
        self.attacking = False; self.last_def = -999

    def step(self):
        s = self.s; g = s.g; pid = s.pid; p = s.p
        if not self.started:
            s.act("auto wrk 16\nauto sup on\nauto gather on"); self.started = True
        o = s.obs_json(); own = o["own"]; cmds = []
        n = lambda t: sum(1 for e in own if e["type"] == t)
        pend = lambda t: sum(1 for e in own if e["type"] == "wrk" and e["order"][0] == "build" and e["order"][1] == t)
        hq = next((e for e in own if e["type"] == "hq"), None)
        if hq is None: return
        hx, hy = hq["x"], hq["y"]; ore = o["ore"]; k = 1 if pid == 0 else -1
        bars = n("bar") + pend("bar"); wks = n("wks") + pend("wks")
        if bars < 1 and ore >= 150: cmds.append("build bar %d %d" % (hx + 4 * k, hy - 3 * k)); ore -= 150
        elif bars < 2 and ore >= 250 and n("wrk") >= 12: cmds.append("build bar %d %d" % (hx + 5 * k, hy + 3 * k)); ore -= 150
        elif n("bar") >= 1 and wks < 1 and ore >= 300 and self.style != "inf": cmds.append("build wks %d %d" % (hx + 1 * k, hy + 6 * k)); ore -= 200
        elif bars < 4 and ore >= 600: cmds.append("build bar %d %d" % (hx + 6 * k, hy)); ore -= 150
        if n("hq") + pend("hq") < 2 and ore >= 500 and g.tick > 3000:
            r = next((r for r in g.regions if r["tag"] == "P%d natural" % pid), None)
            if r: cmds.append("build hq %d %d" % (r["cx"], r["cy"] + 3 * k)); s.auto["wrk"] = 26
        for e in own:
            if e["type"] == "bar" and e["progress"] >= 1 and not e["repeat"]:
                cmds.append("repeat %d %s" % (e["id"], "inf" if (e["id"] % 2 or self.style == "inf") else "hvy"))
                cmds.append("rally %d %d %d" % (e["id"], hx + 6 * k, hy))
            if e["type"] == "wks" and e["progress"] >= 1 and not e["repeat"]:
                cmds.append("repeat %d art" % e["id"]); cmds.append("rally %d %d %d" % (e["id"], hx + 6 * k, hy))
        army = [e for e in own if e["type"] in ("inf", "hvy", "art", "fly")]
        threat = [e for e in o["enemy_visible"] if not e["is_structure"] and abs(e["x"] - hx) + abs(e["y"] - hy) < 26]
        if threat and army and g.tick - self.last_def > 50:
            cmds.append("amove army %d %d" % (threat[0]["x"], threat[0]["y"])); self.last_def = g.tick; self.attacking = False
        elif not threat:
            idle = [e for e in army if e["order"][0] == "idle"]
            if not self.attacking and len(army) >= self.wave:
                self.attacking = True
            if self.attacking:
                if len(army) < self.wave // 3: self.attacking = False; cmds.append("amove army %d %d" % (hx + 6 * k, hy))
                elif idle:
                    tgt = o["enemy_structures_remembered"] + [e for e in o["enemy_visible"] if e["is_structure"]]
                    if tgt: cmds.append("amove %s %d %d" % (",".join(str(e["id"]) for e in idle), tgt[0]["x"], tgt[0]["y"]))
                    else:
                        # nothing known: sweep enemy start, then ore regions
                        spots = ["enemy"] + ["R%d" % r["id"] for r in g.regions if r["ore"]]
                        cmds.append("amove %s %s" % (",".join(str(e["id"]) for e in idle), spots[(g.tick // 600) % len(spots)]))
        if cmds: s.act("\n".join(cmds))
