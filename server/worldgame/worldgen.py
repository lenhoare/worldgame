"""Build a voxel world from a generated region (tools/mapgen/generate.py).

Everything comes from the real map: ground and bedrock from terrain, soil and
geology; buildings from footprints and heights, with walls, interiors and
roofs chosen by the land use around them; trees from woodland and parks;
salvage (cars, tanks, batteries...) from real sites and streets.
The same region and seed always give the same world.
"""

import gzip
import json
import math
import os
import random

import numpy as np

from . import materials as M
from . import physics as P
from .world import World

DEPTH = 8          # diggable layers below sea level
HEADROOM = 12


def _gz(path, dtype, shape):
    with gzip.open(path, "rb") as f:
        return np.frombuffer(f.read(), dtype).reshape(shape)


def load_region(d):
    meta = json.load(open(os.path.join(d, "meta.json")))
    W, H = meta["width"], meta["height"]
    L = meta["layers"]
    r = {
        "meta": meta,
        "cover": _gz(os.path.join(d, L["cover"]["file"]), np.uint8, (H, W)).T.copy(),
        "height": _gz(os.path.join(d, L["height"]["file"]), "<f2", (H, W)).T.astype(np.float32),
        "geology": _gz(os.path.join(d, L["geology"]["file"]), np.uint8, (H, W, 3)).transpose(1, 0, 2).copy(),
        "sites": json.load(open(os.path.join(d, L["sites"]["file"]))),
    }
    b = _gz(os.path.join(d, L["buildings"]["file"]), np.uint8, (H, W, 2))
    r["bheight"] = b[..., 0].T.copy()
    return r


def _box_count(mask, r):
    """Number of True cells within a (2r+1) square window (integral image)."""
    a = np.pad(mask.astype(np.int32), ((r + 1, r), (r + 1, r))).cumsum(0).cumsum(1)
    n = 2 * r + 1
    return a[n:, n:] - a[:-n, n:] - a[n:, :-n] + a[:-n, :-n]


def _hash(X, Z, seed):
    x = np.arange(X, dtype=np.int64)[:, None]
    z = np.arange(Z, dtype=np.int64)[None, :]
    h = (x * 73856093) ^ (z * 19349663) ^ (seed * 83492791)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFF).astype(np.int32)


