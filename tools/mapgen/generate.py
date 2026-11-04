#!/usr/bin/env python3
"""WorldGame region generator.

Turns a postcode (or a lon/lat bounding box) into compact grid layers that the
Godot landscape loads:

    height.bin.gz     float16 terrain height in metres (row 0 = north edge)
    cover.bin.gz      uint8 land-cover class per cell (see CLASSES)
    buildings.bin.gz  uint8 pairs: building height in metres, roof variant
    meta.json         grid geometry, classes, palette, resources, attribution

Data sources (all open, attribution required, see meta.json):
  * OpenFreeMap vector tiles (OpenMapTiles schema, (c) OpenStreetMap contributors)
  * Mapzen/AWS Terrain Tiles (Terrarium encoding)
  * postcodes.io (UK postcode lookup, OS/ONS open data)

Example (the Brighton - Worthing prototype region):

    python3 tools/mapgen/generate.py --postcode "BN15 8EU" \
        --bbox -0.43,50.795,-0.085,50.92 --name brighton_worthing
"""

import argparse
import gzip
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mvt  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
USER_AGENT = "worldgame-mapgen/0.1 (+https://github.com/lenhoare/worldgame)"

VECTOR_ZOOM = 14
ELEVATION_ZOOM = 12
EARTH_CIRCUMFERENCE = 40075016.686
OPENFREEMAP_TILEJSON = "https://tiles.openfreemap.org/planet"
TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
POSTCODE_URL = "https://api.postcodes.io/postcodes/{}"

# ---------------------------------------------------------------------------
# Land-cover classes. Index = value stored in cover.bin. Colours are the
# "Day" pixel palette; resources are (biomass, water, metal, energy) per cell
# and are a first sketch of the game economy.
# ---------------------------------------------------------------------------
CLASSES = [
    # name,        colour,    biomass, water, metal, energy
    ("sea",        "#3f7f9e", 0, 1, 0, 1),
    ("beach",      "#d9c99a", 0, 0, 1, 0),
    ("water",      "#4f93ab", 0, 3, 0, 0),
    ("urban",      "#b9b2a2", 0, 0, 1, 1),
    ("commercial", "#c4a99a", 0, 0, 1, 2),
    ("industrial", "#a39da3", 0, 0, 3, 1),
    ("park",       "#7fb267", 2, 0, 0, 0),
    ("grass",      "#9cbd6e", 1, 0, 0, 0),
    ("farmland",   "#c9c27a", 3, 0, 0, 0),
    ("wood",       "#4f8a4e", 4, 0, 0, 0),
    ("scrub",      "#8a9f5c", 1, 0, 0, 0),
    ("wetland",    "#7fa58f", 1, 2, 0, 0),
    ("bare",       "#c7bfae", 0, 0, 2, 0),
    ("golf",       "#8fc46f", 1, 0, 0, 0),
    ("path",       "#d3c4a0", 0, 0, 0, 0),
    ("rail",       "#7c6f68", 0, 0, 2, 1),
    ("road",       "#e6e0d0", 0, 0, 0, 0),
    ("road_major", "#f0d48a", 0, 0, 0, 0),
    ("runway",     "#8c8c8c", 0, 0, 1, 1),
    ("pier",       "#9c7a5a", 0, 0, 1, 0),
    ("building",   "#a8a097", 0, 0, 2, 2),
]
C = {name: i for i, (name, *_rest) in enumerate(CLASSES)}

ROOF_COLOURS = [
    "#b5654a",  # terracotta tiles
    "#6e7a86",  # slate
    "#4f5866",  # dark slate
    "#d9c9a3",  # cream
    "#e8e4da",  # white render
    "#9a8f86",  # warm grey
    "#7f9c96",  # weathered copper
    "#8b6a52",  # brown tiles
]

