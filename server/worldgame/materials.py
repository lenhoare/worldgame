"""Substances and voxel materials.

Nothing in the game is a hard-coded recipe. Every substance has physical
properties (density, hardness, melting point, flammability, energy content,
conductivity...) and the simulation's generic processes act on those
properties. A voxel material is a substance arranged as a structure (a brick
wall is bricks at 20 % fill with a one-voxel span).

Units: density t/m3, temperatures deg C, energy kWh per tonne, hardness on a
0-10 scratch scale (2 wood, 3.5 brick, 5 concrete, 6.5 steel, 7 flint).
"""

from dataclasses import dataclass, field

AIR = 0

# ---------------------------------------------------------------------------
# Substances
# ---------------------------------------------------------------------------
# name: (density, hardness, melt, flammability, energy_kwh_t, colour, flags, heat_to)
#   flags: g granular, l liquid, c conducts electricity, d ductile (metal),
#          b brittle, f fibrous, t transparent, o organic, s stone, m mouldable when wet
#   heat_to: (temperature, product) transformation when held at that temperature
_S = {
    "water":      (1.00, 0, 0,    0.0, 0,    "#4fa8d8", "l", (100, "steam")),
    "seawater":   (1.03, 0, 0,    0.0, 0,    "#3f86ad", "l", (100, "salt")),
    "fuel":       (0.75, 0, -50,  1.0, 3500, "#d9b23a", "l", None),
    "soil":       (1.50, 1.0, 0,  0.0, 0,    "#6b4f36", "g", None),
    "clay":       (1.80, 1.5, 0,  0.0, 0,    "#b0683f", "gm", (950, "ceramic")),
    "sand":       (1.60, 1.0, 1700, 0.0, 0,  "#e2cf8e", "g", (1500, "glass")),
    "gravel":     (1.70, 1.5, 0,  0.0, 0,    "#b9b0a0", "gs", None),
    "chalk":      (1.90, 2.5, 0,  0.0, 0,    "#efeadb", "s", (900, "lime")),
    "flint":      (2.60, 7.0, 0,  0.0, 0,    "#5b5e66", "sb", None),
    "sandstone":  (2.30, 5.0, 0,  0.0, 0,    "#cfa868", "s", None),
    "mudstone":   (2.40, 3.0, 0,  0.0, 0,    "#8a7466", "s", (1000, "ceramic")),
    "basalt":     (2.90, 6.5, 1200, 0.0, 0,  "#4d4a52", "s", None),
    "slate":      (2.70, 5.5, 0,  0.0, 0,    "#5d6875", "sb", None),
    "rock":       (2.60, 5.0, 0,  0.0, 0,    "#8d8d8d", "s", None),
    "rubble":     (1.70, 3.0, 0,  0.0, 0,    "#a59a8c", "g", None),
    "concrete":   (2.40, 5.0, 0,  0.0, 0,    "#b5b1a8", "s", None),
    "asphalt":    (2.30, 3.0, 0,  0.15, 300, "#55565a", "", None),
    "brick":      (1.90, 3.5, 0,  0.0, 0,    "#b4563c", "sb", None),
    "tile":       (1.90, 3.5, 0,  0.0, 0,    "#a8573c", "sb", None),
    "ceramic":    (2.00, 4.5, 1800, 0.0, 0,  "#c98a5e", "sb", None),
    "lime":       (1.00, 1.5, 0,  0.0, 0,    "#f4f1e6", "g", None),   # quicklime: + water + sand -> mortar
    "mortar":     (1.90, 2.0, 0,  0.0, 0,    "#cfc8b8", "g", None),
    "glass":      (2.50, 5.5, 1000, 0.0, 0,  "#a9e6e0", "bt", None),
    "steel":      (7.85, 6.5, 1500, 0.0, 0,  "#8b98a8", "cd", None),
    "copper":     (8.96, 3.0, 1085, 0.0, 0,  "#d98345", "cd", None),
    "aluminium":  (2.70, 2.8, 660, 0.0, 0,   "#cdd3d8", "cd", None),
    "lead":       (11.3, 1.5, 327, 0.0, 0,   "#6f7480", "cd", None),
    "wood":       (0.60, 2.0, 0,  0.7, 150,  "#8a5a32", "of", (400, "charcoal")),
    "charcoal":   (0.30, 1.0, 0,  0.9, 420,  "#2b2a2c", "ob", None),
    "biomass":    (0.30, 0.5, 0,  0.6, 90,   "#6fb04a", "of", None),
    "fibre":      (0.30, 0.5, 0,  0.8, 100,  "#c9b26a", "of", None),
    "fabric":     (0.40, 0.5, 0,  0.8, 120,  "#9a6fa8", "of", None),
    "plastic":    (0.95, 1.5, 200, 0.7, 300, "#e0609e", "", None),
    "rubber":     (1.10, 1.0, 0,  0.6, 280,  "#2f3034", "", None),
    "electronics": (2.00, 2.0, 0, 0.2, 0,    "#3fd27f", "c", None),
    "ash":        (0.60, 0.5, 0,  0.0, 0,    "#9b9b96", "g", None),   # a flux: lowers the glass temperature
    "salt":       (2.10, 2.0, 801, 0.0, 0,   "#f7f7f2", "g", None),
    "steam":      (0.00, 0, 0,    0.0, 0,    "#ffffff", "", None),
}


