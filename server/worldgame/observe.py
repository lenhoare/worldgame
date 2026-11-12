"""What a giant perceives: its observation each turn, and the questions it can ask.

Everything is plain JSON with short text, written to be read by a language
model. Positions are [x, y, z]: x east, z south, y up (0 = just above sea
level), in voxels of about 3 m.
"""

import math

from . import materials as M
from .giants import CARRY_KG, HEAR, REACH, REACH_DOWN, REACH_UP, VERBS, kg
from .items import FORMS, affordances

MAP_R = 12
SEE_ITEMS = 20
SEE_GIANTS = 150
SEE_FIRE = 250
SEE_SITES = 260

SYMBOL = {
    "seawater": "~", "water": "=", "turf": ".", "soil": ",", "farm_soil": ";", "clay": "c", "sand": ":",
    "gravel": "o", "chalk": "k", "sandstone": "r", "mudstone": "r", "basalt": "r", "slate": "r", "rock": "r",
    "asphalt": "_", "paving": "-", "ballast": "b", "brick_wall": "B", "concrete_wall": "C",
    "steel_frame": "S", "glass_wall": "G", "roof_tile": "^", "roof_metal": "M", "interior_home": "i",
    "interior_shop": "i", "interior_industrial": "i", "interior_medical": "i", "interior_garage": "i",
    "wood": "T", "leaves": "t", "shrub": '"', "timber": "W", "rubble": "x", "masonry": "m",
    "stonework": "n", "mortared_wall": "w", "concrete": "N", "steel_plate": "P", "glass": "g",
    "ceramic": "e", "charcoal": "h", "ash": "a", "lime": "l", "air": " ",
}
SYM_BY_ID = [SYMBOL.get(v.name, "?") for v in M.VOXELS]
HEIGHT = "ihgfedcba0123456789"      # -9 .. +9 relative to the ground you stand on


def bearing(dx, dz):
    if dx == 0 and dz == 0:
        return "here"
    names = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
    return names[int(round(math.atan2(dz, dx) / (math.pi / 4))) % 8]


def pos3(w, p):
    return [int(p[0]), int(p[1]) - w.sea, int(p[2])]


def column_top(w, x, z):
    """Layer of the highest non-air voxel (includes water and foliage)."""
    col = w.vox[x, z]
    k = int(w.top[x, z])
    kk = k + 1
    while kk < w.Y and col[kk] != M.AIR:
        k = kk
        kk += 1
    return k


def local_map(w, g):
    rows, relief, seen = [], [], set()
    others = {(o.x, o.z): o for o in w.giants.values() if o is not g and o.status != "destroyed"}
    burning_cols = {(x, z) for (x, _k, z) in w.burning}
    for z in range(g.z - MAP_R, g.z + MAP_R + 1):
        row, rel = "", ""
        for x in range(g.x - MAP_R, g.x + MAP_R + 1):
            if not (0 <= x < w.X and 0 <= z < w.Z):
                row += "#"
                rel += "#"
                continue
            k = column_top(w, x, z)
            s = SYM_BY_ID[int(w.vox[x, z, k])]
            seen.add(M.VOXELS[int(w.vox[x, z, k])].name)
            if (x, z) == (g.x, g.z):
                s = "@"
            elif (x, z) in others:
                s = "&"
            elif (x, z) in burning_cols:
                s = "*"
            row += s
            d = int(w.top[x, z]) - (g.k - 1)
            rel += HEIGHT[max(-9, min(9, d)) + 9]
        rows.append(row)
        relief.append(rel)
    legend = {SYMBOL[n]: n for n in sorted(seen) if n in SYMBOL}
    legend.update({"@": "you", "&": "another giant", "*": "fire", "#": "edge of the region"})
    return {
        "top_left": [g.x - MAP_R, g.z - MAP_R],
        "note": "rows run north to south, columns west to east; one character per voxel column",
        "surface": rows,
        "height": relief,
        "height_note": "top of solid ground or structure relative to the ground under you: "
                       "0 level, 1-9 higher, a-i lower (a = 1 down)",
        "legend": legend,
    }


