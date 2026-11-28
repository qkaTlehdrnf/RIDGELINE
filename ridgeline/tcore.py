"""Torch (GPU) paths for the hot loops of the engine. Same rules, same results bit for bit, faster.

    from ridgeline import tcore; tcore.enable(game)            # or Game(..., engine="torch") via tools that pass --engine torch

What runs here now: choosing the targets of every unit in a hot area (Game._fire_plan), which was the costliest part
of an hour. Everything a hit then does (damage, morale, assaults, experience) stays in engine.py, so rule changes
there need no change here. A rule change in Game._fire_plan or Game._xok must be mirrored in _plan below;
tools/bench_war.py --engine torch prints the same state hashes as the CPU engine when both agree.

Device: RIDGELINE_DEVICE (default cuda when available, else cpu).
"""
import os
import time as _time
import types

import torch

from . import data as D

_OFFS = [(dx, dy) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)]


class _Tables:
    """Per unit-version numbers the plan needs, one row per stats dict (a faction's version of a type)."""
    def __init__(self, dev):
        self.dev = dev; self.row = {}; self.keep = []; self.rows = []; self.t = None

    def idx(self, st):
        k = id(st); r = self.row.get(k)
        if r is None:
            r = self.row[k] = len(self.rows); self.keep.append(st)
            self.rows.append((st["range"], st["dom"], st["va"], st["vs"], st["vg"])); self.t = None
        return r

    def tensor(self):
        if self.t is None: self.t = torch.tensor(self.rows, dtype=torch.float64, device=self.dev)
        return self.t


def enable(g, device=None):
    dev = torch.device(device or os.environ.get("RIDGELINE_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu"))
    torch.set_num_threads(1)                      # the work is on the GPU; idle CPU worker threads only spin
    g._tc = dict(dev=dev, tab=_Tables(dev), stats=dict(hours=0, fallback=0))
    g._fire_plan = types.MethodType(_fire_plan, g)
    g.engine = "torch"
    return g


