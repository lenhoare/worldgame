"""Global hex grid: Uber's H3 (https://h3geo.org).

Every hex has a permanent worldwide id (e.g. "89194a710c3ffff"), so claims,
scouting and deposit seeds mean the same thing in every region. The game
doesn't need H3 itself: the generator writes, per region,

  hex.bin.gz   uint16 local hex index per grid cell (row-major)
  hexes.json   for each local index: H3 id, centre, cell bounds, neighbours,
               and whether the hex lies completely inside the region

Resolution 9 hexes average ~0.1 km^2 (~350 m across).
"""

import h3
import numpy as np

DEFAULT_RESOLUTION = 9


def build(grid, resolution, log):
    lons, lats = grid.cell_lonlats()
    layer = np.zeros((grid.height, grid.width), np.uint16)
    ids = []
    local = {}
    latlng_to_cell = h3.latlng_to_cell
    for row in range(grid.height):
        lat = float(lats[row])
        out = layer[row]
        prev_id = None
        prev_idx = 0
        for col in range(grid.width):
            hid = latlng_to_cell(lat, float(lons[col]), resolution)
            if hid != prev_id:
                idx = local.get(hid)
                if idx is None:
                    idx = local[hid] = len(ids)
                    ids.append(hid)
                    if idx > 65535:
                        raise ValueError("region too large for 16-bit hex indices; use a coarser --h3-res")
                prev_id, prev_idx = hid, idx
            out[col] = prev_idx

    flat = layer.ravel().astype(np.int64)
    counts = np.bincount(flat, minlength=len(ids))
    rr, cc = np.divmod(np.arange(flat.size), grid.width)
    c0 = np.full(len(ids), grid.width, np.int64)
    r0 = np.full(len(ids), grid.height, np.int64)
    c1 = np.zeros(len(ids), np.int64)
    r1 = np.zeros(len(ids), np.int64)
    np.minimum.at(c0, flat, cc)
    np.minimum.at(r0, flat, rr)
    np.maximum.at(c1, flat, cc)
    np.maximum.at(r1, flat, rr)

    hexes = []
    for i, hid in enumerate(ids):
        lat, lon = h3.cell_to_latlng(hid)
        cx, cz = grid.lonlat_to_cell(lon, lat)
        boundary = h3.cell_to_boundary(hid)
        inside = all(grid.west <= blon <= grid.east and grid.south <= blat <= grid.north
                     for blat, blon in boundary)
        neighbours = [local.get(n, -1) for n in h3.grid_ring(hid, 1)]
        hexes.append({
            "id": hid,
            "x": round(cx * grid.cell, 1),
            "z": round(cz * grid.cell, 1),
            "complete": inside,
            "cells": int(counts[i]),
            "bounds": [int(c0[i]), int(r0[i]), int(c1[i]), int(r1[i])],
            "neighbours": neighbours,
        })
    complete = sum(h["complete"] for h in hexes)
    log(f"Hex grid: H3 resolution {resolution}, {len(hexes)} hexes ({complete} complete)")
    return layer, hexes