def observe(w, g):
    night = w.daylight() < 0.08
    lit = any(it.props.get("burning") for it in g.items())
    see = SEE_ITEMS if (not night or lit) else 8
    near, more = [], {}
    cands = []
    for it in w.items_near(g.x, g.k, g.z, see, 8):
        d = max(abs(it.pos[0] - g.x), abs(it.pos[2] - g.z))
        cands.append((d, it.id, it))
    cands.sort(key=lambda c: c[:2])
    shown = {}
    for d, _id, it in cands:
        # List the nearest few of each kind; summarise the rest so cars don't drown everything.
        if len(near) < 30 and shown.get(it.name, 0) < 4:
            shown[it.name] = shown.get(it.name, 0) + 1
            b = it.brief()
            b["at"] = pos3(w, it.pos)
            b["dist"] = d
            near.append(b)
        else:
            more[it.name] = more.get(it.name, 0) + 1
    giants = []
    for o in w.giants.values():
        if o is g:
            continue
        d = max(abs(o.x - g.x), abs(o.z - g.z))
        if d <= SEE_GIANTS and (not night or d <= 40):
            entry = {"name": o.name, "at": pos3(w, o.pos), "dist": d, "bearing": bearing(o.x - g.x, o.z - g.z),
                     "doing": o.doing, "state": o.status,
                     "condition": "pristine" if o.integrity > 90 else "damaged" if o.integrity > 40 else "badly damaged",
                     "carrying": [it.name for it in o.items()][:8]}
            if o.said and w.tick - o.said[1] < 90:
                entry["last_said"] = o.said[0]
            giants.append(entry)
    fires = [p for p in w.burning if max(abs(p[0] - g.x), abs(p[2] - g.z)) <= SEE_FIRE]
    fire_items = [w.items[i].pos for i in w.burning_items if i in w.items and w.items[i].pos
                  and max(abs(w.items[i].pos[0] - g.x), abs(w.items[i].pos[2] - g.z)) <= SEE_FIRE]
    fires += fire_items
    fire = None
    if fires:
        nearest = min(fires, key=lambda p: max(abs(p[0] - g.x), abs(p[2] - g.z)))
        fire = {"burning_voxels_in_sight": len(fires), "nearest": pos3(w, nearest),
                "dist": max(abs(nearest[0] - g.x), abs(nearest[2] - g.z)),
                "bearing": bearing(nearest[0] - g.x, nearest[2] - g.z)}
    sites = []
    for s in w.sites:
        d = max(abs(s["x"] - g.x), abs(s["z"] - g.z))
        if d <= SEE_SITES and s["kind"] != "car_park":
            sites.append({"name": s["name"] or s["kind"], "kind": s["kind"], "x": s["x"], "z": s["z"],
                          "dist": d, "bearing": bearing(s["x"] - g.x, s["z"] - g.z)})
    sites.sort(key=lambda s: s["dist"])
    signs = [{"at": pos3(w, p), "text": t} for p, t in w.signs.items()
             if max(abs(p[0] - g.x), abs(p[2] - g.z)) <= 30]
    under = w.mat(g.x, g.k - 1, g.z).name
    load = g.load()
    out = {
        "time": {"tick": w.tick, "clock": w.clock(), "light": "night" if night else "day",
                 "weather": "rain" if w.raining else "dry", "wind": w.wind_name()},
        "you": {
            "name": g.name, "at": pos3(w, g.pos), "standing_on": under, "state": g.status,
            "energy_kwh": round(g.energy, 1), "energy_max": g.max_energy,
            "integrity_pct": round(g.integrity, 1),
            "carrying": [it.brief() for it in g.items()],
            "load": f"{kg(load)} of {kg(CARRY_KG + g.haul())}",
            "doing": g.doing,
            "queued": [a.get("do") for a in g.queue][:12],
        },
        "map": local_map(w, g),
        "items_nearby": near,
        "giants_in_sight": giants,
        "landmarks": sites[:12],
        "events": g.inbox,
    }
    if more:
        out["more_items_nearby"] = more
    if fire:
        out["fire"] = fire
    if signs:
        out["writing_nearby"] = signs
    if g.advice:
        out["advice_from_your_human"] = g.advice
    if g.notes:
        out["your_notes"] = g.notes[-12:]
    g.inbox = []
    g.advice = []
    return out


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
def inspect(w, g, q):
    """Look closely at an item, a giant, or a voxel column."""
    if "item" in q:
        it = w.items.get(int(q["item"]))
        if it is None:
            return {"error": "no such item"}
        where = it.pos or (w.giants[it.holder].pos if it.holder in w.giants else None)
        if where is None or max(abs(where[0] - g.x), abs(where[2] - g.z)) > 40:
            return {"error": "too far away to make out (40 voxels)"}
        d = it.describe()
        if it.pos:
            d["at"] = pos3(w, it.pos)
        if it.holder:
            d["held_by"] = w.giants[it.holder].name
        wired = [b if a == it.id else a for a, b, _m in w.links if it.id in (a, b)]
        if wired:
            d["wired_to"] = [f"#{i} {w.items[i].name}" for i in wired if i in w.items]
        if "powered" in it.props:
            d["powered"] = it.props["powered"]
        if it.props.get("stored"):
            d["inside"] = [dict(w.items[i].brief()) for i in it.props["stored"] if i in w.items][:30]
        if it.props.get("trigger") in w.items:
            t = w.items[it.props["trigger"]]
            d["runs_only_while_active"] = f"#{t.id} {t.name}"
        return d
    if "giant" in q:
        o = next((o for o in w.giants.values() if o.name == q["giant"]), None)
        if o is None or max(abs(o.x - g.x), abs(o.z - g.z)) > SEE_GIANTS:
            return {"error": "no such giant in sight"}
        return {"name": o.name, "at": pos3(w, o.pos), "state": o.status, "doing": o.doing,
                "integrity_pct": round(o.integrity), "carrying": [it.brief() for it in o.items()],
                "energy": "unknown (you can't see inside another giant)"}
    try:
        x, z = int(q["x"]), int(q["z"])
    except (KeyError, TypeError, ValueError):
        return {"error": "give item, giant, or x and z (optionally y)"}
    if not (0 <= x < w.X and 0 <= z < w.Z) or max(abs(x - g.x), abs(z - g.z)) > 40:
        return {"error": "that column is too far away to make out (40 voxels)"}
    col = w.vox[x, z]
    top = column_top(w, x, z)
    runs = []
    k = top
    low = max(0, min(top, g.k) - 6)
    while k >= low:
        vid = int(col[k])
        j = k
        while j - 1 >= low and int(col[j - 1]) == vid:
            j -= 1
        run = {"y": [j - w.sea, k - w.sea] if j != k else k - w.sea, "material": M.VOXELS[vid].name}
        if any((x, kk, z) in w.burning for kk in range(j, k + 1)):
            run["burning"] = True
        runs.append(run)
        k = j - 1
    out = {"x": x, "z": z, "column_top_down": runs,
           "items_here": [dict(it.brief(), at=pos3(w, it.pos)) for it in w.items_near(x, top, z, 0, 40)]}
    if "y" in q:
        v = w.mat(x, int(q["y"]) + w.sea, z)
        out["voxel"] = describe_voxel(w, v)
        p = (x, int(q["y"]) + w.sea, z)
        if p in w.signs:
            out["voxel"]["writing"] = w.signs[p]
        if p in w.soaked:
            out["voxel"]["soaked_in_fuel"] = True
    return out


