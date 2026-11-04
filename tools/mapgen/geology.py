"""Worldwide geology layers for resource placement.

* Bedrock: Macrostrat "carto" vector tiles (CC-BY 4.0). Zoom 8 gives global
  coverage (compiled from global lithology maps); zoom 12 adds detailed
  national maps where Macrostrat has them (e.g. BGS in Great Britain, USGS
  state maps in the USA). Each map unit's free-text lithology is classified
  into a small set of rock classes the game understands.
* Soil: SoilGrids 2.0 (ISRIC, CC-BY 4.0), 250 m global predictions of clay and
  sand content at 15-30 cm depth, fetched from the ISRIC WCS service.

Either source may be unavailable for a location; the layers then stay at
"unknown" / 0 and the game falls back to land cover.
"""

import math
import os
import re
from io import BytesIO

import numpy as np
from PIL import Image

import mvt

MACROSTRAT_URL = "https://tiles.macrostrat.org/carto/{z}/{x}/{y}.mvt"
SOILGRIDS_URL = ("https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1"
                 "&REQUEST=GetCoverage&COVERAGEID={prop}_15-30cm_mean&FORMAT=GEOTIFF_INT16"
                 "&SUBSET=long({w:.5f},{e:.5f})&SUBSET=lat({s:.5f},{n:.5f})"
                 "&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
                 "&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
                 "&SCALESIZE=long({nx}),lat({ny})")
SOIL_STEP = 0.0025  # degrees; requests snap to this global lattice so overlapping regions match
BEDROCK_ZOOMS = (8, 12)  # coarse global first, detail painted over it

# Rock classes: (name, preview colour). Index = value in the game's rock lookup.
ROCKS = [
    ("unknown", "#9a9a9a"),
    ("carbonate", "#e9e4cf"),     # chalk, limestone, dolomite, marl
    ("sandstone", "#d9b77a"),     # sandstone, conglomerate, grit, breccia
    ("mudstone", "#a8806a"),      # mudstone, shale, siltstone, claystone
    ("sediment", "#cdbb8f"),      # loose sand, gravel, clay, alluvium, till
    ("igneous", "#8c6f78"),       # granite, basalt, tuff, volcanic, plutonic
    ("metamorphic", "#7d8796"),   # schist, gneiss, slate, quartzite, marble
]
R = {name: i for i, (name, _c) in enumerate(ROCKS)}

# First matching keyword (by position in the description) decides the class.
KEYWORDS = [
    (r"chalk|limestone|dolomite|dolostone|marl|carbonate", "carbonate"),
    (r"sandstone|conglomerate|gritstone|\bgrit\b|breccia|arkose|greywacke|graywacke", "sandstone"),
    (r"mudstone|claystone|shale|siltstone|argillaceous|argillite|\bclay\b|\bsilt\b", "mudstone"),
    (r"alluvi|gravel|\bsand\b|\btill\b|deposits|sediments?\b|terrace|levee|peat|loess|unconsolidated",
     "sediment"),
    (r"basalt|granite|tuff|andesite|rhyolite|gabbro|diorite|syenite|volcanic|plutonic|igneous|lava|"
     r"pyroclastic|dolerite|obsidian", "igneous"),
    (r"schist|gneiss|slate|marble|quartzite|phyllite|metamorphic|migmatite|hornfels|amphibolite", "metamorphic"),
]
TYPE_FALLBACK = {
    "carbonate": "carbonate", "siliciclastic": "sandstone", "sedimentary": "sediment",
    "organic": "mudstone", "volcanic": "igneous", "plutonic": "igneous", "igneous": "igneous",
    "metamorphic": "metamorphic", "metasedimentary": "metamorphic", "metaigneous": "metamorphic",
}


def classify(lith, lith_class, lith_type):
    text = (lith or "").lower()
    # "clay, silt, sand and gravel": loose mixed deposits, not mudstone.
    if re.search(r"\bclay\b|\bsilt\b", text) and re.search(r"\bsand\b|gravel", text) and "stone" not in text:
        return R["sediment"]
    best = None
    for pattern, rock in KEYWORDS:
        m = re.search(pattern, text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), rock)
    if best:
        return R[best[1]]
    for key in (lith_type, lith_class):
        if key and key.lower() in TYPE_FALLBACK:
            return R[TYPE_FALLBACK[key.lower()]]
    return R["unknown"]