def _plan(g, H):
    """For the units H (all units of the hot buckets, in bucket order): the targets of each, as {index in H: [index in H, ...]}
    (nearest first, ties by id, at most TARGETS) for every unit that has one; and its ux."""
    tc = g._tc; dev = tc["dev"]; tab = tc["tab"]; S0 = g.sea0; B = D.BUCKET; n = len(H); P = len(g.players)
    f64 = torch.float64; i64 = torch.int64
    X = torch.tensor([u.x for u in H], dtype=f64, device=dev); Y = torch.tensor([u.y for u in H], dtype=f64, device=dev)
    O = torch.tensor([u.owner for u in H], dtype=i64, device=dev); ID = torch.tensor([u.id for u in H], dtype=i64, device=dev)
    PV = torch.tensor([u.prov for u in H], dtype=i64, device=dev); PL = torch.tensor([u.plan_t if u.plan_t is not None else -1 for u in H], dtype=i64, device=dev)
    BA = torch.tensor([u.base for u in H], dtype=i64, device=dev)
    PA = torch.tensor([bool(u.path) for u in H], dtype=torch.bool, device=dev); RO = torch.tensor([u.rout for u in H], dtype=torch.bool, device=dev)
    BX = torch.tensor([u.bk[0] for u in H], dtype=i64, device=dev); BY = torch.tensor([u.bk[1] for u in H], dtype=i64, device=dev)
    ti = tab.idx; SI = torch.tensor([ti(u.st) for u in H], dtype=i64, device=dev); T = tab.tensor()[SI]
    RNG = T[:, 0]; DOM = T[:, 1].to(i64); VA = T[:, 2]; VS = T[:, 3]; VG = T[:, 4]
    OWN = torch.tensor(g.owner, dtype=i64, device=dev)
    ASS = torch.zeros((g.n, P), dtype=torch.bool, device=dev)
    if g.assaults:
        k = torch.tensor(list(g.assaults.keys()), dtype=i64, device=dev); ASS[k[:, 0], k[:, 1]] = True
    PEACE = torch.zeros((P, P), dtype=torch.bool, device=dev)
    if g.peace:
        k = torch.tensor(list(g.peace), dtype=i64, device=dev); PEACE[k[:, 0], k[:, 1]] = True
    WAR = torch.tensor([[g.war(a, b) for b in range(P)] for a in range(P)], dtype=torch.bool, device=dev)

    sea = PV >= S0
    ok_s = ~RO & ~(sea & (DOM == 0)) & ~(~sea & (DOM == 2) & ~PA & (PV == BA) & (VA < 0.5))
    UX = torch.where(sea, torch.clamp(DOM, min=1), DOM)
    R = torch.where(RNG <= B, 1, 2); R2 = RNG * RNG
    OWNP = OWN[PV]; foreign = OWNP != O
    mode1 = PA | foreign
    AL = (DOM != 0) | sea | PA | foreign                     # as a target: always answered by a unit holding its line
    # spatial hash on the GPU: sort by bucket, look up the 5 x 5 buckets around each shooter
    key = (BX + 4096) * 8192 + (BY + 4096)
    sk, order = torch.sort(key, stable=True)
    uk, cnt = torch.unique_consecutive(sk, return_counts=True); start = torch.cumsum(cnt, 0) - cnt
    s_idx = torch.nonzero(ok_s).squeeze(1)
    if s_idx.numel() == 0: return {}, UX
    off = torch.tensor(_OFFS, dtype=i64, device=dev)
    nk = ((BX[s_idx, None] + off[None, :, 0]) + 4096) * 8192 + (BY[s_idx, None] + off[None, :, 1] + 4096)     # (S, 25)
    inR = (off[None, :, 0].abs() <= R[s_idx, None]) & (off[None, :, 1].abs() <= R[s_idx, None])
    pos = torch.searchsorted(uk, nk).clamp(max=uk.numel() - 1)
    so = O[order]; omin = torch.full_like(uk, 1 << 30).scatter_reduce(0, torch.repeat_interleave(torch.arange(uk.numel(), device=dev), cnt), so, "amin")
    omax = torch.full_like(uk, -1).scatter_reduce(0, torch.repeat_interleave(torch.arange(uk.numel(), device=dev), cnt), so, "amax")
    hit = (uk[pos] == nk) & inR & ~((omin[pos] == omax[pos]) & (omin[pos] == O[s_idx, None]))      # a bucket holding only the shooter's own side has nothing to fire at
    c = torch.where(hit, cnt[pos], 0).reshape(-1); st0 = torch.where(hit, start[pos], 0).reshape(-1)
    shooter = s_idx.repeat_interleave(25)
    tot = int(c.sum()); tc["stats"]["pairs"] = tc["stats"].get("pairs", 0) + tot
    if tot == 0: return {}, UX
    rep = torch.repeat_interleave(torch.arange(c.numel(), device=dev), c)
    within = torch.arange(tot, device=dev) - (torch.cumsum(c, 0) - c)[rep]
    s = shooter[rep]; t = order[st0[rep] + within]
    os_ = O[s]; ot = O[t]
    m = (ot != os_) & ~PEACE[ot, os_]
    d2 = (X[t] - X[s]) ** 2 + (Y[t] - Y[s]) ** 2
    m &= d2 <= R2[s]
    s, t, d2, os_, ot = s[m], t[m], d2[m], os_[m], ot[m]
    # may s fire at t when one of them is not ground troops on land (Game._xok)
    dt = DOM[t]; seat = sea[t]
    tdx = torch.where((dt == 0) & seat, 1, dt)
    f = (dt == 2) & ~PA[t] & (PV[t] == BA[t])
    ds = DOM[s]
    f |= (ds == 2) & (tdx != 2) & ~PA[s] & (PV[s] == BA[s])
    w = torch.where(tdx == 2, VA[s], torch.where(tdx == 1, VS[s], VG[s])); f |= w <= 0.0
    f |= ~WAR[os_, ot]
    f |= (tdx == 0) & (ds != 0) & (PL[s] != PV[t]) & ~ASS[PV[t], os_]
    xok = ~f
    m1 = mode1[s]
    need1 = (UX[s] != 0) | (dt != 0) | seat
    keep1 = m1 & (~need1 | xok)
    alt = AL[t]
    keep2a = ~m1 & alt & (~((dt != 0) | seat) | xok)
    cand = ASS[PV[s], ot] | (PL[t] == PV[s]) | (PV[t] == PL[s]) | ASS[PV[t], os_]
    keep2b = ~m1 & ~alt & cand
    m = keep1 | keep2a | keep2b
    s, t, d2 = s[m], t[m], d2[m]
    if s.numel() == 0: return {}, UX
    # nearest first, ties by id, at most TARGETS per shooter
    o1 = torch.sort(ID[t], stable=True)[1]; s, t, d2 = s[o1], t[o1], d2[o1]
    o2 = torch.sort(d2, stable=True)[1]; s, t = s[o2], t[o2]
    o3 = torch.sort(s, stable=True)[1]; s, t = s[o3], t[o3]
    us, uc = torch.unique_consecutive(s, return_counts=True)
    first = torch.repeat_interleave(torch.cumsum(uc, 0) - uc, uc)
    rk = torch.arange(s.numel(), device=dev) - first
    k = rk < D.TARGETS
    s = s[k].tolist(); t = t[k].tolist()
    out = {}
    for a, b in zip(s, t):
        l = out.get(a)
        if l is None: out[a] = [b]
        else: l.append(b)
    return out, UX