def describe_voxel(w, v):
    d = {"material": v.name, "kind": v.kind, "hardness": v.hardness,
         "mass_per_voxel": kg(v.mass(w.voxel_m3)),
         "can_overhang_voxels": v.span, "made_of": v.substance,
         "substance": M.SUBSTANCES[v.substance].describe()}
    if v.flammability > 0:
        d["flammability"] = v.flammability
    if v.yields:
        d["breaks_into"] = {s: kg(v.mass(w.voxel_m3) * f) for s, f in v.yields}
    if v.loot:
        d["contains"] = "salvage (varies)"
    return d


def survey(w, g, q):
    """Count what is in an area the giant can see."""
    x0, z0 = int(q.get("x", g.x)), int(q.get("z", g.z))
    r = max(1, min(40, int(q.get("r", 15))))
    if max(abs(x0 - g.x), abs(z0 - g.z)) > 80:
        return {"error": "that area is out of sight (80 voxels)"}
    xa, xb = max(0, x0 - r), min(w.X, x0 + r + 1)
    za, zb = max(0, z0 - r), min(w.Z, z0 + r + 1)
    block = w.vox[xa:xb, za:zb]
    counts = {}
    ids, n = _unique(block)
    for vid, c in zip(ids, n):
        if vid != M.AIR:
            counts[M.VOXELS[vid].name] = int(c)
    surface = {}
    for x in range(xa, xb):
        for z in range(za, zb):
            name = M.VOXELS[int(w.vox[x, z, column_top(w, x, z)])].name
            surface[name] = surface.get(name, 0) + 1
    items = {}
    for it in w.items_near(x0, g.k, z0, r, 40):
        e = items.setdefault(it.name, {"count": 0, "kg": 0})
        e["count"] += 1
        e["kg"] += round(it.total_mass)
    above = {k: v for k, v in counts.items() if M.V[k].kind != "liquid" and not M.V[k].natural}
    return {"centre": [x0, z0], "radius": r, "surface_columns": dict(sorted(surface.items(), key=lambda kv: -kv[1])),
            "structure_voxels": dict(sorted(above.items(), key=lambda kv: -kv[1])),
            "items": dict(sorted(items.items(), key=lambda kv: -kv[1]["count"])[:40]),
            "height_range_y": [int(w.top[xa:xb, za:zb].min()) - w.sea, int(w.top[xa:xb, za:zb].max()) - w.sea]}


