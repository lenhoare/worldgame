"""Generic physical processes. None of them know about any particular object.

  gravity    loose material falls; items fall; unsupported structures collapse
  structure  a voxel needs a vertical path to the ground, or a sideways one
             no longer than its material's span
  fire       spreads by flammability, wind and dryness; needs air; heats and
             transforms what it touches (clay -> ceramic, chalk -> lime,
             sand -> glass, smothered wood -> charcoal); sets off explosives
  water      floods any opening at or below the level of the body it joins
  explosion  destroys by hardness and distance, ignites, injures, chains
  growth     bare soil greens over; scrub creeps in
"""

from collections import deque

from . import materials as M
from .items import KINDS, LOOT

N6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))   # (dx, dk, dz)
SIDES = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))
AIR = M.AIR
SUPPORT_LIMIT = 6000
TENSILE = {M.ID[n] for n in ("wood", "timber", "steel_frame", "steel_plate", "roof_metal")}
FIRE_DT = 2
FIRE_BASE = {"wood": 800, "biomass": 650, "fibre": 650, "fabric": 650, "charcoal": 1100, "fuel": 900,
             "plastic": 750, "rubber": 750, "asphalt": 700}


def structural(vid):
    v = M.VOXELS[vid]
    return v.kind == "solid" and not v.natural


# ---------------------------------------------------------------------------
# Changes -> consequences
# ---------------------------------------------------------------------------
def process_changes(w, budget=20000):
    n = 0
    liquid = w.t["liquid"]
    while w.changes and n < budget:
        x, k, z, old, new = w.changes.popleft()
        n += 1
        mo, mn = M.VOXELS[old], M.VOXELS[new]
        if not mn.solid:
            if mo.solid:
                settle_column(w, x, z, k)
                for iid in list(w.items_at.get((x, k + 1, z), ())):
                    if iid in w.items:
                        w.settle(w.items[iid])
                for dx, dk, dz in N6:
                    if dk >= 0 and structural(w.get(x + dx, k + dk, z + dz)):
                        w.support_queue.append((x + dx, k + dk, z + dz))
            w.burning.pop((x, k, z), None) if new != old and mn.flammability == 0 else None
            if new == AIR:
                for dx, dk, dz in N6:
                    if liquid[w.get(x + dx, k + dk, z + dz)] and w.inside(x + dx, k + dk, z + dz):
                        w.water_frontier.append((x, k, z))
                        break
        else:
            if mn.flammability == 0:
                w.burning.pop((x, k, z), None)
            if mn.kind == "granular":
                settle_column(w, x, z, k - 1)
            elif not mn.natural:
                w.support_queue.append((x, k, z))
            for iid in list(w.items_at.get((x, k, z), ())):     # items are pushed up, not buried
                if iid in w.items:
                    w.settle(w.items[iid])
    return n


def settle_column(w, x, z, k0):
    """Loose material above layer k0 falls into any gap beneath it."""
    col = w.vox[x, z]
    solid, gran = w.t["solid"], w.t["granular"]
    k = max(1, k0)
    while k < w.Y and not solid[col[k]]:
        k += 1                                  # first solid voxel above the gap
        if k - k0 > 2:
            return
    while k < w.Y and gran[col[k]]:
        j = k
        while j > 0 and not solid[col[j - 1]]:
            j -= 1
        if j == k:
            break
        v = int(col[k])
        below = int(col[j])
        col[j] = v
        col[k] = AIR
        w.changes.append((x, j, z, below, v))
        w.changes.append((x, k, z, v, AIR))
        k += 1
    w._retop(x, z)
    w.touch(x, z)


