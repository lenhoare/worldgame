"""Save and load a whole game: voxels as compressed numpy, everything else as JSON."""

import json
import os
from collections import deque

import numpy as np

from .giants import Giant
from .items import Item
from .world import World

VERSION = 1


def _key(p):
    return [int(p[0]), int(p[1]), int(p[2])]


def save(w, path):
    """Write <path>.npz and <path>.json (atomically, so a crash can't leave half a save)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, vox=w.vox)
    os.replace(tmp, path + ".npz")
    state = {
        "version": VERSION, "dims": [w.X, w.Z, w.Y], "cell": w.cell, "sea": w.sea, "seed": w.seed,
        "tick": w.tick, "meta": w.meta, "sites": w.sites, "wind": w.wind, "raining": w.raining,
        "dryness": w.dryness, "stats": w.stats, "next_item": w._next_item,
        "rng": list(w.rng.getstate()[1]) + [w.rng.getstate()[0], w.rng.getstate()[2]],
        "items": [{"id": it.id, "kind": it.kind, "mat": it.mat, "mass": it.mass,
                   "pos": list(it.pos) if it.pos else None, "holder": it.holder, "inside": it.inside,
                   "props": it.props} for it in w.items.values()],
        "giants": [{"id": g.id, "name": g.name, "token": g.token, "colour": g.colour, "p": [g.x, g.k, g.z],
                    "energy": g.energy, "integrity": g.integrity, "carrying": g.carrying, "status": g.status,
                    "queue": [{k: v for k, v in a.items() if not k.startswith("_")}
                              for a in ([g.cur] if g.cur else []) + g.queue],
                    "notes": g.notes, "advice": g.advice, "inbox": g.inbox, "stats": g.stats}
                   for g in w.giants.values()],
        "burning": [_key(p) + [f] for p, f in w.burning.items()],
        "burning_items": sorted(w.burning_items), "hot_items": sorted(w.hot_items),
        "soaked": [_key(p) for p in w.soaked], "links": [list(l) for l in w.links],
        "signs": [_key(p) + [t] for p, t in w.signs.items()],
        "water_level": [_key(p) + [l] for p, l in w.water_level.items()],
        "water_frontier": [_key(p) for p in w.water_frontier],
        "log": list(w.log)[-500:],
    }
    tmp = path + ".tmp.json"
    with open(tmp, "w") as f:
        json.dump(state, f, separators=(",", ":"))
    os.replace(tmp, path + ".json")


def load(path):
    with open(path + ".json") as f:
        s = json.load(f)
    if s.get("version") != VERSION:
        raise ValueError(f"save version {s.get('version')} is not supported")
    X, Z, Y = s["dims"]
    w = World(X, Z, Y, s["cell"], s["sea"], s["seed"])
    w.vox = np.load(path + ".npz")["vox"]
    w.rebuild_top()
    for k in ("tick", "meta", "sites", "wind", "raining", "dryness", "stats"):
        setattr(w, k, s[k])
    r = s["rng"]
    w.rng.setstate((r[-2], tuple(r[:-2]), r[-1]))
    w._next_item = s["next_item"]
    for d in s["items"]:
        it = Item(d["id"], d["kind"], d["mat"], d["mass"], **d["props"])
        it.holder, it.inside = d["holder"], d["inside"]
        if "parts" in it.props:
            it.props["parts"] = [tuple(p) for p in it.props["parts"]]
        if d["pos"]:
            it.pos = tuple(d["pos"])
            w.items_at.setdefault(it.pos, set()).add(it.id)
        it.rev = w.rev
        w.items[it.id] = it
    for d in s["giants"]:
        g = Giant(w, d["id"], d["name"], d["p"][0], d["p"][2], d["colour"])
        g.k, g.token = d["p"][1], d["token"]
        for k in ("energy", "integrity", "carrying", "status", "queue", "notes", "advice", "inbox", "stats"):
            setattr(g, k, d[k])
        w.giants[g.id] = g
    w.burning = {tuple(b[:3]): b[3] for b in s["burning"]}
    w.burning_items, w.hot_items = set(s["burning_items"]), set(s["hot_items"])
    w.soaked = {tuple(p) for p in s["soaked"]}
    w.links = [tuple(l) for l in s["links"]]
    w.signs = {tuple(p[:3]): p[3] for p in s["signs"]}
    w.water_level = {tuple(p[:3]): p[3] for p in s["water_level"]}
    w.water_frontier = deque(tuple(p) for p in s["water_frontier"])
    w.log.extend(s["log"])
    w.rev += 1
    return w
