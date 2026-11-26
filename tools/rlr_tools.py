"""Small utilities for .rlr replays (see tools/record_replay.py for the format).

  python tools/rlr_tools.py info  replay.rlr
  python tools/rlr_tools.py cut   replay.rlr out.rlr FROM_HOUR TO_HOUR [EVERY]     # excerpt; first frame becomes a key frame
  python tools/rlr_tools.py split replay.rlr out_prefix MB                          # pieces of at most MB megabytes (for hosts
                                                                                    # with a file size limit); the viewer joins
                                                                                    # them with ?src=a.bin,b.bin,...  (--b64: base64 .txt pieces)
"""
import json
import os
import struct
import sys
import zlib

import numpy as np

NCOL = 17


def read_header(path):
    with open(path, "rb") as f:
        f.seek(-12, 2); off, ln = struct.unpack("<II", f.read(8)); f.seek(off); return json.loads(f.read(ln))


def frames(path):
    """Yield (t, ids, cols[17,N], prov[3,P], vis bytes, shots, meta bytes) as absolute values, frame by frame."""
    h = read_header(path); nf = len(h["factions"]); prev = None
    with open(path, "rb") as f:
        for off, ln, t, key in h["frames"]:
            f.seek(off); b = zlib.decompress(f.read(ln))
            t, key, N, P, S, ML, G, _ = struct.unpack_from("<8i", b, 0); o = 32
            ids = np.cumsum(np.frombuffer(b, np.int32, N, o).astype(np.int64)); o += 4 * N
            cols = np.frombuffer(b, np.uint8, NCOL * N, o).reshape(NCOL, N).astype(np.int64); o += NCOL * N
            prov = np.frombuffer(b, np.uint8, 3 * P, o).reshape(3, P).astype(np.int64); o += 3 * P
            nv = 2 * nf * ((P + 7) // 8) if h.get("vis") else 0
            vis = np.frombuffer(b, np.uint8, nv, o).copy(); o += nv
            shots = b[o:o + 4 * S]; o += 4 * S; meta = b[o:o + ML]
            if not key:
                pids, pcols, pprov, pvis = prev
                j = np.minimum(np.searchsorted(pids, ids), max(0, len(pids) - 1)); hit = (pids[j] == ids) if len(pids) else np.zeros(N, bool)
                base = np.zeros_like(cols); base[:, hit] = pcols[:, j[hit]]
                cols = (cols + base) & 255; prov = (prov + pprov) & 255; vis = vis ^ pvis
            prev = (ids, cols, prov, vis)
            yield t, ids, cols, prov, vis, shots, meta, G


def cut(src, dst, t0, t1, every=1, key_every=24):
    h = read_header(src); out = open(dst, "wb"); out.write(b"RLR1"); index = []; prev = None; n = 0
    with open(src, "rb") as f:
        c = h["cells"]; f.seek(c[0]); cells = f.read(c[1])
    h["cells"] = [out.tell(), len(cells)]; out.write(cells)
    for t, ids, cols, prov, vis, shots, meta, G in frames(src):
        if t < t0 or t > t1 or (t - t0) % every: continue
        key = n % key_every == 0
        if key: dc, dp, dv = cols, prov, vis
        else:
            pids, pcols, pprov, pvis = prev
            j = np.minimum(np.searchsorted(pids, ids), max(0, len(pids) - 1)); hit = pids[j] == ids
            base = np.zeros_like(cols); base[:, hit] = pcols[:, j[hit]]
            dc = cols - base; dp = prov - pprov; dv = vis ^ pvis
        prev = (ids, cols, prov, vis)
        body = struct.pack("<8i", t, int(key), len(ids), prov.shape[1], len(shots) // 4, len(meta), G, 0) \
            + np.diff(ids, prepend=0).astype(np.int32).tobytes() + (dc & 255).astype(np.uint8).tobytes() + (dp & 255).astype(np.uint8).tobytes() \
            + dv.tobytes() + shots + meta
        z = zlib.compress(body, 6); index.append([out.tell(), len(z), t, int(key)]); out.write(z); n += 1
    h["frames"] = index; h["key"] = key_every; h["timeline"] = [r for r in h.get("timeline", []) if t0 <= r["t"] <= t1]
    hb = json.dumps(h, separators=(",", ":")).encode(); off = out.tell(); out.write(hb); out.write(struct.pack("<II", off, len(hb)) + b"RLR1"); out.close()
    print("wrote", dst, "%d frames, %.1f MB" % (n, os.path.getsize(dst) / 1e6))


def split(src, prefix, mb, b64=False):
    data = open(src, "rb").read(); step = int(mb * 1e6 * (0.75 if b64 else 1)) // 3 * 3; names = []
    for i in range(0, len(data), step):
        part = data[i:i + step]
        if b64:
            import base64
            name = "%s.%03d.b64.txt" % (prefix, i // step); open(name, "wb").write(base64.b64encode(part))
        else:
            name = "%s.%03d.bin" % (prefix, i // step); open(name, "wb").write(part)
        names.append(os.path.basename(name))
    print(",".join(names))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"): print(__doc__)
    elif a[0] == "info":
        h = read_header(a[1]); fr = h["frames"]
        print("%s: %d factions, %d frames, hours %d-%d, %.1f MB, visibility %s" % (a[1], len(h["factions"]), len(fr), fr[0][2], fr[-1][2], os.path.getsize(a[1]) / 1e6, bool(h.get("vis"))))
        print("result:", h.get("result"))
    elif a[0] == "cut": cut(a[1], a[2], int(a[3]), int(a[4]), int(a[5]) if len(a) > 5 else 1)
    elif a[0] == "split": split(a[1], a[2], float(a[3]), "--b64" in a)