LANDUSE = {
    "residential": "urban", "suburb": "urban", "quarter": "urban",
    "neighbourhood": "urban", "garages": "urban", "school": "urban",
    "university": "urban", "college": "urban", "kindergarten": "urban",
    "hospital": "urban", "library": "urban", "bus_station": "commercial",
    "commercial": "commercial", "retail": "commercial",
    "industrial": "industrial", "railway": "industrial", "dam": "industrial",
    "military": "bare", "quarry": "bare",
    "cemetery": "park", "stadium": "park", "pitch": "park",
    "playground": "park", "track": "park", "theme_park": "park", "zoo": "park",
}

LANDCOVER_SUBCLASS = {
    "park": "park", "recreation_ground": "park", "village_green": "park",
    "garden": "park", "allotments": "park", "golf_course": "golf",
    "grass": "grass", "grassland": "grass", "meadow": "grass",
    "heath": "scrub", "scrub": "scrub", "fell": "scrub",
    "beach": "beach", "sand": "beach", "dune": "beach",
    "bare_rock": "bare", "scree": "bare",
}
LANDCOVER_CLASS = {
    "farmland": "farmland", "wood": "wood", "grass": "grass",
    "wetland": "wetland", "sand": "beach", "rock": "bare", "ice": "bare",
}

# Line features: (class, width in cells). Drawn in this order, later wins.
ROAD_STYLE = {
    "path": ("path", 1), "track": ("path", 1), "service": ("road", 1),
    "minor": ("road", 1), "tertiary": ("road", 1), "secondary": ("road", 2),
    "primary": ("road_major", 2), "trunk": ("road_major", 2),
    "motorway": ("road_major", 3),
    "rail": ("rail", 1), "transit": ("rail", 1),
    "pier": ("pier", 1),
}
ROAD_ORDER = ["path", "track", "service", "minor", "rail", "transit",
              "tertiary", "secondary", "primary", "trunk", "motorway", "pier"]
WATERWAY_WIDTH = {"river": 2, "canal": 2, "stream": 1}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def log(msg):
    print(msg, flush=True)


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def http_get(url, cache_path=None, retries=4):
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    delay = 2
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries:
                raise
        time.sleep(delay)
        delay *= 2
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(data)
    return data


def lookup_postcode(postcode):
    pc = postcode.replace(" ", "").upper()
    data = http_get(POSTCODE_URL.format(urllib.parse.quote(pc)))
    if data is None:
        sys.exit(f"Postcode {postcode!r} not found (postcodes.io covers the UK).")
    result = json.loads(data)["result"]
    return result["postcode"], result["longitude"], result["latitude"]


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------
class Grid:
    """Regular grid of square cells laid over Web Mercator at VECTOR_ZOOM.

    One "unit" is one zoom-14 tile. Inside a region of a few tens of km the
    Mercator scale is treated as constant (error < 0.5 %), so cells are
    `cell` metres on the ground and Godot can use plain metres.
    """

    def __init__(self, west, south, east, north, cell):
        self.west, self.south, self.east, self.north = west, south, east, north
        self.cell = cell
        self.x0, self.y0 = lonlat_to_tile(west, north, VECTOR_ZOOM)
        x1, y1 = lonlat_to_tile(east, south, VECTOR_ZOOM)
        lat_c = (north + south) / 2.0
        self.metres_per_unit = EARTH_CIRCUMFERENCE / 2 ** VECTOR_ZOOM * math.cos(math.radians(lat_c))
        self.cells_per_unit = self.metres_per_unit / cell
        self.width = int(round((x1 - self.x0) * self.cells_per_unit))
        self.height = int(round((y1 - self.y0) * self.cells_per_unit))
        self.tx_range = range(int(math.floor(self.x0)), int(math.floor(x1)) + 1)
        self.ty_range = range(int(math.floor(self.y0)), int(math.floor(y1)) + 1)

    def to_cell(self, ux, uy):
        """Global tile units -> fractional cell coordinates."""
        return (ux - self.x0) * self.cells_per_unit, (uy - self.y0) * self.cells_per_unit

    def lonlat_to_cell(self, lon, lat):
        return self.to_cell(*lonlat_to_tile(lon, lat, VECTOR_ZOOM))

    def tile_rect(self, tx, ty):
        """Cells whose centres fall inside tile (tx, ty): (c0, r0, c1, r1), exclusive end."""
        a, b = self.to_cell(tx, ty)
        c, d = self.to_cell(tx + 1, ty + 1)
        c0 = max(0, math.ceil(a - 0.5))
        r0 = max(0, math.ceil(b - 0.5))
        c1 = min(self.width, math.ceil(c - 0.5))
        r1 = min(self.height, math.ceil(d - 0.5))
        return c0, r0, c1, r1


