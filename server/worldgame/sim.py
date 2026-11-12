"""The simulation loop: one tick is one second of game time."""

from . import physics as P
from .giants import Giant
from .items import KINDS
from .worldgen import spawn_point

POWER_DT = 5
POWER_SCALE = 30.0       # electricity runs 30x faster than wall-clock physics, to suit short games
STRICT = False           # tests set this so bugs surface instead of being swallowed
COLOURS = ["#c9a227", "#3f8fd2", "#d2553f", "#4fb06a", "#a05fc9", "#e08a2e", "#3fb7b0", "#c94f8a"]


def add_giant(w, name, total_hint=4):
    gid = 1 + max(w.giants, default=0)
    x, z = spawn_point(w, gid - 1, total_hint)
    g = Giant(w, gid, name, x, z, COLOURS[(gid - 1) % len(COLOURS)])
    w.giants[gid] = g
    w.emit("arrival", f"A giant called {name} has powered up.", g.pos, radius=200)
    return g


def step(w, n=1):
    for _ in range(n):
        w.tick += 1
        for g in list(w.giants.values()):
            try:
                g.tick()
            except Exception as e:                 # one giant's bug must not stop the world
                g.cur, g.queue, g.doing = None, [], "idle"
                g.report(f"internal error, action abandoned: {e!r}", ok=False)
                if STRICT:
                    raise
        if w.changes:
            P.process_changes(w)
        if w.support_queue:
            P.check_support(w)
            if w.changes:
                P.process_changes(w)
        if w.tick % P.FIRE_DT == 0:
            if w.burning or w.burning_items or w.hot_items or w.heaters:
                P.fire_tick(w)
            if w.water_frontier:
                P.water_tick(w)
        if w.tick % POWER_DT == 0:
            power_tick(w)
        if w.tick % 60 == 0:
            w.weather_tick()
        if w.tick % 600 == 0:
            P.growth_tick(w)