# ---------------------------------------------------------------------------
# Structural support
# ---------------------------------------------------------------------------
def check_support(w, max_seeds=8):
    seen = set()
    done = 0
    while w.support_queue and done < max_seeds:
        p = w.support_queue.popleft()
        if p in seen or not w.inside(*p) or not structural(w.get(*p)):
            continue
        done += 1
        comp = {}
        anchored = set()
        braced = set()
        q = deque([p])
        comp[p] = w.get(*p)
        capped = False
        while q:
            x, k, z = q.popleft()
            for dx, dk, dz in N6:
                n = (x + dx, k + dk, z + dz)
                if n in comp:
                    continue
                vid = w.get(*n)
                if structural(vid):
                    if len(comp) >= SUPPORT_LIMIT:
                        capped = True
                        anchored.add((x, k, z))     # the unexplored part is assumed to hold
                        continue
                    comp[n] = vid
                    q.append(n)
                elif dk == -1 and M.VOXELS[vid].solid:
                    anchored.add((x, k, z))         # resting on ground or packed rubble
                elif dk == 0 and M.VOXELS[vid].solid:
                    braced.add((x, k, z))           # butted against ground at the same level
        seen.update(comp)
        best = {a: 0 for a in anchored}
        dq = deque(anchored)
        for b in braced:
            if b not in best and M.VOXELS[comp[b]].span >= 1:
                best[b] = 1
                dq.append(b)
        while dq:
            u = dq.popleft()
            d = best[u]
            x, k, z = u
            up = (x, k + 1, z)
            if up in comp and best.get(up, 99) > d:
                best[up] = d
                dq.appendleft(up)
            for dx, dk, dz in SIDES:
                n = (x + dx, k, z + dz)
                if n in comp and d + 1 <= M.VOXELS[comp[n]].span and best.get(n, 99) > d + 1:
                    best[n] = d + 1
                    dq.append(n)
            dn = (x, k - 1, z)
            if dn in comp and comp[dn] in TENSILE and d + 1 <= M.VOXELS[comp[dn]].span \
                    and best.get(dn, 99) > d + 1:
                best[dn] = d + 1
                dq.append(dn)
        falling = [v for v in comp if v not in best]
        if falling and not (capped and len(falling) > SUPPORT_LIMIT // 2):
            collapse(w, falling)


def collapse(w, falling, cause="collapsed"):
    """Unsupported voxels come down as rubble and salvage where they stood."""
    falling.sort(key=lambda p: p[1])
    debris = {}
    low = {}
    for x, k, z in falling:
        v = w.mat(x, k, z)
        w.burning.pop((x, k, z), None)
        w.vox[x, z, k] = AIR
        mass = v.mass(w.voxel_m3)
        col = debris.setdefault((x, z), {})
        low.setdefault((x, z), k)
        organic = M.SUBSTANCES[v.substance].has("o")
        for sub, frac in v.yields:
            col[sub] = col.get(sub, 0) + mass * frac * (0.9 if organic else 0.6)
        if not v.yields:
            col["rubble"] = col.get("rubble", 0) + mass * 0.5
        elif not organic:
            col["rubble"] = col.get("rubble", 0) + mass * 0.3
        if v.loot and w.rng.random() < 0.4:
            col.setdefault("_loot", []).append((v.loot, (x, k, z)))
    cx = cz = 0
    for (x, z), col in debris.items():
        w._retop(x, z)
        w.touch(x, z)
        k = w.surface(x, z) + 1
        for g in w.giants.values():
            if g.x == x and g.z == z and g.k <= low[(x, z)]:
                tonnes = sum(m for s, m in col.items() if s != "_loot") / 1000.0
                g.hurt(min(70, 4 + tonnes * (low[(x, z)] - g.k + 1) * 0.6), "falling debris")
        for sub, kg in col.items():
            if sub == "_loot":
                for table, pos in kg:
                    roll_loot(w, table, (x, k, z), pos, 0.6)
            else:
                w.add_bulk(sub, kg, (x, k, z))
        compact_pile(w, (x, k, z))
        w.changes.append((x, low[(x, z)], z, M.ID["rubble"], AIR))   # let water and neighbours react
        cx += x
        cz += z
    n = len(falling)
    w.stats["collapsed"] += n
    c = (cx // len(debris), w.surface(cx // len(debris), cz // len(debris)), cz // len(debris))
    w.emit("collapse", f"A structure {cause}: {n} voxel{'s' if n != 1 else ''} came down.", c,
           radius=60 + min(200, n * 3))


def compact_pile(w, pos):
    """Enough loose rubble, soil, sand... in one place becomes a voxel of it."""
    for iid in list(w.items_at.get(pos, ())):
        it = w.items.get(iid)
        if not it or not it.bulk or it.mat not in ("rubble", "soil", "sand", "gravel", "clay", "ash"):
            continue
        v = M.V[it.mat]
        per = v.mass(w.voxel_m3)
        x, k, z = pos
        while it.mass >= per and w.get(x, k, z) == AIR and k < w.Y - 1:
            it.mass -= per
            w.set(x, k, z, v.id)
            k += 1
        if it.mass < 1:
            w.remove(it)
        elif it.id in w.items:
            w.put(it, (x, k, z))


def roll_loot(w, table, where, key, scale=1.0):
    """Deterministic salvage for a broken building voxel (same voxel, same loot)."""
    import random
    r = random.Random(hash((w.seed, table) + tuple(key)) & 0xFFFFFFFF)
    out = []
    for chance, what, lo, hi in LOOT.get(table, ()):
        if r.random() >= chance:
            continue
        if what in M.SUBSTANCES:
            out.append(w.add_bulk(what, r.uniform(lo, hi) * scale, where))
        else:
            for _ in range(r.randint(lo, hi)):
                out.append(spawn(w, what, where, r))
    return [o for o in out if o]


def burn_out_loot(w, table, pos):
    """What is left of a room's contents after a fire: metal, glass, and anything that can explode."""
    import random
    r = random.Random(hash((w.seed, table) + tuple(pos)) & 0xFFFFFFFF)
    for chance, what, lo, hi in LOOT.get(table, ()):
        if r.random() >= chance:
            continue
        if what in M.SUBSTANCES:
            amount = r.uniform(lo, hi)
            if M.SUBSTANCES[what].flammability == 0:
                w.add_bulk(what, amount * 0.6, pos)
        else:
            n = r.randint(lo, hi)
            k = KINDS[what]
            if k.get("explosive") or what in ("fuel_can", "fuel_tank") or k.get("cap_kwh", 0) >= 30:
                for _ in range(n):
                    spawn(w, what, pos, r)          # ...and the fire will find it
            else:
                for sub, kg_ in k.get("parts", [(k.get("mat", "steel"), k["mass"])]):
                    if sub in M.SUBSTANCES and M.SUBSTANCES[sub].flammability == 0:
                        w.add_bulk(sub, kg_ * n * 0.6, pos)


def spawn(w, kind, pos, r=None):
    """Create a salvage object with sensible random contents."""
    r = r or w.rng
    k = KINDS[kind]
    it = w.new_item(kind, pos=None)
    if "cap_kwh" in k:
        it.props["charge"] = round(k["cap_kwh"] * r.uniform(0.2, 0.95), 1)
    if kind in ("fuel_can", "fuel_tank"):
        it.props["contents"] = {"fuel": round(k["cap_l"] * 0.75 * r.uniform(0.3, 1.0))}
    if kind == "generator":
        it.props["contents"] = {"fuel": round(150 * r.uniform(0.0, 0.6))}
        it.props["on"] = False
    if kind == "car":
        if r.random() < 0.2:
            it.props["ev"] = True
        else:
            it.props["contents"] = {"fuel": round(30 * r.uniform(0.0, 1.0))}
    if k.get("comp") == "sink":
        it.props["on"] = kind in ("charger", "sensor")
    w.put(it, pos)
    return it


# ---------------------------------------------------------------------------
# Fire and heat
# ---------------------------------------------------------------------------
def has_air(w, x, k, z):
    v = w.mat(x, k, z)
    if v.kind == "foliage" or "interior" in v.tags or "roof" in v.tags:
        return True                                   # rooms and canopies hold their own air
    for dx, dk, dz in N6:
        if w.get(x + dx, k + dk, z + dz) == AIR:
            return True
    return False


def ignite_voxel(w, pos, force=False):
    v = w.mat(*pos)
    if pos in w.burning or v.flammability <= 0 or not has_air(w, *pos):
        return False
    if not force and w.raining and w.exposed(*pos) and w.rng.random() < 0.7:
        return False
    w.burning[pos] = v.fuel * (0.6 + 0.8 * w.rng.random())
    w.rev += 1
    return True


def ignite_item(w, it):
    if it.props.get("burning") or it.sub.flammability <= 0:
        return False
    it.props["burning"] = True
    w.burning_items.add(it.id)
    w.mark(it)
    return True


def fire_temp(w, pos, fuel_sub):
    t = FIRE_BASE.get(fuel_sub, 700)
    x, k, z = pos
    walls = 0
    for dx, dk, dz in N6:
        m = w.mat(x + dx, k + dk, z + dz)
        if m.solid and m.flammability == 0:
            walls += 1
    if walls >= 4:
        t += 250
    if w.blow.get(pos, 0) > w.tick:
        t += 350
    return t


def _spread(w, pos, dt):
    """A fire at pos tries to light the flammable voxels around it."""
    x, k, z = pos
    wx, wz, ws = w.wind
    for dx, dk, dz in N6:
        n = (x + dx, k + dk, z + dz)
        v = w.mat(*n)
        if n in w.burning:
            continue
        if v.flammability <= 0:
            if n in w.soaked and v.id != AIR and w.rng.random() < 0.5 * dt:
                w.burning[n] = 30.0                       # a pool of spilled fuel catches
            continue
        rate = v.flammability * (0.4 + 0.6 * w.dryness)
        if dk == 1:
            rate *= 2.0                                   # flames rise
        rate *= 1.0 + ws * 1.5 * (dx * wx + dz * wz)      # and lean with the wind
        if n in w.soaked:
            rate *= 6.0
        if w.raining and w.exposed(*n):
            rate *= 0.3
        if w.rng.random() < rate * dt / 10.0:
            ignite_voxel(w, n, force=True)


def heat_items_at(w, pos, temp, dt):
    for iid in list(w.items_at.get(pos, ())):
        it = w.items.get(iid)
        if it:
            heat_item(w, it, temp, dt)


def heat_item(w, it, temp, dt):
    """Apply heat to one item: it may ignite, explode, or transform."""
    p = it.props
    k = KINDS.get(it.kind, {})
    fuel_l = p.get("contents", {}).get("fuel", 0)
    if temp >= 250 and (k.get("explosive") or fuel_l >= 5 or (k.get("cap_kwh", 0) >= 30 and p.get("charge", 0) > 5)):
        power = k.get("explosive") or min(14.0, 2.0 + fuel_l / 15.0) if (k.get("explosive") or fuel_l >= 5) else 3.0
        pos = it.pos
        name = it.name
        w.remove(it)
        explode(w, pos, power, f"A {name} exploded")
        return
    if temp >= 300 and it.sub.flammability > 0 and not p.get("burning"):
        ignite_item(w, it)
        return
    if temp > p.get("temp", 15):
        p["temp"] = temp
        w.hot_items.add(it.id)
        w.mark(it)
    ht = it.sub.heat_to
    if ht and not it.sub.has("l"):
        need = ht[0]
        if it.mat == "sand" and any(w.items[i].mat in ("ash", "lime") for i in w.items_at.get(it.pos, ())
                                    if i in w.items):
            need = 1100                                   # a flux lowers the melting point
        if temp >= need and it.mat != "wood":
            p["cook"] = p.get("cook", 0) + dt
            if p["cook"] >= 20 + it.mass / 100.0:
                old = it.name
                it.mat = ht[1]
                p.pop("cook", None)
                w.mark(it)
                w.emit("transform", f"Heat turned {old} into {it.name}.", it.pos, radius=8)


def fire_tick(w):
    dt = FIRE_DT
    liquid = w.t["liquid"]
    # --- burning voxels ---
    for pos in list(w.burning):
        x, k, z = pos
        vid = w.get(*pos)
        v = M.VOXELS[vid]
        if v.flammability <= 0:
            # Spilled fuel burns on anything, for a while, without consuming what it lies on.
            if pos in w.soaked and w.burning[pos] > 0 and not w.t["liquid"][vid]:
                _spread(w, pos, dt)
                for dx, dk, dz in ((0, 0, 0), (0, 1, 0)) + SIDES:
                    heat_items_at(w, (x + dx, k + dk, z + dz), 900, dt)
                w.burning[pos] -= dt
                continue
            w.burning.pop(pos, None)
            w.soaked.discard(pos)
            continue
        wet = any(liquid[w.get(x + dx, k + dk, z + dz)] for dx, dk, dz in N6)
        rained = w.raining and w.exposed(*pos) and w.rng.random() < 0.06
        if wet or rained:
            w.burning.pop(pos, None)
            w.rev += 1
            continue
        if not has_air(w, *pos):                          # smothered: wood chars instead of burning
            w.burning.pop(pos, None)
            if v.substance == "wood":
                w.set(x, k, z, M.ID["charcoal"])
            continue
        temp = fire_temp(w, pos, v.substance)
        _spread(w, pos, dt)
        _heat_voxels_around(w, pos, temp, dt)
        for dx, dk, dz in ((0, 1, 0),) + SIDES:
            heat_items_at(w, (x + dx, k + dk, z + dz), temp, dt)
        for g in w.giants.values():
            if g.x == x and g.z == z and 0 <= g.k - k <= 1:
                g.hurt(0.6 * dt, "fire")
        w.burning[pos] -= dt
        if w.burning.get(pos, 1) <= 0:
            w.burning.pop(pos, None)
            w.soaked.discard(pos)
            w.stats["burnt"] += 1
            if v.substance == "wood":
                w.add_bulk("ash", v.mass(w.voxel_m3) * 0.03, (x, k, z))
            w.set(x, k, z, M.ID.get(v.burn_to, AIR))
            if v.loot:
                burn_out_loot(w, v.loot, (x, k, z))
    # --- burning items (fuel piles, torches) ---
    for iid in list(w.burning_items):
        it = w.items.get(iid)
        if not it or not it.props.get("burning"):
            w.burning_items.discard(iid)
            continue
        pos = it.pos
        blown = pos is not None and w.blow.get(pos, 0) > w.tick
        if pos is not None:
            x, k, z = pos
            if liquid[w.get(x, k, z)] or (w.raining and w.exposed(*pos) and w.rng.random() < 0.05):
                it.props.pop("burning", None)
                w.burning_items.discard(iid)
                w.mark(it)
                continue
            if not has_air(w, x, k, z) and w.get(x, k + 1, z) != AIR:
                it.props.pop("burning", None)             # sealed in: wood becomes charcoal
                w.burning_items.discard(iid)
                if it.mat == "wood":
                    it.mat = "charcoal"
                    it.mass *= 0.3
                    w.emit("transform", "Starved of air, the burning wood turned to charcoal.", pos, radius=8)
                w.mark(it)
                continue
            temp = fire_temp(w, pos, it.mat)
            _spread(w, pos, dt)
            _heat_voxels_around(w, pos, temp, dt)
            for q in (pos, (x, k + 1, z)):
                for oid in list(w.items_at.get(q, ())):
                    o = w.items.get(oid)
                    if o and o is not it:
                        heat_item(w, o, temp, dt)
            for g in w.giants.values():
                if (g.x, g.k, g.z) == pos:
                    g.hurt(0.4 * dt, "fire")
        it.mass -= (2.0 + 0.005 * it.mass) * (2.0 if blown else 1.0) * dt   # big fires burn faster
        it.props["temp"] = 600
        if it.mass <= 0:
            ash = None
            if pos is not None:
                ash = pos
            mat = it.mat
            w.remove(it)
            if ash and mat in ("wood", "charcoal", "biomass", "fibre"):
                w.add_bulk("ash", 40, ash)
    # --- electric heaters act like a clean fire ---
    for iid, temp in list(w.heaters.items()):
        it = w.items.get(iid)
        if it and it.pos:
            heat_items_at(w, it.pos, temp, dt)
            _heat_voxels_around(w, it.pos, temp, dt)
    # --- cooling ---
    for iid in list(w.hot_items):
        it = w.items.get(iid)
        if not it:
            w.hot_items.discard(iid)
            continue
        t = it.props.get("temp", 15)
        t -= max(2.0, 0.012 * (t - 15)) * dt
        if t <= 20:
            it.props.pop("temp", None)
            w.hot_items.discard(iid)
        else:
            it.props["temp"] = t
    for pos in [p for p, until in w.blow.items() if until <= w.tick]:
        del w.blow[pos]


def _heat_voxels_around(w, pos, temp, dt):
    """Non-flammable voxels beside a fire bake: clay fires, chalk burns to lime."""
    x, k, z = pos
    for dx, dk, dz in N6:
        n = (x + dx, k + dk, z + dz)
        v = w.mat(*n)
        ht = M.VOXEL_HEAT_TO.get(v.name)
        if ht and temp >= ht[0]:
            w.heat[n] = w.heat.get(n, 0) + dt
            if w.heat[n] >= 90:
                del w.heat[n]
                w.set(n[0], n[1], n[2], M.ID[ht[1]])


def explode(w, pos, power, text="An explosion"):
    """Blast: destroys by hardness and distance, ignites, injures, sets off more."""
    if pos is None:
        return
    x0, k0, z0 = pos
    R = min(7.0, 1.0 + power / 3.0)
    r = int(R + 1)
    rubble = 0.0
    chain = []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            for dk in range(-r, r + 1):
                d = (dx * dx + dz * dz + dk * dk) ** 0.5
                if d > R + 0.5:
                    continue
                p = (x0 + dx, k0 + dk, z0 + dz)
                if not w.inside(*p):
                    continue
                v = w.mat(*p)
                if v.kind == "liquid" or v.id == AIR:
                    continue
                if v.hardness <= power * (1.0 - d / (R + 0.5)) + 1.0:
                    rubble += v.mass(w.voxel_m3) * 0.15
                    w.burning.pop(p, None)
                    w.set(p[0], p[1], p[2], AIR)
                elif v.flammability > 0 and w.rng.random() < 0.6:
                    ignite_voxel(w, p, force=True)
    for it in w.items_near(x0, k0, z0, r + 2, r + 2):
        k = KINDS.get(it.kind, {})
        if k.get("explosive") or it.props.get("contents", {}).get("fuel", 0) >= 5:
            chain.append(it)
        elif it.sub.flammability > 0 and w.rng.random() < 0.5:
            ignite_item(w, it)
    for g in w.giants.values():
        d = ((g.x - x0) ** 2 + (g.z - z0) ** 2 + (g.k - k0) ** 2) ** 0.5
        if d <= R:
            g.hurt(15 + 55 * (1 - d / R), "an explosion")
        elif d <= 2 * R:
            g.hurt(8, "an explosion")
    if rubble > 100:
        w.add_bulk("rubble", rubble, (x0, min(w.Y - 1, k0 + 1), z0))
    w.emit("explosion", f"{text}!", pos, radius=400)
    for it in chain:
        if it.id in w.items:
            heat_item(w, it, 900, 1)


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------
def water_tick(w, budget=400):
    """Water fills any opening at or below the level of the body it touches."""
    liquid = w.t["liquid"]
    sea_id = M.ID["seawater"]
    sea_level = w.sea - 1
    n = 0
    while w.water_frontier and n < budget:
        x, k, z = w.water_frontier.popleft()
        n += 1
        if not w.inside(x, k, z):
            continue
        cur = w.get(x, k, z)
        if cur != AIR and M.VOXELS[cur].kind != "foliage":
            continue
        fill = None
        for dx, dk, dz in N6:
            if dk == -1:
                continue                                  # water does not rise from below on its own
            p = (x + dx, k + dk, z + dz)
            vid = w.get(*p)
            if not liquid[vid] or not w.inside(*p):
                continue
            level = sea_level if vid == sea_id else w.water_level.get(p, p[1])
            if k <= level:
                fill = (vid, level)
                break
        if fill is None:
            # also filled from below when the body's surface is higher than this cell
            p = (x, k - 1, z)
            vid = w.get(*p)
            if liquid[vid] and w.inside(*p):
                level = sea_level if vid == sea_id else w.water_level.get(p, p[1])
                if k <= level:
                    fill = (vid, level)
        if fill is None:
            continue
        w.vox[x, z, k] = fill[0]
        if fill[0] != sea_id:
            w.water_level[(x, k, z)] = fill[1]
        w.touch(x, z)
        w.stats["flooded"] += 1
        w.burning.pop((x, k, z), None)
        for iid in list(w.items_at.get((x, k, z), ())):
            it = w.items.get(iid)
            if it:
                it.props.pop("burning", None)
                w.settle(it)
        for dx, dk, dz in N6:
            p = (x + dx, k + dk, z + dz)
            if w.get(*p) == AIR and w.inside(*p) and p[1] <= fill[1]:
                w.water_frontier.append(p)
            w.burning.pop(p, None) if p in w.burning else None
    return n


def flood_notice(w):
    """Tell nearby giants when flooding starts (called when the frontier wakes up)."""
    if w.water_frontier:
        x, k, z = w.water_frontier[0]
        w.emit("flood", "Water is flowing into an opening.", (x, k, z), radius=40)


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------
def growth_tick(w, samples=3000):
    soil, turf, shrub = M.ID["soil"], M.ID["turf"], M.ID["shrub"]
    r = w.rng
    for _ in range(samples):
        x, z = r.randrange(w.X), r.randrange(w.Z)
        k = w.surface(x, z)
        if k < 0 or k >= w.Y - 1:
            continue
        v = int(w.vox[x, z, k])
        if v == soil and w.vox[x, z, k + 1] == AIR and (x, k + 1, z) not in w.items_at and r.random() < 0.15:
            w.vox[x, z, k] = turf
            w.touch(x, z)
        elif v == turf and w.vox[x, z, k + 1] == AIR and r.random() < 0.004 \
                and (x, k + 1, z) not in w.items_at:
            w.vox[x, z, k + 1] = shrub
            w.touch(x, z)