@dataclass(frozen=True)
class Substance:
    name: str
    density: float
    hardness: float
    melt: float
    flammability: float
    energy: float
    colour: str
    flags: str
    heat_to: tuple | None

    def has(self, flag):
        return flag in self.flags

    @property
    def metal(self):
        return "d" in self.flags

    def describe(self):
        words = {"g": "granular", "l": "liquid", "c": "conducts electricity", "d": "ductile metal",
                 "b": "brittle", "f": "fibrous", "t": "transparent", "o": "organic", "s": "stone",
                 "m": "mouldable when wet"}
        d = {"density_t_m3": self.density, "hardness": self.hardness,
             "traits": [words[f] for f in self.flags]}
        if self.melt > 0:
            d["melts_at_c"] = self.melt
        if self.flammability > 0:
            d["flammability"] = self.flammability
            d["fuel_energy_kwh_per_t"] = self.energy
        if self.heat_to:
            d["when_heated"] = f"becomes {self.heat_to[1]} at {self.heat_to[0]} C"
        return d


SUBSTANCES = {n: Substance(n, *v) for n, v in _S.items()}


# ---------------------------------------------------------------------------
# Voxel materials
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Voxel:
    id: int
    name: str
    substance: str
    kind: str            # air | solid | granular | liquid | foliage
    fill: float          # fraction of the voxel that is material (buildings are mostly air)
    hardness: float
    work: float          # seconds to break one voxel with a tool of matching power
    span: int            # how many voxels it can cantilever sideways from support
    flammability: float
    fuel: float          # seconds one voxel burns
    burn_to: str         # voxel left after burning ("air" for nothing)
    colour: str
    natural: bool        # natural ground: anchors structures
    yields: tuple = ()   # ((substance, fraction of mass), ...)
    loot: str = ""       # loot table rolled when broken (interiors)
    tags: tuple = ()

    @property
    def solid(self):
        return self.kind in ("solid", "granular")

    @property
    def passable(self):
        return self.kind in ("air", "foliage", "liquid")

    def mass(self, voxel_m3):
        """Kilograms of material in one voxel."""
        return SUBSTANCES[self.substance].density * 1000.0 * self.fill * voxel_m3


def _v(name, substance, kind, fill, hardness, work, span, flam, fuel, burn_to, colour=None,
       natural=False, yields=(), loot="", tags=()):
    return dict(name=name, substance=substance, kind=kind, fill=fill, hardness=hardness, work=work,
                span=span, flammability=flam, fuel=fuel, burn_to=burn_to,
                colour=colour or SUBSTANCES[substance].colour, natural=natural,
                yields=tuple(yields), loot=loot, tags=tuple(tags))


