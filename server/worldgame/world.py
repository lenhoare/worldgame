"""World state: the voxel grid, items, giants, events, time and weather.

Coordinates: x east, z south (the region grid), k = voxel layer counted from
the bottom of the world. Agents see y = k - sea, so y = 0 is the first layer
above sea level. One voxel is `cell` metres on each side (about 3 m).
"""

import math
import random
from collections import deque

import numpy as np

from . import materials as M
from .items import KINDS, Item

CHUNK = 32
DAY_TICKS = 7200          # one game day = 2 hours of one-second ticks
START_CLOCK = 0.36        # world starts mid-morning


class World:
    def __init__(self, X, Z, Y, cell, sea, seed=1):
        self.X, self.Z, self.Y = X, Z, Y
        self.cell = cell
        self.voxel_m3 = cell ** 3
        self.sea = sea                      # layers below sea level; sea surface = top of layer sea-1
        self.seed = seed
        self.rng = random.Random(seed)
        self.vox = np.zeros((X, Z, Y), np.uint8)
        self.top = np.full((X, Z), -1, np.int16)   # highest solid layer per column
        self.t = M.numpy_tables()
        self.tick = 0
        self.rev = 1
        self.chunk_rev = np.ones(((X + CHUNK - 1) // CHUNK, (Z + CHUNK - 1) // CHUNK), np.int64)
        self.items = {}
        self.items_at = {}                  # (x, k, z) -> set of item ids
        self.removed_items = deque(maxlen=20000)   # (rev, id) for the viewer
        self._next_item = 1
        self.giants = {}
        self.changes = deque()              # (x, k, z, old, new) awaiting physics
        self.burning = {}                   # (x, k, z) -> seconds of fuel left
        self.burning_items = set()
        self.hot_items = set()              # items above ambient temperature
        self.heaters = {}                   # powered electric heaters: item id -> temperature
        self.soaked = set()                 # fuel-soaked positions
        self.blow = {}                      # (x, k, z) -> tick until which air is forced
        self.heat = {}                      # (x, k, z) -> seconds of kiln heat received
        self.water_frontier = deque()
        self.water_level = {}               # fresh-water voxel -> surface layer of its body
        self.support_queue = deque()
        self.links = []                     # electrical links: (item a, item b, metres)
        self.signs = {}                     # (x, k, z) -> text written on a voxel
        self.log = deque(maxlen=3000)       # recent events, for the viewer
        self.sites = []                     # named landmarks: {kind, name, x, z}
        self.meta = {}
        self.wind = [1.0, 0.0, 0.3]         # dx, dz (unit), strength 0-1
        self.raining = 0                    # ticks of rain left
        self.dryness = 0.6
        self.stats = {"collapsed": 0, "burnt": 0, "flooded": 0, "broken": 0, "placed": 0}

    # --- coordinates ---------------------------------------------------------
    def inside(self, x, k, z):
        return 0 <= x < self.X and 0 <= z < self.Z and 0 <= k < self.Y

    def get(self, x, k, z):
        """Voxel id; outside the world is bedrock below/sideways and air above."""
        if 0 <= x < self.X and 0 <= z < self.Z:
            if 0 <= k < self.Y:
                return int(self.vox[x, z, k])
            return M.AIR if k >= self.Y else M.ID["rock"]
        return M.ID["rock"] if k < self.sea else M.AIR

    def mat(self, x, k, z):
        return M.VOXELS[self.get(x, k, z)]

    def set(self, x, k, z, vid):
        """Change one voxel and queue the physics that follows from it."""
        if not self.inside(x, k, z):
            return False
        old = int(self.vox[x, z, k])
        if old == vid:
            return False
        self.vox[x, z, k] = vid
        self._retop(x, z)
        self.touch(x, z)
        self.changes.append((x, k, z, old, vid))
        return True

    def _retop(self, x, z):
        col = self.t["solid"][self.vox[x, z]]
        nz = np.flatnonzero(col)
        self.top[x, z] = nz[-1] if nz.size else -1

    def rebuild_top(self):
        solid = self.t["solid"][self.vox]
        any_solid = solid.any(axis=2)
        self.top = np.where(any_solid, self.Y - 1 - np.argmax(solid[:, :, ::-1], axis=2), -1).astype(np.int16)

    def touch(self, x, z):
        """Mark the chunk (and neighbours, at a border) as changed for the viewer."""
        self.rev += 1
        cx, cz = x // CHUNK, z // CHUNK
        self.chunk_rev[cx, cz] = self.rev
        if x % CHUNK == 0 and cx > 0:
            self.chunk_rev[cx - 1, cz] = self.rev
        if x % CHUNK == CHUNK - 1 and cx + 1 < self.chunk_rev.shape[0]:
            self.chunk_rev[cx + 1, cz] = self.rev
        if z % CHUNK == 0 and cz > 0:
            self.chunk_rev[cx, cz - 1] = self.rev
        if z % CHUNK == CHUNK - 1 and cz + 1 < self.chunk_rev.shape[1]:
            self.chunk_rev[cx, cz + 1] = self.rev

    def surface(self, x, z):
        """Layer of the highest solid voxel in a column (-1 if none)."""
        return int(self.top[x, z]) if 0 <= x < self.X and 0 <= z < self.Z else -1

    def exposed(self, x, k, z):
        """True if nothing solid is above this voxel (open to sky and rain)."""
        return self.surface(x, z) <= k

    # --- items -----------------------------------------------------------------
    def new_item(self, kind, mat=None, mass=None, pos=None, **props):
        k = KINDS.get(kind, {})
        if mat is None:
            mat = k.get("mat", "steel")
        if mass is None:
            mass = k.get("mass", 1.0)
        for key in ("cap_kwh", "cap_l", "wire_m"):
            if key in k and key not in props:
                props[key] = k[key]
        it = Item(self._next_item, kind, mat, mass, **props)
        self._next_item += 1
        self.items[it.id] = it
        if pos is not None:
            self.put(it, pos)
        self.mark(it)
        return it

    def mark(self, it):
        self.rev += 1
        it.rev = self.rev

    def put(self, it, pos):
        """Place an item in the world at pos (it then settles under gravity)."""
        self.lift(it)
        it.holder = it.inside = None
        it.pos = tuple(int(c) for c in pos)
        self.items_at.setdefault(it.pos, set()).add(it.id)
        self.settle(it)
        self.mark(it)

    def lift(self, it):
        """Take an item out of the world index (it is being carried or stored)."""
        if it.pos is not None:
            s = self.items_at.get(it.pos)
            if s:
                s.discard(it.id)
                if not s:
                    del self.items_at[it.pos]
            it.pos = None

    def remove(self, it):
        self.lift(it)
        if it.holder is not None:
            g = self.giants.get(it.holder)
            if g and it.id in g.carrying:
                g.carrying.remove(it.id)
        if it.inside is not None:
            c = self.items.get(it.inside)
            if c and it.id in c.props.get("stored", []):
                c.props["stored"].remove(it.id)
        self.burning_items.discard(it.id)
        self.items.pop(it.id, None)
        self.rev += 1
        self.removed_items.append((self.rev, it.id))
        self.links = [l for l in self.links if l[0] != it.id and l[1] != it.id]

    def settle(self, it):
        """Let an item fall until it rests on something solid (or floats)."""
        x, k, z = it.pos
        if not self.inside(x, k, z):
            x, z = min(max(x, 0), self.X - 1), min(max(z, 0), self.Z - 1)
            k = min(max(k, 1), self.Y - 1)
        solid, liquid = self.t["solid"], self.t["liquid"]
        col = self.vox[x, z]
        while k < self.Y - 1 and solid[col[k]]:
            k += 1                              # pushed up out of solid
        floats = it.sub.density < 1.0 and not it.props.get("contents")
        while k > 0 and not solid[col[k - 1]]:
            if liquid[col[k - 1]] and floats:
                break
            k -= 1
        if (x, k, z) != it.pos:
            s = self.items_at.get(it.pos)
            if s:
                s.discard(it.id)
                if not s:
                    del self.items_at[it.pos]
            it.pos = (x, k, z)
            self.items_at.setdefault(it.pos, set()).add(it.id)
        if it.bulk:
            self.merge_bulk(it)

    def merge_bulk(self, it):
        """Loose material of the same substance in one place is one pile."""
        for oid in list(self.items_at.get(it.pos, ())):
            o = self.items.get(oid)
            if o and o is not it and o.bulk and o.mat == it.mat and not o.props.get("burning") \
                    and not it.props.get("burning"):
                it.mass += o.mass
                it.props["temp"] = max(it.props.get("temp", 15), o.props.get("temp", 15))
                self.remove(o)
        self.mark(it)

    def add_bulk(self, mat, kg, pos, **props):
        if kg <= 0.5:
            return None
        return self.new_item("bulk", mat, kg, pos, **props)

    def items_near(self, x, k, z, r, dk=3):
        out = []
        for (ix, ik, iz), ids in self.items_at.items():
            if abs(ix - x) <= r and abs(iz - z) <= r and abs(ik - k) <= dk:
                out.extend(self.items[i] for i in ids)
        return out

    # --- events ------------------------------------------------------------------
    def emit(self, kind, text, pos=None, radius=0, to=None, data=None):
        """Record something that happened and tell every giant who could perceive it."""
        ev = {"t": self.tick, "type": kind, "text": text}
        if pos is not None:
            ev["at"] = [int(pos[0]), int(pos[1]) - self.sea, int(pos[2])]
        if data:
            ev.update(data)
        self.log.append(ev)
        for g in self.giants.values():
            if to is not None:
                if g.id in to:
                    g.inbox.append(ev)
            elif pos is not None and g.status != "destroyed":
                if max(abs(g.x - pos[0]), abs(g.z - pos[2])) <= radius:
                    g.inbox.append(ev)
        return ev

    # --- time and weather ----------------------------------------------------------
    def day_fraction(self):
        return (START_CLOCK + self.tick / DAY_TICKS) % 1.0

    def clock(self):
        f = self.day_fraction() * 24
        return f"day {1 + int(START_CLOCK + self.tick / DAY_TICKS)}, {int(f):02d}:{int(f % 1 * 60):02d}"

    def daylight(self):
        """0 at night, up to 1 at noon."""
        return max(0.0, math.sin((self.day_fraction() - 0.25) * 2 * math.pi))

    def weather_tick(self):
        r = self.rng
        a = math.atan2(self.wind[1], self.wind[0]) + r.uniform(-0.3, 0.3)
        self.wind = [math.cos(a), math.sin(a), min(1.0, max(0.0, self.wind[2] + r.uniform(-0.1, 0.1)))]
        if self.raining > 0:
            self.raining -= 60
            self.dryness = max(0.1, self.dryness - 0.05)
            if self.raining <= 0:
                self.emit("weather", "The rain has stopped.", to=list(self.giants))
        else:
            self.dryness = min(1.0, self.dryness + 0.004)
            if r.random() < 0.008:
                self.raining = r.randint(300, 1500)
                self.emit("weather", "It has started to rain.", to=list(self.giants))

    def wind_name(self):
        dx, dz, s = self.wind
        # Wind blows *towards* (dx, dz); name the direction it comes from.
        names = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
        i = int(round(math.atan2(dz, dx) / (math.pi / 4))) % 8
        word = "calm" if s < 0.15 else ("light" if s < 0.4 else ("fresh" if s < 0.7 else "strong"))
        return f"{word} from the {names[i]}" if s >= 0.15 else "calm"