def power_tick(w):
    """Solve each wired network: sources feed sinks, batteries buffer."""
    comps = {}
    for a, b, _m in w.links:
        for i in (a, b):
            it = w.items.get(i)
            if it is not None and it.pos is not None and KINDS.get(it.kind, {}).get("comp"):
                comps[i] = it
    w.heaters.clear()
    if not comps:
        return
    parent = {i: i for i in comps}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, _m in w.links:
        if a in comps and b in comps:
            parent[find(a)] = find(b)
    nets = {}
    for i in comps:
        nets.setdefault(find(i), []).append(comps[i])
    hours = POWER_DT / 3600.0 * POWER_SCALE
    sun = w.daylight() * (0.3 if w.raining else 1.0)
    for net in nets.values():
        solar = sum(KINDS[it.kind]["kw"] for it in net if KINDS[it.kind].get("solar")) * sun
        gens = [it for it in net if it.kind == "generator" and it.props.get("on")
                and it.props.get("contents", {}).get("fuel", 0) > 0]
        bats = [it for it in net if KINDS[it.kind]["comp"] == "battery"]
        sinks = []
        for it in net:
            k = KINDS[it.kind]
            if k["comp"] != "sink" or it.props.get("on") is False:
                continue
            if "trigger" in it.props and not trigger_active(w, it.props["trigger"]):
                if it.props.get("powered"):
                    it.props["powered"] = False
                    it.props.pop("fired_once", None)
                    w.mark(it)
                continue
            if it.kind == "charger":
                g = _giant_beside(w, it)
                if g is None:
                    continue
                sinks.append((it, k["kw"], g))
            else:
                sinks.append((it, k["kw"], None))
        fixed = sum(kw for _it, kw, g in sinks if g is None)
        flexible = sum(kw for _it, kw, g in sinks if g is not None)     # chargers take what they can get
        demand = fixed + flexible
        supply = solar
        need = max(0.0, demand - supply)
        for gen in gens:                                   # generators follow the load
            if need <= 0:
                break
            kw = min(KINDS["generator"]["kw"], need)
            c = gen.props["contents"]
            litres = kw * hours * KINDS["generator"]["burns_l_per_kwh"]
            if litres > c["fuel"]:
                kw *= c["fuel"] / litres
                litres = c["fuel"]
            c["fuel"] -= litres
            if c["fuel"] <= 0.01:
                del c["fuel"]
                w.emit("power", "A generator ran out of fuel.", gen.pos, radius=30)
            supply += kw
            need -= kw
            w.mark(gen)
        for b in bats:                                     # then batteries discharge
            if need <= 0:
                break
            kw = min(100.0, need, b.props.get("charge", 0) / hours)
            if kw > 0:
                b.props["charge"] -= kw * hours
                supply += kw
                need -= kw
                w.mark(b)
        spare = supply - demand
        for b in bats:                                     # spare power charges them
            if spare <= 0:
                break
            cap = KINDS[b.kind]["cap_kwh"]
            kw = min(100.0, spare, (cap - b.props.get("charge", 0)) / hours)
            if kw > 0:
                b.props["charge"] = b.props.get("charge", 0) + kw * hours
                spare -= kw
                w.mark(b)
        frac = 1.0 if fixed <= 0 else min(1.0, supply / fixed)
        left = max(0.0, supply - fixed)
        share = 0.0 if flexible <= 0 else min(1.0, left / flexible)
        for it, kw, g in sinks:
            powered = (share > 0.0) if g is not None else frac >= 0.5
            if it.props.get("powered") != powered:
                it.props["powered"] = powered
                w.mark(it)
            if not powered:
                continue
            if it.kind == "charger" and g is not None:
                g.energy = min(g.max_energy, g.energy + kw * share * hours)
            elif it.kind == "heater":
                w.heaters[it.id] = 1600
            elif it.kind == "blower":
                x, k, z = it.pos
                for dx, dk, dz in P.N6 + ((0, 0, 0),):
                    w.blow[(x + dx, k + dk, z + dz)] = w.tick + POWER_DT + 2
            elif it.kind == "sensor":
                _sense(w, it)
            elif it.kind == "igniter" and not it.props.get("fired_once"):
                it.props["fired_once"] = True              # one spark each time it is switched on
                x, k, z = it.pos
                for q in ((x, k - 1, z), (x, k, z)):
                    if not P.ignite_voxel(w, q, force=True) and q in w.soaked:
                        w.burning[q] = 30
                for oid in list(w.items_at.get(it.pos, ())):
                    o = w.items.get(oid)
                    if o is not None and o is not it:
                        P.heat_item(w, o, 900, POWER_DT)
                w.emit("fire", "An igniter sparked.", it.pos, radius=40)
            elif it.kind == "siren" and w.tick - it.props.get("last_wail", -999) >= 30:
                it.props["last_wail"] = w.tick
                w.emit("siren", f"A siren is wailing at ({it.pos[0]}, {it.pos[1] - w.sea}, {it.pos[2]}).",
                       it.pos, radius=250)


def trigger_active(w, tid):
    """Is this trigger letting power through?"""
    t = w.items.get(tid)
    if t is None or t.pos is None:
        return False
    p = t.props
    if t.kind == "switch":
        return bool(p.get("on"))
    if t.kind == "timer":
        return bool(p.get("on")) and w.tick >= p.get("armed_at", 0) + p.get("seconds", 60)
    if t.kind == "radio_trigger":
        return bool(p.get("on")) and bool(p.get("fired"))
    x, k, z = t.pos
    if t.kind == "pressure_plate":
        return any(g.x == x and g.z == z and abs(g.k - k) <= 1 and g.status != "destroyed"
                   for g in w.giants.values())
    if t.kind == "sensor":
        return any(g.id != p.get("owner") and g.status != "destroyed"
                   and max(abs(g.x - x), abs(g.z - z)) <= 15 for g in w.giants.values())
    return False


def _giant_beside(w, it):
    x, k, z = it.pos
    for g in w.giants.values():
        if g.status != "destroyed" and max(abs(g.x - x), abs(g.z - z)) <= 2 and abs(g.k - k) <= 3 \
                and g.energy < g.max_energy - 0.5:
            return g
    return None


def _sense(w, it):
    owner = it.props.get("owner")
    if owner not in w.giants or w.tick - it.props.get("last_alert", -999) < 60:
        return
    x, k, z = it.pos
    for g in w.giants.values():
        if g.id != owner and g.status != "destroyed" and max(abs(g.x - x), abs(g.z - z)) <= 15:
            it.props["last_alert"] = w.tick
            w.emit("alarm", f"Your sensor #{it.id} at ({x}, {k - w.sea}, {z}) detected {g.name} nearby.",
                   to=[owner])
            return