def bedrock(grid, rasterizer_cls, http_get, cache_dir, log):
    """Return (unit index layer uint8, units list). Unit 0 = no data."""
    units = [{"name": "", "lith": "", "rock": "unknown", "age": ""}]
    index = {}
    layer = np.zeros((grid.height, grid.width), np.uint8)
    r = rasterizer_cls(grid)
    fetched = 0
    for z in BEDROCK_ZOOMS:
        for tx, ty in grid.tiles(z):
            try:
                data = http_get(MACROSTRAT_URL.format(z=z, x=tx, y=ty),
                                os.path.join(cache_dir, "macrostrat", str(z), str(tx), f"{ty}.mvt"))
            except Exception as e:  # service down: keep what we have
                log(f"  Macrostrat tile {z}/{tx}/{ty} failed: {e}")
                continue
            fetched += 1
            layers = mvt.decode(data, {"units"}) if data else {}
            u = layers.get("units")
            if not u:
                continue
            r.set_tile(tx, ty, u.extent, zoom=z)
            for f in u.features:
                if f.type != mvt.POLYGON:
                    continue
                t = f.tags
                key = (t.get("name") or "", t.get("lith") or "")
                if key not in index:
                    if len(units) >= 255:
                        continue
                    rock = classify(t.get("lith"), t.get("lith_class1"), t.get("lith_type1"))
                    index[key] = len(units)
                    units.append({"name": key[0], "lith": key[1], "rock": ROCKS[rock][0],
                                  "age": t.get("age") or ""})
                r.fill(f, index[key], min_area=0.0, target=layer)
    log(f"Bedrock: {fetched} Macrostrat tiles, {len(units) - 1} map units, "
        f"{100.0 * (layer > 0).mean():.0f}% coverage")
    return layer, units


def _read_geotiff(data):
    """Single-band GeoTIFF -> (array, west, north, dx, dy) using Pillow only."""
    im = Image.open(BytesIO(data))
    arr = np.array(im).astype(np.float32)
    sx, sy = im.tag_v2[33550][:2]  # ModelPixelScale
    tie = im.tag_v2[33922]  # ModelTiepoint: i, j, k, x, y, z
    return arr, tie[3] - tie[0] * sx, tie[4] + tie[1] * sy, sx, sy


def soil(grid, http_get, cache_dir, log):
    """Return (clay %, sand %) uint8 layers sampled at cell centres (0 = no data)."""
    lons, lats = grid.cell_lonlats()
    st = SOIL_STEP
    i0, i1 = math.floor(grid.west / st) - 1, math.ceil(grid.east / st) + 1
    j0, j1 = math.floor(grid.south / st) - 1, math.ceil(grid.north / st) + 1
    out = []
    for prop in ("clay", "sand"):
        url = SOILGRIDS_URL.format(prop=prop, w=i0 * st, e=i1 * st, s=j0 * st, n=j1 * st,
                                   nx=i1 - i0, ny=j1 - j0)
        name = f"{prop}_{i0}_{j0}_{i1}_{j1}.tif"
        try:
            data = http_get(url, os.path.join(cache_dir, "soilgrids", name))
            arr = _read_geotiff(data)[0]
        except Exception as e:
            log(f"  SoilGrids {prop} unavailable ({e}); using land cover only")
            out.append(np.zeros((grid.height, grid.width), np.uint8))
            continue
        # Index on the global lattice (not the returned float origin) for exactness.
        cols = np.clip(np.floor(lons / st).astype(int) - i0, 0, arr.shape[1] - 1)
        rows = np.clip(j1 - 1 - np.floor(lats / st).astype(int), 0, arr.shape[0] - 1)
        v = arr[np.ix_(rows, cols)]  # g/kg
        v[(v < 0) | (v > 1000)] = 0
        out.append(np.clip(np.round(v / 10.0), 0, 100).astype(np.uint8))
    valid = out[0] > 0
    log(f"Soil: SoilGrids clay/sand, {100.0 * valid.mean():.0f}% coverage, "
        f"median clay {np.median(out[0][valid]) if valid.any() else 0:.0f}%")
    return out[0], out[1]
