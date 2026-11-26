"""Map: 64x64 tiles, 3 elevation levels, ramps, brush, rock. 180-degree point symmetric."""

W = H = 64


class Map:
    def __init__(self):
        self.w, self.h = W, H
        n = W * H
        self.level = [0] * n
        self.ramp = [False] * n
        self.brush = [False] * n
        self.block = [False] * n
        self.ore = []          # (x, y)
        self.starts = []       # hq top-left tile per player
        self.name = "twin-shelf"

    def idx(self, x, y):
        return y * self.w + x


def _mir(x, y):
    return W - 1 - x, H - 1 - y


def default_map():
    m = Map()

    def rect(x0, y0, x1, y1, fn):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                for (a, b) in ((x, y), _mir(x, y)):
                    fn(m.idx(a, b))

    def lvl(v):
        def f(i): m.level[i] = v; m.ramp[i] = False
        return f

    def ramp(v):
        def f(i): m.level[i] = v; m.ramp[i] = True
        return f

    def brush(i): m.brush[i] = True
    def rock(i): m.block[i] = True

    # --- player 0 corner (bottom-left); everything is mirrored for player 1 ---
    rect(1, 45, 17, 62, lvl(2))        # main shelf (high)
    rect(18, 47, 31, 62, lvl(1))       # natural shelf (mid)
    rect(18, 52, 18, 54, ramp(2))      # main -> natural
    rect(23, 46, 25, 46, ramp(1))      # natural -> low ground (north)
    rect(32, 56, 32, 58, ramp(1))      # natural -> low ground (east)
    # side ridge with an expansion (mid)
    rect(44, 42, 53, 51, lvl(1))
    rect(43, 46, 43, 48, ramp(1))
    rect(48, 41, 49, 41, ramp(1))
    # central hill (mid) with a summit (high)
    rect(26, 26, 37, 37, lvl(1))
    rect(25, 31, 25, 32, ramp(1))      # west ramp (mirror gives east)
    rect(31, 38, 32, 38, ramp(1))      # south ramp (mirror gives north)
    rect(30, 30, 33, 33, lvl(2))
    rect(31, 34, 32, 34, ramp(2))      # summit ramps south/north
    # brush and rock on the low ground
    rect(19, 37, 22, 40, brush)
    rect(36, 50, 39, 52, brush)
    rect(8, 38, 10, 39, brush)
    rect(38, 43, 40, 44, rock)
    rect(12, 30, 13, 33, rock)
    rect(0, 0, 63, 0, rock); rect(0, 0, 0, 63, rock)   # border
    # ore
    ore = [(2, 48), (2, 50), (2, 52), (2, 54), (2, 56), (2, 58), (4, 60), (6, 61),      # main
           (21, 61), (23, 61), (25, 61), (27, 61), (29, 61), (30, 59),                    # natural
           (52, 43), (52, 45), (52, 47), (52, 49), (50, 50), (48, 50)]                    # ridge
    for (x, y) in ore:
        m.ore.append((x, y)); m.ore.append(_mir(x, y))
    m.starts = [(8, 52), _mir(10, 54)]
    return m


def ascii_map(m, x0=0, y0=0, x1=None, y1=None, overlay=None):
    x1 = m.w - 1 if x1 is None else x1
    y1 = m.h - 1 if y1 is None else y1
    rows = []
    ore = set(m.ore)
    for y in range(y0, y1 + 1):
        r = []
        for x in range(x0, x1 + 1):
            i = m.idx(x, y)
            if overlay and i in overlay: c = overlay[i]
            elif m.block[i]: c = "#"
            elif (x, y) in ore: c = "$"
            elif m.ramp[i]: c = "/"
            elif m.brush[i]: c = '"'
            else: c = ".:^"[m.level[i]]
            r.append(c)
        rows.append("".join(r))
    return "\n".join(rows)


if __name__ == "__main__":
    print(ascii_map(default_map()))