def _fire_plan(self, mono, hot_units):
    """Game._fire_plan with the targets chosen on the GPU in one go. Should a war begin during the hour (one unit's fire can
    start one), the rest of the hour is chosen by the CPU code, as the plan may be stale."""
    grid = self.grid; H = []
    for (bx, by), me in mono.items():
        hot = me == -2
        if not hot:
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    o = mono.get((bx + dx, by + dy))
                    if o is not None and o != me: hot = True; break
                if hot: break
        if hot: H.extend(grid[(bx, by)])
    st = self._tc["stats"]; st["hours"] += 1
    if not H: return
    t0 = _time.perf_counter(); plan, UX = _plan(self, H); st["plan_s"] = st.get("plan_s", 0.0) + _time.perf_counter() - t0
    ux = UX.tolist() if plan else None
    wv = self._warv
    for i, u in enumerate(H):
        if self._warv != wv:                     # a war began this hour: the CPU picks for everyone not yet served
            st["fallback"] += 1
            yield from _cpu_rest(self, H[i:], hot_units)
            return
        u.contact = True; hot_units.append(u)
        p = plan.get(i)
        if p: yield u, [(None, H[j].id, H[j]) for j in p], ux[i]


def _cpu_rest(g, rest, hot_units):
    """The CPU rules (Game._fire_plan) for the remaining units: re-run it on just these, sharing nothing it would cache across them."""
    owner = g.owner; S0 = g.sea0; xok = g._xok; peace = g.peace; ass = g.assaults; grid = g.grid
    for u in rest:
        u.contact = True; hot_units.append(u)
        if u.rout: continue
        st = u.st; r = st["range"]; r2 = r * r; R = 1 if r <= D.BUCKET else 2; ux = st["dom"]
        if u.prov >= S0:
            if not ux: continue
            ux = ux or 1
        elif ux == 2 and not u.path and u.prov == u.base and st["va"] < 0.5: continue
        bx, by = u.bk
        fl = [t for dx in range(-R, R + 1) for dy in range(-R, R + 1) for t in grid.get((bx + dx, by + dy), ()) if t.owner != u.owner and (t.owner, u.owner) not in peace]
        if not fl: continue
        best = []; uxx = u.x; uy = u.y
        if u.path or owner[u.prov] != u.owner:
            for t in fl:
                d = (t.x - uxx) ** 2 + (t.y - uy) ** 2
                if d <= r2:
                    if (ux or t.st["dom"] or t.prov >= S0) and not xok(u, t): continue
                    best.append((d, t.id, t))
        else:
            uo = u.owner; upv = u.prov; upl = u.plan_t
            for t in fl:
                if t.st["dom"] or t.prov >= S0 or t.path or owner[t.prov] != t.owner:
                    if (t.st["dom"] or t.prov >= S0) and not xok(u, t): continue
                elif not ((upv, t.owner) in ass or (t.plan_t is not None and t.plan_t >= 0 and t.plan_t == upv) or t.prov == upl or (t.prov, uo) in ass): continue
                d = (t.x - uxx) ** 2 + (t.y - uy) ** 2
                if d <= r2: best.append((d, t.id, t))
        if not best: continue
        best.sort(); yield u, best[:D.TARGETS], ux