_VOXELS = [
    _v("air", "steam", "air", 0, 0, 0, 0, 0, 0, "air", "#000000"),
    _v("seawater", "seawater", "liquid", 1, 0, 0, 0, 0, 0, "air", tags=("water", "source")),
    _v("water", "water", "liquid", 1, 0, 0, 0, 0, 0, "air", tags=("water",)),
    # --- natural ground ---
    _v("turf", "soil", "granular", 1, 1.0, 14, 0, 0.25, 20, "soil", "#86b85a", True,
       [("soil", 0.95), ("biomass", 0.05)]),
    _v("soil", "soil", "granular", 1, 1.0, 14, 0, 0, 0, "air", None, True, [("soil", 1)]),
    _v("farm_soil", "soil", "granular", 1, 0.8, 12, 0, 0.3, 20, "soil", "#b99c5a", True,
       [("soil", 0.93), ("biomass", 0.07)]),
    _v("clay", "clay", "granular", 1, 1.5, 20, 0, 0, 0, "air", None, True, [("clay", 1)]),
    _v("sand", "sand", "granular", 1, 1.0, 10, 0, 0, 0, "air", None, True, [("sand", 1)]),
    _v("gravel", "gravel", "granular", 1, 1.5, 14, 0, 0, 0, "air", None, True,
       [("gravel", 0.97), ("flint", 0.03)]),
    _v("chalk", "chalk", "solid", 1, 2.5, 30, 2, 0, 0, "air", None, True,
       [("chalk", 0.96), ("flint", 0.04)]),
    _v("sandstone", "sandstone", "solid", 1, 5.0, 70, 3, 0, 0, "air", None, True, [("sandstone", 1)]),
    _v("mudstone", "mudstone", "solid", 1, 3.0, 40, 2, 0, 0, "air", None, True, [("mudstone", 1)]),
    _v("basalt", "basalt", "solid", 1, 6.5, 110, 4, 0, 0, "air", None, True, [("basalt", 1)]),
    _v("slate", "slate", "solid", 1, 5.5, 80, 3, 0, 0, "air", None, True, [("slate", 1)]),
    _v("rock", "rock", "solid", 1, 5.0, 70, 3, 0, 0, "air", None, True, [("rock", 1)]),
    # --- made ground ---
    _v("asphalt", "asphalt", "solid", 0.3, 3.0, 18, 1, 0.1, 60, "rubble", None, True,
       [("asphalt", 0.6), ("gravel", 0.4)], tags=("road",)),
    _v("paving", "concrete", "solid", 0.3, 4.0, 22, 1, 0, 0, "air", "#c2bdb1", True,
       [("concrete", 0.7), ("gravel", 0.3)], tags=("road",)),
    _v("ballast", "gravel", "granular", 1, 1.5, 14, 0, 0, 0, "air", "#8f867c", True, [("gravel", 1)]),
    # --- buildings ---
    _v("brick_wall", "brick", "solid", 0.20, 3.5, 20, 1, 0, 0, "air", None, False,
       [("brick", 0.75), ("rubble", 0.25)], tags=("wall",)),
    _v("concrete_wall", "concrete", "solid", 0.25, 5.0, 45, 3, 0, 0, "air", "#b9b4aa", False,
       [("concrete", 0.9), ("steel", 0.1)], tags=("wall",)),
    _v("steel_frame", "steel", "solid", 0.012, 6.0, 40, 5, 0, 0, "air", "#9aa4ae", False,
       [("steel", 1)], tags=("wall",)),
    _v("glass_wall", "glass", "solid", 0.06, 5.5, 8, 2, 0, 0, "air", "#9fd3dc", False,
       [("glass", 0.6), ("aluminium", 0.2), ("steel", 0.2)], tags=("wall", "window")),
    _v("roof_tile", "tile", "solid", 0.05, 2.5, 10, 2, 0.3, 90, "air", "#a8573c", False,
       [("tile", 0.5), ("wood", 0.5)], loot="roof", tags=("roof",)),
    _v("roof_metal", "steel", "solid", 0.006, 4.0, 14, 4, 0, 0, "air", "#7f8c96", False,
       [("steel", 0.8), ("aluminium", 0.2)], loot="roof_big", tags=("roof",)),
    _v("interior_home", "wood", "solid", 0.05, 2.0, 12, 1, 0.6, 120, "air", "#c8b79a", False,
       loot="home", tags=("interior",)),
    _v("interior_shop", "plastic", "solid", 0.04, 2.0, 12, 1, 0.6, 120, "air", "#c9a9a0", False,
       loot="shop", tags=("interior",)),
    _v("interior_industrial", "steel", "solid", 0.008, 3.0, 16, 1, 0.3, 80, "air", "#a59fa6", False,
       loot="industrial", tags=("interior",)),
    _v("interior_medical", "plastic", "solid", 0.04, 2.0, 12, 1, 0.5, 100, "air", "#d6dfe2", False,
       loot="medical", tags=("interior",)),
    _v("interior_garage", "steel", "solid", 0.008, 3.0, 14, 1, 0.5, 80, "air", "#8e8a86", False,
       loot="garage", tags=("interior",)),
    # --- vegetation ---
    _v("wood", "wood", "solid", 0.15, 2.0, 16, 3, 0.7, 240, "air", None, False, [("wood", 1)],
       tags=("tree",)),
    _v("leaves", "biomass", "foliage", 0.05, 0.3, 4, 1, 0.9, 25, "air", "#4f8a4e", False,
       [("biomass", 0.8), ("fibre", 0.2)], tags=("tree",)),
    _v("shrub", "biomass", "foliage", 0.04, 0.3, 4, 0, 0.8, 25, "air", "#7c9a52", False,
       [("biomass", 0.6), ("fibre", 0.4)]),
    # --- things giants build or leave behind ---
    _v("timber", "wood", "solid", 0.30, 2.0, 14, 3, 0.7, 300, "air", "#a8763f", False, [("wood", 1)],
       tags=("built",)),
    _v("rubble", "rubble", "granular", 0.6, 3.0, 12, 0, 0, 0, "air", None, False, [("rubble", 1)]),
    _v("masonry", "brick", "solid", 0.6, 3.5, 24, 1, 0, 0, "air", "#b0664e", False, [("brick", 1)],
       tags=("built", "wall")),
    _v("stonework", "rock", "solid", 0.6, 4.5, 40, 1, 0, 0, "air", "#9c978d", False, [("rock", 1)],
       tags=("built", "wall")),
    _v("mortared_wall", "brick", "solid", 0.6, 4.0, 40, 3, 0, 0, "air", "#b97a62", False,
       [("brick", 0.7), ("rubble", 0.3)], tags=("built", "wall")),
    _v("concrete", "concrete", "solid", 0.8, 5.5, 90, 4, 0, 0, "air", "#aaa69d", False,
       [("concrete", 1)], tags=("built",)),
    _v("steel_plate", "steel", "solid", 0.03, 6.5, 60, 6, 0, 0, "air", "#76838f", False, [("steel", 1)],
       tags=("built", "wall")),
    _v("glass", "glass", "solid", 0.1, 5.5, 6, 1, 0, 0, "air", None, False, [("glass", 1)],
       tags=("built", "window")),
    _v("ceramic", "ceramic", "solid", 0.9, 4.5, 50, 2, 0, 0, "air", None, False, [("ceramic", 1)],
       tags=("built",)),
    _v("charcoal", "charcoal", "granular", 0.5, 1.0, 6, 0, 0.9, 400, "ash", None, False,
       [("charcoal", 1)]),
    _v("ash", "ash", "granular", 0.3, 0.5, 4, 0, 0, 0, "air", None, False, [("ash", 1)]),
    _v("lime", "lime", "granular", 0.6, 1.5, 8, 0, 0, 0, "air", None, False, [("lime", 1)]),
]