class Rasterizer:
    """Stamps polygons and lines into numpy layers, clipped to a cell rect."""

    def __init__(self, grid):
        self.grid = grid
        self.cover = np.full((grid.height, grid.width), C["grass"], np.uint8)
        self.bheight = np.zeros((grid.height, grid.width), np.uint8)
        self.broof = np.zeros((grid.height, grid.width), np.uint8)
        self.clip = (0, 0, grid.width, grid.height)

    def set_tile(self, tx, ty, extent):
        self.clip = self.grid.tile_rect(tx, ty)
        self.tx, self.ty, self.extent = tx, ty, extent

    def _to_cells(self, part):
        g = self.grid
        k = g.cells_per_unit / self.extent
        ox = (self.tx - g.x0) * g.cells_per_unit
        oy = (self.ty - g.y0) * g.cells_per_unit
        # -0.5: PIL treats integer coordinates as pixel centres.
        return [(ox + x * k - 0.5, oy + y * k - 0.5) for x, y in part]

    def _window(self, pts, pad):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        c0, r0, c1, r1 = self.clip
        x0 = max(c0, int(math.floor(min(xs) - pad)))
        y0 = max(r0, int(math.floor(min(ys) - pad)))
        x1 = min(c1, int(math.ceil(max(xs) + pad)) + 1)
        y1 = min(r1, int(math.ceil(max(ys) + pad)) + 1)
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1, y1

    def polygon_mask(self, rings, min_area=0.0):
        """Return (window, bool mask) for a polygon with holes, or None."""
        ext = self._to_cells(rings[0])
        if min_area > 0 and abs(mvt.ring_area(ext)) < min_area:
            return None
        win = self._window(ext, 1)
        if win is None:
            return None
        x0, y0, x1, y1 = win
        img = Image.new("1", (x1 - x0, y1 - y0), 0)
        d = ImageDraw.Draw(img)
        d.polygon([(x - x0, y - y0) for x, y in ext], fill=1, outline=1)
        for hole in rings[1:]:
            h = self._to_cells(hole)
            if len(h) >= 3:
                d.polygon([(x - x0, y - y0) for x, y in h], fill=0)
        return win, np.array(img, dtype=bool)

    def fill(self, feature, cls, min_area=0.5):
        for rings in mvt.polygons(feature.parts):
            m = self.polygon_mask(rings, min_area)
            if m:
                (x0, y0, x1, y1), mask = m
                self.cover[y0:y1, x0:x1][mask] = cls

    def line(self, feature, cls, width):
        for part in feature.parts:
            if len(part) < 2:
                continue
            pts = self._to_cells(part)
            win = self._window(pts, width + 1)
            if win is None:
                continue
            x0, y0, x1, y1 = win
            img = Image.new("1", (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(img).line([(x - x0, y - y0) for x, y in pts], fill=1, width=width,
                                     joint="curve" if width > 2 else None)
            mask = np.array(img, dtype=bool)
            self.cover[y0:y1, x0:x1][mask] = cls

    def building(self, rings, height):
        m = self.polygon_mask(rings)
        if not m:
            return
        (x0, y0, x1, y1), mask = m
        # Stable roof variant from the building's position (consistent across tiles).
        ux, uy = rings[0][0]
        gx = self.tx * self.extent + ux
        gy = self.ty * self.extent + uy
        variant = 1 + ((gx * 73856093) ^ (gy * 19349663)) % len(ROOF_COLOURS)
        self.cover[y0:y1, x0:x1][mask] = C["building"]
        h = self.bheight[y0:y1, x0:x1]
        r = self.broof[y0:y1, x0:x1]
        taller = mask & (h < height)
        h[taller] = height
        r[taller] = variant


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
def vector_tile_url():
    tj = json.loads(http_get(OPENFREEMAP_TILEJSON))
    return tj["tiles"][0]


def fetch_vector_tiles(grid, url_template):
    version = url_template.split("/")[-4]
    jobs = []
    for ty in grid.ty_range:
        for tx in grid.tx_range:
            url = url_template.format(z=VECTOR_ZOOM, x=tx, y=ty)
            path = os.path.join(CACHE, "openfreemap", version, str(VECTOR_ZOOM), str(tx), f"{ty}.pbf")
            jobs.append((tx, ty, url, path))
    log(f"Vector tiles: {len(jobs)} (zoom {VECTOR_ZOOM}, OpenFreeMap {version})")
    with ThreadPoolExecutor(max_workers=4) as pool:
        datas = list(pool.map(lambda j: http_get(j[2], j[3]), jobs))
    return [(tx, ty, d) for (tx, ty, _u, _p), d in zip(jobs, datas) if d]


def rasterize(grid, tiles):
    r = Rasterizer(grid)
    wanted = {"landuse", "landcover", "water", "waterway", "transportation", "building", "aeroway"}
    for i, (tx, ty, data) in enumerate(tiles):
        layers = mvt.decode(data, wanted)
        any_layer = next(iter(layers.values()), None)
        if any_layer is None:
            continue
        r.set_tile(tx, ty, any_layer.extent)
        c0, r0, c1, r1 = r.clip
        if c1 <= c0 or r1 <= r0:
            continue

        def feats(name, ftype=None):
            layer = layers.get(name)
            if not layer:
                return []
            return [f for f in layer.features if ftype is None or f.type == ftype]

        for f in feats("landuse", mvt.POLYGON):
            cls = LANDUSE.get(f.tags.get("class"))
            if cls:
                r.fill(f, C[cls])
        for f in feats("landcover", mvt.POLYGON):
            cls = LANDCOVER_SUBCLASS.get(f.tags.get("subclass")) or LANDCOVER_CLASS.get(f.tags.get("class"))
            if cls:
                r.fill(f, C[cls])
        for f in feats("aeroway", mvt.POLYGON):
            if f.tags.get("class") in ("runway", "taxiway", "apron", "helipad"):
                r.fill(f, C["runway"])
        for f in feats("aeroway", mvt.LINESTRING):
            if f.tags.get("class") in ("runway", "taxiway"):
                r.line(f, C["runway"], 4 if f.tags["class"] == "runway" else 2)
        for f in feats("water", mvt.POLYGON):
            if f.tags.get("brunnel") == "tunnel":
                continue
            r.fill(f, C["sea"] if f.tags.get("class") == "ocean" else C["water"], min_area=0.3)
        for f in feats("waterway", mvt.LINESTRING):
            w = WATERWAY_WIDTH.get(f.tags.get("class"))
            if w and f.tags.get("brunnel") != "tunnel":
                r.line(f, C["water"], w)
        roads = [f for f in feats("transportation") if f.tags.get("brunnel") != "tunnel"]
        for f in roads:  # pier / bridge areas
            if f.type == mvt.POLYGON and f.tags.get("class") in ("pier", "bridge"):
                r.fill(f, C["pier"] if f.tags["class"] == "pier" else C["road"], min_area=0.3)
        lines = [f for f in roads if f.type == mvt.LINESTRING and f.tags.get("class") in ROAD_STYLE]
        lines.sort(key=lambda f: ROAD_ORDER.index(f.tags["class"]))
        for f in lines:
            cls, w = ROAD_STYLE[f.tags["class"]]
            r.line(f, C[cls], w)
        blds = []
        for f in feats("building", mvt.POLYGON):
            if f.tags.get("hide_3d"):
                continue
            h = f.tags.get("render_height", 6) or 6
            h = int(max(3, min(255, round(float(h)))))
            for rings in mvt.polygons(f.parts):
                blds.append((h, rings))
        blds.sort(key=lambda b: b[0])
        for h, rings in blds:
            r.building(rings, h)
        if (i + 1) % 20 == 0 or i + 1 == len(tiles):
            log(f"  rasterized {i + 1}/{len(tiles)} tiles")
    return r


def fetch_elevation(grid):
    z = ELEVATION_ZOOM
    s = 2 ** (z - VECTOR_ZOOM)
    ex0 = int(math.floor(grid.x0 * s))
    ey0 = int(math.floor(grid.y0 * s))
    ex1 = int(math.floor((grid.x0 + grid.width / grid.cells_per_unit) * s))
    ey1 = int(math.floor((grid.y0 + grid.height / grid.cells_per_unit) * s))
    nx, ny = ex1 - ex0 + 1, ey1 - ey0 + 1
    log(f"Elevation tiles: {nx * ny} (zoom {z}, Terrarium)")
    mosaic = np.zeros((ny * 256, nx * 256), np.float32)
    for j in range(ny):
        for i in range(nx):
            x, y = ex0 + i, ey0 + j
            data = http_get(TERRARIUM_URL.format(z=z, x=x, y=y),
                            os.path.join(CACHE, "terrarium", str(z), str(x), f"{y}.png"))
            rgb = np.asarray(Image.open(BytesIO(data)).convert("RGB"), np.float32)
            mosaic[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = \
                rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768

    # Bilinear sample at every cell centre.
    cols = (np.arange(grid.width) + 0.5) / grid.cells_per_unit + grid.x0
    rows = (np.arange(grid.height) + 0.5) / grid.cells_per_unit + grid.y0
    px = (cols * s - ex0) * 256 - 0.5
    py = (rows * s - ey0) * 256 - 0.5
    px = np.clip(px, 0, mosaic.shape[1] - 1.001)
    py = np.clip(py, 0, mosaic.shape[0] - 1.001)
    ix, iy = px.astype(int), py.astype(int)
    fx, fy = px - ix, py - iy
    a = mosaic[np.ix_(iy, ix)]
    b = mosaic[np.ix_(iy, ix + 1)]
    c = mosaic[np.ix_(iy + 1, ix)]
    d = mosaic[np.ix_(iy + 1, ix + 1)]
    fx = fx[None, :]
    fy = fy[:, None]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def shape_terrain(height, cover):
    h = height.astype(np.float32)
    # Light 3x3 blur: SRTM is a surface model and is noisy in towns.
    p = np.pad(h, 1, mode="edge")
    h = sum(p[dy:dy + h.shape[0], dx:dx + h.shape[1]] for dy in range(3) for dx in range(3)) / 9.0
    sea = cover == C["sea"]
    h[sea] = 0.0
    h[~sea] = np.maximum(h[~sea], 0.6)
    water = cover == C["water"]
    h[water] = np.maximum(h[water] - 0.4, 0.3)
    return h


def write_layers(out_dir, grid, r, height, name, postcode_info):
    os.makedirs(out_dir, exist_ok=True)

    def wgz(fname, arr):
        with gzip.open(os.path.join(out_dir, fname), "wb", compresslevel=9) as f:
            f.write(np.ascontiguousarray(arr).tobytes())

    wgz("height.bin.gz", height.astype("<f2"))
    wgz("cover.bin.gz", r.cover)
    wgz("buildings.bin.gz", np.stack([r.bheight, r.broof], axis=-1))

    home = None
    if postcode_info:
        pc, lon, lat = postcode_info
        cx, cy = grid.lonlat_to_cell(lon, lat)
        home = {"postcode": pc, "lon": lon, "lat": lat, "x": cx * grid.cell, "z": cy * grid.cell}

    counts = np.bincount(r.cover.ravel(), minlength=len(CLASSES))
    meta = {
        "format": 1,
        "name": name,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bbox": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north},
        "width": grid.width,
        "height": grid.height,
        "cell_size": grid.cell,
        "projection": {
            "type": "web_mercator_local",
            "zoom": VECTOR_ZOOM,
            "origin_tile_x": grid.x0,
            "origin_tile_y": grid.y0,
            "metres_per_tile": grid.metres_per_unit,
        },
        "home": home,
        "layers": {
            "height": {"file": "height.bin.gz", "type": "float16", "units": "m"},
            "cover": {"file": "cover.bin.gz", "type": "uint8"},
            "buildings": {"file": "buildings.bin.gz", "type": "uint8x2",
                          "channels": ["height_m", "roof_variant"]},
        },
        "classes": [
            {"id": i, "name": n, "colour": col,
             "resources": {"biomass": b, "water": w, "metal": m, "energy": e},
             "cells": int(counts[i])}
            for i, (n, col, b, w, m, e) in enumerate(CLASSES)
        ],
        "roof_colours": ROOF_COLOURS,
        "elevation_range": [float(height.min()), float(height.max())],
        "attribution": [
            "Map data (c) OpenStreetMap contributors (ODbL), via OpenMapTiles / OpenFreeMap",
            "Elevation: Mapzen Terrain Tiles (SRTM and other sources), hosted on AWS Open Data",
            "Postcode lookup: postcodes.io (contains OS and ONS data, (c) Crown copyright and database right)",
        ],
    }
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta


def write_preview(path, r, height, scale=1):
    pal = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _n, c, *_ in CLASSES], np.float32)
    img = pal[r.cover]
    # Hillshade from the north-west.
    gy, gx = np.gradient(height.astype(np.float32) * 2.0, 10.0)
    shade = np.clip(1.0 - (gx - gy) * 0.35, 0.65, 1.25)[..., None]
    img = img * shade
    roof = r.bheight > 0
    img[roof] *= np.clip(0.75 + r.bheight[roof, None] / 60.0, 0.75, 1.15)
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    if scale != 1:
        out = out.resize((out.width // scale, out.height // scale), Image.NEAREST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.save(path, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--postcode", help="UK postcode for the player's home (also centres the region)")
    ap.add_argument("--bbox", help="west,south,east,north in degrees (overrides --radius-km)")
    ap.add_argument("--radius-km", type=float, default=4.0, help="half-size of the square region around the postcode")
    ap.add_argument("--cell", type=float, default=10.0, help="cell size in metres (default 10)")
    ap.add_argument("--name", default=None, help="region name (folder under godot/data/regions)")
    ap.add_argument("--out", default=None, help="output folder (default godot/data/regions/<name>)")
    ap.add_argument("--preview", default=None, help="write a PNG preview here (default docs/<name>-preview.png)")
    args = ap.parse_args()

    postcode_info = lookup_postcode(args.postcode) if args.postcode else None
    if postcode_info:
        log(f"Postcode {postcode_info[0]}: {postcode_info[2]:.5f}, {postcode_info[1]:.5f}")

    if args.bbox:
        west, south, east, north = (float(v) for v in args.bbox.split(","))
    elif postcode_info:
        _pc, lon, lat = postcode_info
        dlat = args.radius_km / 111.32
        dlon = args.radius_km / (111.32 * math.cos(math.radians(lat)))
        west, south, east, north = lon - dlon, lat - dlat, lon + dlon, lat + dlat
    else:
        ap.error("give --postcode and/or --bbox")

    name = args.name or (postcode_info[0].replace(" ", "").lower() if postcode_info else "region")
    out_dir = args.out or os.path.join(ROOT, "godot", "data", "regions", name)
    preview = args.preview or os.path.join(ROOT, "docs", f"{name}-preview.png")

    grid = Grid(west, south, east, north, args.cell)
    log(f"Region {name}: {grid.width} x {grid.height} cells of {args.cell:g} m "
        f"({grid.width * args.cell / 1000:.1f} x {grid.height * args.cell / 1000:.1f} km)")

    t0 = time.time()
    tiles = fetch_vector_tiles(grid, vector_tile_url())
    r = rasterize(grid, tiles)
    height = shape_terrain(fetch_elevation(grid), r.cover)
    meta = write_layers(out_dir, grid, r, height, name, postcode_info)
    write_preview(preview, r, height, scale=2 if grid.width > 2000 else 1)
    log(f"Elevation {meta['elevation_range'][0]:.1f} .. {meta['elevation_range'][1]:.1f} m, "
        f"{int((r.bheight > 0).sum())} building cells")
    log(f"Wrote {out_dir} and {preview} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