def build_world(region_dir, seed=1):
    r = load_region(region_dir)
    meta = r["meta"]
    X, Z = meta["width"], meta["height"]
    cell = float(meta["cell_size"])
    C = {c["name"]: c["id"] for c in meta["classes"]}
    ID = M.ID
    cover, h, bh = r["cover"], r["height"], r["bheight"].astype(np.int32)
    is_sea = cover == C["sea"]
    is_water = cover == C["water"]
    is_bld = bh > 0
    storeys = np.where(is_bld, np.clip(np.rint(bh / cell), 1, 30), 0).astype(np.int32)

    sea = DEPTH
    gt = (sea + np.floor(np.maximum(h, 0.0) / cell)).astype(np.int32)       # top ground layer on land
    Y = int(gt.max() + storeys.max() + 2 + HEADROOM)
    w = World(X, Z, Y, cell, sea, seed)
    w.meta = {"name": meta["name"], "bbox": meta["bbox"], "projection": meta["projection"],
              "home": meta.get("home"), "attribution": meta.get("attribution", [])}
    hsh = _hash(X, Z, seed)

    # --- sea bed: deeper away from land -----------------------------------
    land = ~is_sea
    dist = np.zeros((X, Z), np.int32)
    grown = land.copy()
    for i in range(1, 25):
        g = grown.copy()
        g[1:, :] |= grown[:-1, :]
        g[:-1, :] |= grown[1:, :]
        g[:, 1:] |= grown[:, :-1]
        g[:, :-1] |= grown[:, 1:]
        dist[g & ~grown] = i
        grown = g
    dist[~grown] = 25
    depth = np.clip(1 + dist // 6, 1, 5)
    gt = np.where(is_sea, sea - 1 - depth, gt)
    gt = np.where(is_water, gt - 2, gt)                                     # fresh water sits one voxel down

    # --- bedrock, subsoil and surface ids per column ------------------------
    units = meta["geology"]["units"]
    rock_vox = []
    for u in units:
        rock, lith = u["rock"], u["lith"].lower()
        if rock == "carbonate":
            rock_vox.append(ID["chalk"])
        elif rock == "sandstone":
            rock_vox.append(ID["sandstone"])
        elif rock == "mudstone":
            rock_vox.append(ID["mudstone"])
        elif rock == "igneous":
            rock_vox.append(ID["basalt"])
        elif rock == "metamorphic":
            rock_vox.append(ID["slate"])
        elif rock == "sediment":
            first = min((lith.find(k) if k in lith else 999, k) for k in ("clay", "sand", "gravel"))[1]
            rock_vox.append(ID[first] if any(k in lith for k in ("clay", "sand", "gravel")) else ID["gravel"])
        else:
            rock_vox.append(ID["rock"])
    bedrock = np.array(rock_vox, np.uint8)[r["geology"][..., 0]]
    clay, sand = r["geology"][..., 1].astype(np.int32), r["geology"][..., 2].astype(np.int32)
    subsoil = np.full((X, Z), ID["soil"], np.uint8)
    subsoil[clay >= 35] = ID["clay"]
    subsoil[sand >= 60] = ID["sand"]
    nodata = clay == 0
    subsoil[nodata & (bedrock == ID["clay"])] = ID["clay"]
    subsoil[nodata & (bedrock == ID["sand"])] = ID["sand"]

    surf = np.full((X, Z), ID["turf"], np.uint8)
    garden = hsh % 100 < 62
    surf[cover == C["urban"]] = ID["paving"]
    surf[(cover == C["urban"]) & garden] = ID["turf"]
    for name, vox in (("commercial", "paving"), ("industrial", "paving"), ("farmland", "farm_soil"),
                      ("beach", "sand"), ("path", "gravel"), ("rail", "ballast"), ("road", "asphalt"),
                      ("road_major", "asphalt"), ("runway", "asphalt"), ("pier", "paving"),
                      ("building", "paving")):
        surf[cover == C[name]] = ID[vox]
    surf[cover == C["bare"]] = bedrock[cover == C["bare"]]
    surf[is_sea] = ID["sand"]
    surf[is_water] = ID["gravel"]

    K = np.arange(Y, dtype=np.int32)[None, None, :]
    g3 = gt[:, :, None]
    vox = np.where(K <= g3, bedrock[:, :, None], np.uint8(M.AIR)).astype(np.uint8)
    np.putmask(vox, K == g3 - 1, np.broadcast_to(subsoil[:, :, None], vox.shape))
    np.putmask(vox, K == g3, np.broadcast_to(surf[:, :, None], vox.shape))
    np.putmask(vox, is_sea[:, :, None] & (K > g3) & (K <= sea - 1), np.uint8(ID["seawater"]))
    np.putmask(vox, is_water[:, :, None] & (K == g3 + 1), np.uint8(ID["water"]))
    del K

    # --- buildings ----------------------------------------------------------
    sites = []
    for s in r["sites"]:
        sites.append({"kind": s["kind"], "name": s["name"], "x": int(s["x"] / cell), "z": int(s["z"] / cell)})
    w.sites = sites
    near_ind = _box_count(cover == C["industrial"], 8)
    near_com = _box_count(cover == C["commercial"], 8)
    near_urb = _box_count(cover == C["urban"], 8)
    btype = np.zeros((X, Z), np.int8)                                      # 0 home 1 shop 2 industrial 3 medical 4 garage
    btype[near_com > near_urb // 2] = 1
    btype[near_ind > near_urb] = 2
    xs_all = np.arange(X)[:, None]
    zs_all = np.arange(Z)[None, :]
    for s in sites:
        d = np.maximum(np.abs(xs_all - s["x"]), np.abs(zs_all - s["z"]))
        if s["kind"] == "hospital":
            btype[d <= 14] = 3
        elif s["kind"] == "garage":
            btype[d <= 7] = 4
        elif s["kind"] == "station":
            btype[d <= 10] = 2
    tall = storeys >= 5
    wall_id = np.choose(btype, [ID["brick_wall"], ID["concrete_wall"], ID["steel_frame"],
                                ID["concrete_wall"], ID["brick_wall"]]).astype(np.uint8)
    int_id = np.choose(btype, [ID["interior_home"], ID["interior_shop"], ID["interior_industrial"],
                               ID["interior_medical"], ID["interior_garage"]]).astype(np.uint8)
    wall_id[tall] = ID["concrete_wall"]
    roof_id = np.where((btype == 0) & (storeys <= 3), ID["roof_tile"], ID["roof_metal"]).astype(np.uint8)
    bx, bz = np.nonzero(is_bld)
    for level in range(1, int(storeys.max()) + 1):
        here = storeys >= level
        pad = np.pad(here, 1)
        edge = here & ~(pad[2:, 1:-1] & pad[:-2, 1:-1] & pad[1:-1, 2:] & pad[1:-1, :-2])
        sel = here[bx, bz]
        x, z = bx[sel], bz[sel]
        ids = np.where(edge[x, z], wall_id[x, z], int_id[x, z])
        glassy = edge[x, z] & (((btype[x, z] == 1) & (level == 1) & (hsh[x, z] % 2 == 0))
                               | (tall[x, z] & ((x + z + level) % 2 == 0)))
        ids = np.where(glassy, ID["glass_wall"], ids)
        vox[x, z, gt[x, z] + level] = ids
    vox[bx, bz, gt[bx, bz] + storeys[bx, bz] + 1] = roof_id[bx, bz]

    # --- trees and scrub ------------------------------------------------------
    open_top = ~is_bld & ~is_sea & ~is_water
    tree = open_top & (((cover == C["wood"]) & (hsh % 5 == 0))
                       | ((cover == C["park"]) & (hsh % 60 == 0))
                       | ((cover == C["urban"]) & garden & (hsh % 140 == 0))
                       | ((cover == C["scrub"]) & (hsh % 45 == 0)))
    tx, tz = np.nonzero(tree)
    th = 2 + (hsh[tx, tz] >> 4) % 2
    for i in range(3):
        sel = th > i
        vox[tx[sel], tz[sel], gt[tx[sel], tz[sel]] + 1 + i] = ID["wood"]
    crown = gt[tx, tz] + th
    vox[tx, tz, crown + 1] = ID["leaves"]
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, nz = np.clip(tx + dx, 0, X - 1), np.clip(tz + dz, 0, Z - 1)
        free = vox[nx, nz, crown] == M.AIR
        vox[nx[free], nz[free], crown[free]] = ID["leaves"]
    shrub = open_top & (cover == C["scrub"]) & (hsh % 100 < 35) & ~tree
    sx, sz = np.nonzero(shrub)
    free = vox[sx, sz, gt[sx, sz] + 1] == M.AIR
    vox[sx[free], sz[free], gt[sx[free], sz[free]] + 1] = ID["shrub"]

    w.vox = vox
    w.rebuild_top()
    _place_salvage(w, r, C, cover, hsh, btype, seed)
    w.meta["coarse_map"] = _coarse_map(w, cover, C, is_bld)
    w.rev += 1
    return w


def _place_salvage(w, r, C, cover, hsh, btype, seed):
    rng = random.Random(seed * 7919 + 13)
    X, Z = w.X, w.Z
    is_road = (cover == C["road"]) | (cover == C["road_major"])

    def ground(x, z):
        return (x, w.surface(x, z) + 1, z)

    def open_cell(x, z):
        if not (0 <= x < X and 0 <= z < Z):
            return False
        k = w.surface(x, z)
        v = M.VOXELS[int(w.vox[x, z, k])]
        return v.natural and w.vox[x, z, k + 1] == M.AIR

    def scatter(kind, x, z, n, radius):
        for _ in range(n):
            for _try in range(12):
                px, pz = x + rng.randint(-radius, radius), z + rng.randint(-radius, radius)
                if open_cell(px, pz):
                    P.spawn(w, kind, ground(px, pz), rng)
                    break

    # Parked cars along streets and in car parks.
    rx, rz = np.nonzero(is_road & (hsh % 37 == 0))
    for x, z in zip(rx.tolist(), rz.tolist()):
        if open_cell(x, z):
            P.spawn(w, "car", ground(x, z), rng)
    for s in w.sites:
        x, z = s["x"], s["z"]
        if s["kind"] == "car_park":
            scatter("car", x, z, rng.randint(5, 14), 7)
            if rng.random() < 0.12:
                scatter("charger", x, z, 1, 4)
        elif s["kind"] == "garage":
            scatter("car", x, z, rng.randint(2, 5), 5)
            scatter("fuel_can", x, z, rng.randint(1, 3), 4)
            scatter("tyre", x, z, rng.randint(2, 6), 4)
        elif s["kind"] == "recycling":
            for mat in ("glass", "plastic", "aluminium"):
                for _try in range(12):
                    px, pz = x + rng.randint(-4, 4), z + rng.randint(-4, 4)
                    if open_cell(px, pz):
                        w.add_bulk(mat, rng.uniform(800, 4000), ground(px, pz))
                        break
            scatter("skip", x, z, 2, 4)
        elif s["kind"] == "hospital":
            scatter("generator", x, z, 1, 6)
            scatter("gas_cylinder", x, z, 3, 6)
        elif s["kind"] == "station":
            scatter("cable_drum", x, z, 2, 6)
            scatter("radio_set", x, z, 1, 5)
        elif s["kind"] == "charging_station":
            scatter("charger", x, z, 2, 3)
        elif s["kind"] == "fuel_station":
            scatter("fuel_tank", x, z, 3, 4)
    # Rails and sleepers along the railway.
    lx, lz = np.nonzero((cover == C["rail"]) & (hsh % 9 == 0))
    for x, z in zip(lx.tolist(), lz.tolist()):
        P.spawn(w, "rail" if (x + z) % 2 else "sleeper", ground(x, z), rng)
    # Containers and stock on industrial yards.
    ix, iz = np.nonzero((cover == C["industrial"]) & (hsh % 331 == 0))
    for x, z in zip(ix.tolist(), iz.tolist()):
        if open_cell(x, z):
            P.spawn(w, rng.choice(["shipping_container", "skip", "tank", "cable_drum", "shipping_container"]),
                    ground(x, z), rng)
    # Flint and driftwood on the beach.
    fx, fz = np.nonzero((cover == C["beach"]) & (hsh % 97 == 0))
    for x, z in zip(fx.tolist(), fz.tolist()):
        if open_cell(x, z):
            if (x + z) % 3:
                w.add_bulk("flint", rng.uniform(200, 900), ground(x, z))
            else:
                w.add_bulk("wood", rng.uniform(300, 1500), ground(x, z))


def _coarse_map(w, cover, C, is_bld, n=48):
    """A small text map of the region as it was before the collapse."""
    sym = {"sea": "~", "water": "=", "beach": ":", "urban": "u", "commercial": "c", "industrial": "I",
           "park": "p", "grass": ".", "farmland": "f", "wood": "T", "scrub": '"', "road": "_",
           "road_major": "#", "rail": "+", "building": "u", "path": ".", "runway": "_", "bare": "r",
           "wetland": "w", "golf": "p", "pier": "_"}
    names = {v: k for k, v in C.items()}
    rows = []
    bx, bz = w.X / n, w.Z / n
    for j in range(n):
        row = ""
        for i in range(n):
            block = cover[int(i * bx):int((i + 1) * bx), int(j * bz):int((j + 1) * bz)]
            counts = np.bincount(block.ravel(), minlength=len(names))
            for key in ("road_major", "rail"):
                if counts[C[key]] > block.size * 0.12:
                    counts[C[key]] = block.size
            row += sym.get(names[int(counts.argmax())], "?")
        rows.append(row)
    return {"rows": rows, "cell_voxels": round(bx, 1),
            "legend": "~ sea, = fresh water, : beach, u houses, c shops, I industry, p park, . grass, "
                      "f farmland, T wood, \" scrub, _ road, # main road, + railway"}


def spawn_point(w, index, total=1):
    """Open ground for a new giant: the first near the home address, others spread on a ring."""
    home = w.meta.get("home") or {}
    hx = int(home.get("x", w.X * w.cell / 2) / w.cell)
    hz = int(home.get("z", w.Z * w.cell / 2) / w.cell)
    if index > 0:
        ang = 2 * math.pi * (index - 1) / max(1, total - 1) + 0.6
        rad = min(w.X, w.Z) * 0.28
        cx, cz = w.X // 2, w.Z // 2
        hx, hz = int(cx + rad * math.cos(ang)), int(cz + rad * math.sin(ang))
    hx, hz = min(max(hx, 3), w.X - 4), min(max(hz, 3), w.Z - 4)
    for radius in range(0, 60):
        for dx in range(-radius, radius + 1):
            for dz in range(-radius, radius + 1):
                if max(abs(dx), abs(dz)) != radius:
                    continue
                x, z = hx + dx, hz + dz
                if not (2 <= x < w.X - 2 and 2 <= z < w.Z - 2):
                    continue
                k = w.surface(x, z)
                v = M.VOXELS[int(w.vox[x, z, k])]
                if v.natural and v.kind != "liquid" and all(w.vox[x, z, k + i] == M.AIR for i in range(1, 5)) \
                        and k >= w.sea and (x, k + 1, z) not in w.items_at \
                        and not any(g.x == x and g.z == z for g in w.giants.values()):
                    return x, z
    return hx, hz