VOXELS = [Voxel(id=i, **d) for i, d in enumerate(_VOXELS)]
V = {v.name: v for v in VOXELS}
ID = {v.name: v.id for v in VOXELS}
assert VOXELS[AIR].name == "air" and len(VOXELS) < 255

# What loose (bulk) substances become when stacked into a voxel with `place`.
PLACE_AS = {
    "soil": "soil", "clay": "clay", "sand": "sand", "gravel": "gravel", "rubble": "rubble",
    "chalk": "stonework", "sandstone": "stonework", "mudstone": "stonework", "basalt": "stonework",
    "slate": "stonework", "rock": "stonework", "flint": "stonework", "concrete": "rubble",
    "asphalt": "rubble", "brick": "masonry", "tile": "masonry", "ceramic": "ceramic",
    "wood": "timber", "steel": "steel_plate", "glass": "glass", "charcoal": "charcoal",
    "ash": "ash", "lime": "lime", "mortar": "concrete",
}

# Heat applied to a voxel in place (kiln walls, scorched ground).
VOXEL_HEAT_TO = {"clay": (950, "ceramic"), "chalk": (900, "lime"), "sand": (1500, "glass"),
                 "turf": (300, "soil"), "farm_soil": (300, "soil")}


def numpy_tables():
    """Lookup arrays indexed by voxel id, for vectorised code."""
    import numpy as np
    n = len(VOXELS)
    t = {
        "solid": np.array([v.solid for v in VOXELS], bool),
        "passable": np.array([v.passable for v in VOXELS], bool),
        "liquid": np.array([v.kind == "liquid" for v in VOXELS], bool),
        "granular": np.array([v.kind == "granular" for v in VOXELS], bool),
        "natural": np.array([v.natural for v in VOXELS], bool),
        "flammable": np.array([v.flammability > 0 for v in VOXELS], bool),
        "colour": np.array([[int(v.colour[i:i + 2], 16) for i in (1, 3, 5)] for v in VOXELS], np.uint8),
    }
    assert all(len(a) == n for a in t.values())
    return t