def _unique(block):
    import numpy as np
    return np.unique(block, return_counts=True)


def region_map(w, g):
    cm = w.meta.get("coarse_map", {})
    k = cm.get("cell_voxels", 16)
    return {"note": f"The region as mapped before the collapse. Each character covers about {k} x {k} voxels. "
                    f"Things may have changed.",
            "size_voxels": [w.X, w.Z], "rows_north_to_south": cm.get("rows", []), "legend": cm.get("legend", ""),
            "you_are_at_map_cell": [int(g.x / k), int(g.z / k)],
            "landmarks": [{"name": s["name"] or s["kind"], "kind": s["kind"], "x": s["x"], "z": s["z"]}
                          for s in w.sites if s["kind"] != "car_park"],
            "car_parks": len([s for s in w.sites if s["kind"] == "car_park"])}


def substance_info(q):
    name = str(q.get("name", ""))
    if name in M.SUBSTANCES:
        return dict(M.SUBSTANCES[name].describe(), name=name,
                    stacks_into_voxel=M.PLACE_AS.get(name, "no"))
    return {"error": f"unknown substance '{name}'", "known": sorted(M.SUBSTANCES)}


RULES = f"""You are a giant: a 12 m machine in a ruined, empty landscape built from the real map.
The world is made of voxels about 3 m on a side; you are 4 voxels tall. Other giants are run by other minds.
There is no set goal and no score. Survive, and do whatever you judge worthwhile.

COORDINATES  [x, y, z]: x grows east, z grows south, y is height (0 = just above sea level).
REACH  You can touch voxels and items up to {REACH} voxels away sideways, {REACH_UP} up and {REACH_DOWN} down.
ENERGY  Everything costs energy (kWh). At zero you go dormant and can only speak. Refill by burning fuel
in your reactor (consume), drawing charge from batteries (charge), or standing by a powered charger.
BODY  Damage lowers integrity; at zero you are destroyed. Repair with steel and electronics.
CARRYING  Up to {kg(CARRY_KG)}. Loose material is carried by weight; a voxel of earth or masonry is far heavier
than one load, so building takes several trips, or a cart.

THE WORLD IS PHYSICAL, NOT A LIST OF RECIPES
- Every material has real properties (hardness, density, melting point, flammability, conductivity...).
  Ask with query substance, or inspect anything you can see.
- Breaking needs a tool at least as hard as the job; bare hands manage soft things only.
- Unsupported things fall. Structures need a path down to the ground and can only overhang so far.
- Fire spreads through anything flammable, leans with the wind, dies without air, and bakes or melts
  what it touches. Hot enough fires need the right fuel, an enclosure, and forced air.
- Water floods any opening that reaches it at or below its level.
- Fuel, gas and big batteries explode in fire. Electricity flows through wired components.
- A device wired to a trigger (switch, timer, pressure plate, sensor, radio trigger) runs only while
  that trigger is active. Things can be stored in containers and carried in them.
- What an object can do comes from its shape and substance. Shapes you can make: {', '.join(FORMS)}.
  Parts can be joined into tools and machines. Try things: failures tell you what was missing.

ACTIONS  Send a list; they run in order, each taking game time. A failure cancels the rest.
{', '.join(VERBS)}
Each action is {{"do": verb, ...}}. Common parameters:
  move_to {{x, z}} or {{target: item id or giant name}}       break {{x, y, z}} or {{item}}
  pick_up {{item, kg?}}   drop {{item, kg?, x?, y?, z?}} or {{item, into: container}}   place {{material, x, y, z}}
  throw {{item, x, z}}
  give {{item, to}}       make {{form, from: item, kg?}}       join {{items: [ids], with?: item}}
  ignite {{x, y, z}} or {{item}}   extinguish {{x, y, z}}      fill {{container, x, y, z}} or {{container, from}}
  pour {{container, x?, y?, z?}} or {{container, into}}        mix {{items: [ids]}}
  consume {{item}}        charge {{from: item}} or {{to: giant, kwh}}
  connect {{a, b}}        disconnect {{a, b}}                  switch {{item, on, seconds?}}
  fan {{x, y, z, seconds}}   say {{text}}   whisper {{to, text}}   radio {{text}}   write {{text, x, y, z}} or {{text, item}}
  hit {{target}}   push {{target}}   repair {{target?}}   wait {{seconds}}   label {{item, text}}
Speech carries about {HEAR} voxels. Other giants hear and see what you do nearby.

QUESTIONS (free, instant): inspect {{item}} | {{giant}} | {{x, z, y?}}; survey {{x, z, r}}; map; substance {{name}}.
"""
