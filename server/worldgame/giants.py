"""Giants: 12 m machines that act in the world through general-purpose verbs.

A giant queues actions; each takes game time and energy. What an action
achieves is decided by the physics and by the properties of whatever the giant
is holding, never by a recipe. Failures explain what was missing, so an agent
can work out what to try next.
"""

import heapq
import secrets

from . import materials as M
from . import physics as P
from .items import BINDERS, FORMS, HANDLES, HEADS, KINDS, affordances, can_make, recognise_assembly

REACH = 2            # voxels sideways
REACH_UP, REACH_DOWN = 4, 2
HANDS_POWER = 4.0    # bare steel hands as a tool
CARRY_KG = 20000.0
HEAR = 100           # voxels a spoken voice carries
VERBS = ("move_to", "break", "pick_up", "drop", "place", "give", "make", "join", "ignite", "extinguish",
         "fill", "pour", "mix", "consume", "charge", "connect", "disconnect", "switch", "fan", "say",
         "whisper", "radio", "write", "hit", "push", "repair", "wait", "label", "throw")
FAST = {M.ID["asphalt"], M.ID["paving"]}
SLOW = {M.ID[n] for n in ("sand", "farm_soil", "rubble", "gravel", "ballast", "clay")}
WEAK = {v.id for v in M.VOXELS if "roof" in v.tags or "interior" in v.tags}
REACTIONS = [({"lime", "sand"}, True, "mortar")]     # (substances, needs water, product)


class Giant:
    def __init__(self, w, gid, name, x, z, colour="#c9a227"):
        self.w, self.id, self.name, self.colour = w, gid, name, colour
        self.token = secrets.token_hex(8)
        self.x, self.z = x, z
        self.k = stand_level(w, x, z, w.surface(x, z) + 1) or w.surface(x, z) + 1
        self.energy, self.max_energy = 600.0, 1000.0
        self.integrity = 100.0
        self.carrying = []
        self.queue = []
        self.cur = None
        self.inbox = []
        self.advice = []
        self.notes = []
        self.status = "active"
        self.said = None
        self.doing = "idle"
        self.stats = {"walked": 0, "broken": 0, "placed": 0, "made": 0, "said": 0}

    # --- basics ------------------------------------------------------------------
    @property
    def pos(self):
        return (self.x, self.k, self.z)

    def items(self):
        return [self.w.items[i] for i in self.carrying if i in self.w.items]

    def load(self):
        return sum(it.total_mass for it in self.items())

    def haul(self):
        return max([affordances(it).get("haul_kg", 0) for it in self.items()] or [0])

    def free_kg(self):
        return CARRY_KG + self.haul() - self.load()

    def best(self, key, exclude=None):
        """Best value of an affordance among carried items, and the item."""
        top, who = 0.0, None
        for it in self.items():
            if it is exclude:
                continue
            v = affordances(it).get(key, 0)
            if v is True:
                v = 1.0
            if v and v > top:
                top, who = v, it
        return top, who

    def report(self, text, ok=True):
        self.inbox.append({"t": self.w.tick, "type": "result" if ok else "failed", "text": text})

    def hurt(self, amount, cause):
        if self.status == "destroyed" or amount <= 0:
            return
        self.integrity -= amount
        if amount >= 3:
            self.inbox.append({"t": self.w.tick, "type": "damage",
                               "text": f"You were damaged by {cause} (-{amount:.0f}); integrity {max(0, self.integrity):.0f}%."})
        if self.integrity <= 0:
            self.integrity = 0
            self.status = "destroyed"
            self.queue, self.cur = [], None
            for it in self.items():
                self.w.put(it, self.pos)
            self.carrying = []
            wreck = self.w.new_item("bulk", "steel", 30000, self.pos, label=f"wreck of {self.name}")
            self.w.add_bulk("electronics", 1500, self.pos)
            self.w.add_bulk("copper", 2000, self.pos)
            self.w.emit("destroyed", f"{self.name} was destroyed by {cause}.", self.pos, radius=300)
            self.inbox.append({"t": self.w.tick, "type": "destroyed", "text": "You have been destroyed."})
            del wreck

    def reach(self, x, k, z):
        return max(abs(x - self.x), abs(z - self.z)) <= REACH and -REACH_DOWN <= k - self.k <= REACH_UP

    def reach_item(self, it):
        if it.holder == self.id:
            return True
        if it.inside is not None:                        # stored in a container we can reach
            c = self.w.items.get(it.inside)
            return c is not None and self.reach_item(c)
        return it.pos is not None and self.reach(*it.pos)

    def find(self, ref):
        """Resolve an item reference (id) that the giant carries or can reach."""
        try:
            it = self.w.items.get(int(ref))
        except (TypeError, ValueError):
            return None, f"'{ref}' is not an item id"
        if it is None:
            return None, f"item {ref} no longer exists"
        if not self.reach_item(it):
            where = f"at {fmt(self.w, it.pos)}" if it.pos else "held by someone else or stored"
            return None, f"item {ref} ({it.name}) is out of reach ({where}); you reach {REACH} voxels"
        return it, None

    def xyz(self, a):
        """Voxel coordinates from an action ({x, y, z} in agent coordinates)."""
        try:
            return int(a["x"]), int(a["y"]) + self.w.sea, int(a["z"])
        except (KeyError, TypeError, ValueError):
            return None

    # --- the clock ---------------------------------------------------------------
    def tick(self):
        w = self.w
        if self.status == "destroyed":
            return
        self.energy -= 0.002
        self._fall()
        if self.energy <= 0:
            self.energy = 0
            if self.status != "dormant":
                self.status = "dormant"
                self.queue = [a for a in self.queue if a.get("do") in ("say", "radio", "whisper")]
                self.cur = None
                self.doing = "dormant"
                self.inbox.append({"t": w.tick, "type": "dormant",
                                   "text": "Your energy is gone. You are dormant: you can only speak until someone recharges you."})
        elif self.status == "dormant":
            self.status = "active"
            self.report("Power restored. You are active again.")
        if self.cur is None and self.queue:
            a = self.queue.pop(0)
            verb = a.get("do")
            if self.status == "dormant" and verb not in ("say", "radio", "whisper"):
                return
            err = self._begin(a)
            if err:
                self._fail(a, err)
                return
            self.cur = a
            self.doing = verb
        if self.cur is not None:
            a = self.cur
            if a["do"] == "move_to":
                done = self._walk(a)
            else:
                a["_t"] -= 1
                self.energy -= a.get("_e", 0.0)
                if a["do"] == "fan":
                    w.blow[a["_pos"]] = w.tick + 3
                done = a["_t"] <= 0
                if done:
                    try:
                        msg = getattr(self, "end_" + a["do"])(a)
                    except Exception as e:           # a bug must never kill the world
                        msg = None
                        self._fail(a, f"internal error: {e!r}")
                    if msg:
                        self.report(msg)
            if done and self.cur is a:
                self.cur = None
                self.doing = "idle"

    def _fail(self, a, err):
        dropped = len(self.queue)
        self.queue = []
        self.cur = None
        self.doing = "idle"
        extra = f" {dropped} queued action{'s' if dropped != 1 else ''} cancelled." if dropped else ""
        self.report(f"{a.get('do')}: {err}.{extra}", ok=False)

    def _begin(self, a):
        verb = a.get("do")
        if verb not in VERBS:
            return f"unknown action '{verb}'. Actions: {', '.join(VERBS)}"
        a["_t"], a["_e"] = 1, 0.0
        try:
            return getattr(self, "begin_" + verb)(a)
        except Exception as e:
            return f"bad parameters ({e!r})"

    def _fall(self):
        w = self.w
        if w.t["solid"][w.get(self.x, self.k - 1, self.z)] and not w.t["solid"][w.get(self.x, self.k, self.z)]:
            return
        k = self.k
        while k < w.Y - 1 and w.t["solid"][w.get(self.x, k, self.z)]:
            k += 1                                   # buried: climb out
        while k > 1 and not w.t["solid"][w.get(self.x, k - 1, self.z)]:
            k -= 1
        drop = self.k - k
        self.k = k
        if drop > 3:
            self.hurt((drop - 3) * 8, f"a fall of {drop * w.cell:.0f} m")
            if self.cur and self.cur.get("do") == "move_to":
                self.cur["_path"] = None

    # --- movement ------------------------------------------------------------------
    def begin_move_to(self, a):
        w = self.w
        near = int(a.get("near", 0))
        if "target" in a:
            t = a["target"]
            g = next((g for g in w.giants.values() if g.name == t or str(g.id) == str(t)), None)
            if g is not None:
                gx, gz, a["_gk"] = g.x, g.z, g.k
            else:
                it = w.items.get(int(t)) if str(t).isdigit() else None
                if it is None or it.pos is None:
                    return f"can't find '{t}' to walk to"
                gx, gz, a["_gk"] = it.pos[0], it.pos[2], it.pos[1]
            near = max(near, 1)
        else:
            gx, gz = int(a["x"]), int(a["z"])
        if not (0 <= gx < w.X and 0 <= gz < w.Z):
            return f"({gx}, {gz}) is outside the region (0..{w.X - 1}, 0..{w.Z - 1})"
        a["_goal"], a["_near"], a["_path"], a["_budget"], a["_stuck"] = (gx, gz), near, None, 0.0, 0
        return None

    def _walk(self, a):
        w = self.w
        gx, gz = a["_goal"]
        gk = a.get("_gk")
        if max(abs(self.x - gx), abs(self.z - gz)) <= a["_near"] and (gk is None or abs(self.k - gk) <= 2):
            return True
        if a["_path"] is None:
            path, complete = find_path(w, self.pos, (gx, gz), a["_near"], self, goal_k=gk)
            if not path:
                self._fail(a, f"no walkable route towards ({gx}, {gz}) from here; something blocks the way "
                              f"(deep water, a sheer drop, or walls more than 3 voxels high)")
                return True
            a["_path"], a["_i"], a["_complete"] = path, 0, complete
        a["_budget"] += 1.0
        heavy = 1.0 + 0.5 * min(1.5, self.load() / CARRY_KG)
        while a["_i"] < len(a["_path"]):
            nx, nk, nz = a["_path"][a["_i"]]
            lv = stand_level(w, nx, nz, self.k)
            if lv is None or any(g is not self and g.x == nx and g.z == nz and g.status != "destroyed"
                                 for g in w.giants.values()):
                a["_path"] = None
                a["_stuck"] += 1
                if a["_stuck"] > 6:
                    self._fail(a, "the way is blocked")
                    return True
                return False
            cost = step_cost(w, self.x, self.k, self.z, nx, lv, nz) * heavy
            if a["_budget"] < cost:
                return False
            a["_budget"] -= cost
            self.x, self.k, self.z = nx, lv, nz
            a["_i"] += 1
            under = w.mat(nx, lv - 1, nz)
            if "roof" in under.tags or "interior" in under.tags:      # too light to carry a giant
                w.set(nx, lv - 1, nz, M.AIR)
                w.add_bulk("rubble", under.mass(w.voxel_m3) * 0.6, (nx, lv - 1, nz))
                self._fall()
                self.report(f"The {under.name} gave way under your weight at {fmt(w, self.pos)}.", ok=False)
                a["_path"] = None
                return False
            self.energy -= 0.15 * heavy
            self.stats["walked"] += 1
            if self.energy <= 0:
                return True
        if not a.get("_complete", True) and max(abs(self.x - gx), abs(self.z - gz)) > a["_near"]:
            self.report(f"move_to: could not get closer to ({gx}, {gz}) than {fmt(w, self.pos)}; "
                        f"the way on is blocked.", ok=False)
            self.queue = []
        return True

    # --- break ----------------------------------------------------------------------
    def tool_power(self):
        cut, tool = self.best("cut")
        return (cut, tool.name) if cut > HANDS_POWER else (HANDS_POWER, "bare hands")

    def begin_break(self, a):
        w = self.w
        if "item" in a:
            it, err = self.find(a["item"])
            if err:
                return err
            if it.bulk:
                return f"{it.name} is already loose material"
            a["_t"], a["_e"] = 20, 0.05
            return None
        p = self.xyz(a)
        if p is None:
            return "give x, y, z of a voxel, or an item id"
        if not self.reach(*p):
            return f"{fmt(w, p)} is out of reach from {fmt(w, self.pos)} (reach: {REACH} sideways, {REACH_UP} up, {REACH_DOWN} down)"
        v = w.mat(*p)
        if v.id == M.AIR or v.kind == "liquid":
            return f"there is nothing solid at {fmt(w, p)} ({v.name})"
        power, tool = self.tool_power()
        sub = M.SUBSTANCES[v.substance]
        need = v.hardness * (0.6 if sub.has("b") else 0.8)
        if power < need:
            return (f"{v.name} (hardness {v.hardness}) needs a tool with cutting power of at least {need:.1f}; "
                    f"your best is {power:.1f} ({tool}). A harder blade or pick would do it")
        t = v.work * (v.hardness / power) ** 1.5 if v.hardness > 0 else v.work
        if v.kind == "granular":
            t /= max(1.0, self.best("dig")[0])
        a["_t"], a["_e"], a["_vid"], a["_p"] = max(2, int(t)), 0.05, v.id, p
        return None

    def end_break(self, a):
        w = self.w
        if "item" in a:
            it, err = self.find(a["item"])
            if err:
                return self._fail(a, err)
            return "Dismantled " + it.name + ": " + self._dismantle(it)
        p = a["_p"]
        v = w.mat(*p)
        if v.id != a["_vid"]:
            return self._fail(a, f"the voxel at {fmt(w, p)} changed before you finished")
        mass = v.mass(w.voxel_m3)
        w.set(p[0], p[1], p[2], M.AIR)
        got = []
        for sub, frac in v.yields:
            it = w.add_bulk(sub, mass * frac, p)
            if it:
                got.append(it)
        if v.loot:
            got += P.roll_loot(w, v.loot, p, p)
        if p in w.signs:
            del w.signs[p]
        self.stats["broken"] += 1
        w.stats["broken"] += 1
        seen = {}
        for it in got:
            if it.id in w.items:
                seen[it.id] = it
        parts = ", ".join(f"{it.name} {kg(it.total_mass)} (#{it.id})" for it in seen.values()) or "nothing useful"
        return f"Broke {v.name} at {fmt(w, p)}: {parts}."

    def _dismantle(self, it):
        w = self.w
        pos = it.pos or self.pos
        out = []
        k = KINDS.get(it.kind, {})
        if it.kind == "assembly" or it.kind in FORMS:
            for form, mat, m in it.props.get("parts", [(it.kind, it.mat, it.mass)]):
                out.append(w.add_bulk(mat, m, pos))
        else:
            for what, n in k.get("parts", [(it.mat, it.mass)]):
                if what in M.SUBSTANCES:
                    out.append(w.add_bulk(what, n, pos))
                else:
                    for _ in range(int(n)):
                        out.append(P.spawn(w, what, pos))
            if it.kind == "car":
                out.append(P.spawn(w, "ev_pack" if it.props.get("ev") else "battery_12v", pos))
        fuel = it.props.get("contents", {}).get("fuel", 0)
        if fuel > 0:
            w.soaked.add((pos[0], pos[1] - 1, pos[2]))
            w.soaked.add(pos)
        w.remove(it)
        names = {}
        for o in out:
            if o and o.id in w.items:
                names[o.id] = f"{o.name} {kg(o.total_mass)} (#{o.id})"
        return ", ".join(names.values()) + (f". {fuel:.0f} L of fuel spilled on the ground" if fuel > 0 else "")

    # --- carry ------------------------------------------------------------------------
    def begin_pick_up(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return err
        if it.holder == self.id:
            return f"you are already carrying {it.name}"
        free = self.free_kg()
        if it.bulk:
            if free < 1:
                return f"you are fully loaded ({kg(self.load())}); drop something first"
        elif it.total_mass > free:
            return f"{it.name} weighs {kg(it.total_mass)} but you can only take {kg(free)} more"
        a["_t"] = 3
        return None

    def end_pick_up(self, a):
        w = self.w
        it, err = self.find(a.get("item"))
        if err:
            return self._fail(a, err)
        free = self.free_kg()
        want = min(float(a.get("kg", it.mass)), it.mass)
        if it.bulk and want > free:
            want = free
        if it.bulk and want < it.mass - 0.5:
            part = w.new_item("bulk", it.mat, want, **{k: v for k, v in it.props.items() if k in ("temp", "burning")})
            it.mass -= want
            box = w.items.get(it.inside) if it.inside is not None else None
            if box is not None:
                box.props["stored_kg"] = max(0.0, box.props.get("stored_kg", 0.0) - want)
            w.mark(it)
            it = part
            if it.props.get("burning"):
                w.burning_items.add(it.id)
        elif not it.bulk and it.total_mass > free:
            return self._fail(a, f"{it.name} is too heavy")
        else:
            w.lift(it)
        if it.inside is not None:
            w.unstore(it)
        it.holder = self.id
        w.links = [l for l in w.links if l[0] != it.id and l[1] != it.id]
        for o in self.items():                       # carried piles of one substance merge
            if o.bulk and it.bulk and o.mat == it.mat and o is not it and not o.props.get("burning") \
                    and not it.props.get("burning"):
                o.mass += it.mass
                w.remove(it)
                w.mark(o)
                return f"Picked up {kg(want)} of {o.mat}; now carrying {kg(o.mass)} of it (#{o.id})."
        self.carrying.append(it.id)
        w.mark(it)
        return f"Picked up {it.name} {kg(it.total_mass)} (#{it.id}). Load {kg(self.load())} of {kg(CARRY_KG + self.haul())}."

    def begin_drop(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return err
        if it.holder != self.id:
            return f"you are not carrying {it.name}"
        if "into" in a:
            c, err = self.find(a["into"])
            if err:
                return err
            cap = c.props.get("cap_l", 0)
            if c is it or cap <= 0 or c.inside is not None:
                return f"{c.name} can't have things stored in it"
            used = sum(c.props.get("contents", {}).values())
            for sid in c.props.get("stored", ()):
                s = self.w.items.get(sid)
                if s:
                    used += s.total_mass / max(0.2, s.sub.density)
            want = min(float(a.get("kg", it.mass)), it.mass) if it.bulk else it.total_mass
            if used + want / max(0.2, it.sub.density) > cap:
                return (f"{c.name} holds {cap:.0f} litres and has {max(0, cap - used):.0f} free; "
                        f"that load needs {want / max(0.2, it.sub.density):.0f}")
            if c.holder == self.id:
                pass                                      # moving it between our own hands and our container
            a["_into"] = c.id
            return None
        p = self.xyz(a) if "x" in a else self.pos
        if p is None or not self.reach(*p):
            return "the drop point is out of reach"
        if self.w.t["solid"][self.w.get(*p)]:
            return f"{fmt(self.w, p)} is solid; drop into an open space"
        a["_p"] = p
        return None

    def end_drop(self, a):
        w = self.w
        it, err = self.find(a.get("item"))
        if err:
            return self._fail(a, err)
        want = min(float(a.get("kg", it.mass)), it.mass)
        if it.bulk and want < it.mass - 0.5:
            it.mass -= want
            w.mark(it)
            it = w.new_item("bulk", it.mat, want)
        else:
            self.carrying.remove(it.id)
        if "_into" in a:
            c = w.items.get(a["_into"])
            if c is None or not self.reach_item(c):
                self.carrying.append(it.id) if it.id not in self.carrying else None
                it.holder = self.id
                return self._fail(a, "the container is gone")
            it.holder, it.inside = None, c.id
            c.props.setdefault("stored", []).append(it.id)
            c.props["stored_kg"] = c.props.get("stored_kg", 0.0) + it.total_mass
            w.mark(it)
            w.mark(c)
            return f"Stored {it.name} {kg(it.total_mass)} in {c.name} (#{c.id})."
        if KINDS.get(it.kind, {}).get("comp"):
            it.props["owner"] = self.id          # whoever sets a device down is told what it senses
        w.put(it, a["_p"])
        P.compact_pile(w, it.pos) if it.id in w.items else None
        return f"Dropped {it.name if it.id in w.items else 'the load'} at {fmt(w, a['_p'])}."

    def begin_give(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return err
        g = self._other(a.get("to"))
        if g is None:
            return f"no giant called '{a.get('to')}' within reach"
        if it.total_mass > g.free_kg():
            return f"{g.name} can't carry another {kg(it.total_mass)}"
        a["_t"] = 3
        return None

    def end_give(self, a):
        it, err = self.find(a.get("item"))
        g = self._other(a.get("to"))
        if err or g is None:
            return self._fail(a, err or "they moved away")
        if it.holder == self.id:
            self.carrying.remove(it.id)
        else:
            self.w.lift(it)
        it.holder = g.id
        g.carrying.append(it.id)
        self.w.mark(it)
        g.inbox.append({"t": self.w.tick, "type": "given",
                        "text": f"{self.name} gave you {it.name} {kg(it.total_mass)} (#{it.id})."})
        return f"Gave {it.name} to {g.name}."

    def _other(self, ref, dist=REACH):
        for g in self.w.giants.values():
            if g is not self and (g.name == ref or str(g.id) == str(ref)) and g.status != "destroyed" \
                    and max(abs(g.x - self.x), abs(g.z - self.z)) <= dist and abs(g.k - self.k) <= 4:
                return g
        return None

    # --- build -------------------------------------------------------------------------
    def _stock(self, mat):
        """Loose material of one substance within reach or carried."""
        out = [it for it in self.items() if it.bulk and it.mat == mat]
        for it in self.w.items_near(self.x, self.k, self.z, REACH, REACH_UP):
            if it.bulk and it.mat == mat and self.reach_item(it):
                out.append(it)
        return out

    def begin_place(self, a):
        w = self.w
        p = self.xyz(a)
        if p is None:
            return "give x, y, z of the empty voxel to fill"
        if not self.reach(*p):
            return (f"{fmt(w, p)} is out of reach from {fmt(w, self.pos)} "
                    f"(reach: {REACH} sideways, {REACH_UP} up, {REACH_DOWN} down)")
        if w.t["solid"][w.get(*p)]:
            return f"{fmt(w, p)} is already solid ({w.mat(*p).name})"
        if any(g.x == p[0] and g.z == p[2] and 0 <= p[1] - g.k < 4 for g in w.giants.values()
               if g.status != "destroyed"):
            return "a giant is standing there"
        mat = a.get("material")
        if mat is None and "item" in a:
            it, err = self.find(a["item"])
            if err:
                return err
            mat = it.mat
        if mat not in M.PLACE_AS:
            return (f"'{mat}' can't be stacked into a voxel. Stackable: {', '.join(sorted(M.PLACE_AS))}"
                    if mat else "say which material to place")
        vox = M.V[M.PLACE_AS[mat]]
        if mat in ("brick", "tile", "chalk", "sandstone", "mudstone", "basalt", "slate", "rock", "flint") \
                and sum(i.mass for i in self._stock("mortar")) >= vox.mass(w.voxel_m3) * 0.08:
            vox = M.V["mortared_wall"]
            a["_mortar"] = True
        need = vox.mass(w.voxel_m3)
        have = sum(i.mass for i in self._stock(mat))
        if have < need:
            return (f"one voxel of {vox.name} takes {kg(need)} of {mat}; you have {kg(have)} within reach. "
                    f"Bring more and pile it here")
        a["_t"], a["_e"], a["_p"], a["_mat"], a["_vox"], a["_need"] = 10, 0.03, p, mat, vox.id, need
        return None

    def end_place(self, a):
        w = self.w
        p, mat, need = a["_p"], a["_mat"], a["_need"]
        if w.t["solid"][w.get(*p)]:
            return self._fail(a, "the space was filled before you finished")
        if sum(i.mass for i in self._stock(mat)) < need:
            return self._fail(a, "the material was taken before you finished")
        self._use(mat, need)
        if a.get("_mortar"):
            self._use("mortar", need * 0.08)
        for iid in list(w.items_at.get(p, ())):
            if iid in w.items:
                w.put(w.items[iid], (p[0], p[1] + 1, p[2]))
        w.set(p[0], p[1], p[2], a["_vox"])
        self.stats["placed"] += 1
        w.stats["placed"] += 1
        return f"Placed {M.VOXELS[a['_vox']].name} at {fmt(w, p)}."

    def _use(self, mat, amount):
        for it in self._stock(mat):
            take = min(it.mass, amount)
            it.mass -= take
            amount -= take
            if it.mass < 0.5:
                self.w.remove(it)
            else:
                self.w.mark(it)
            if amount <= 0:
                break

    # --- make and join ------------------------------------------------------------------
    def _wet(self):
        for it in self.items():
            if it.props.get("contents", {}).get("water", 0) >= 50:
                return True
        w = self.w
        for dx in range(-REACH, REACH + 1):
            for dz in range(-REACH, REACH + 1):
                for dk in (-2, -1, 0, 1):
                    if w.t["liquid"][w.get(self.x + dx, self.k + dk, self.z + dz)]:
                        return True
        return False

    def begin_make(self, a):
        it, err = self.find(a.get("from"))
        if err:
            return err
        form = a.get("form")
        if it.kind in KINDS and "form" not in KINDS[it.kind] and not it.bulk:
            return f"{it.name} is an object, not raw material; break it down first"
        need = float(a.get("kg", FORMS.get(form, 0)))
        if form in FORMS and need < FORMS[form]:
            return f"a giant-sized {form} takes at least {kg(FORMS[form])}"
        if it.mass < need:
            return f"a {form} takes {kg(need)} of {it.mat}; that item has {kg(it.mass)}"
        ctx = {"temp": it.props.get("temp", 15), "cut": self.best("cut", exclude=it)[0], "wet": self._wet()}
        method, why = can_make(form, it.sub, ctx)
        if method is None:
            return why
        a["_t"] = {"knap": 15, "carve": 30, "forge": 40, "cast": 20, "mould": 20, "twist": 20, "snap": 5,
                   "cut": 15}[method]
        a["_e"], a["_method"], a["_kg"] = 0.03, method, need
        return None

    def end_make(self, a):
        w = self.w
        it, err = self.find(a.get("from"))
        if err or it.mass < a["_kg"]:
            return self._fail(a, err or "the material was used up")
        form, need = a["form"], a["_kg"]
        props = {}
        if it.props.get("temp", 15) > 80:
            props["temp"] = it.props["temp"]
        if form == "wire":
            props["wire_m"] = need
        pos = it.pos
        held = it.holder == self.id
        it.mass -= need
        if it.mass < 0.5:
            w.remove(it)
        else:
            w.mark(it)
        new = w.new_item(form, it.mat, need, **props)
        if held and new.mass <= self.free_kg() + need:
            new.holder = self.id
            self.carrying.append(new.id)
        else:
            w.put(new, pos or self.pos)
        self.stats["made"] += 1
        can = affordances(new)
        how = {"knap": "knapping", "snap": "snapping", "cut": "cutting", "carve": "carving", "forge": "forging",
               "cast": "casting", "mould": "moulding", "twist": "twisting"}[a["_method"]]
        where = "in your hands" if new.holder == self.id else f"on the ground at {fmt(w, new.pos)}"
        return (f"Made a {new.name} ({kg(need)}, #{new.id}) by {how}; it is {where}." +
                (f" It can: {can}." if can else ""))

    def begin_join(self, a):
        ids = a.get("items") or []
        if len(ids) < 2:
            return "give at least two item ids to join"
        parts = []
        for ref in ids:
            it, err = self.find(ref)
            if err:
                return err
            if it.bulk:
                return f"{it.name} is loose material; shape it into a part first (make)"
            parts.append(it)
        binder = None
        if "with" in a:
            binder, err = self.find(a["with"])
            if err:
                return err
            if not affordances(binder).get("bind") and not affordances(binder).get("ignite"):
                return f"{binder.name} can't hold things together; use rope, wire, or a torch to weld metal"
        else:
            binder = next((it for it in self.items() if it not in parts and affordances(it).get("bind")), None)
            if binder is None:
                return ("joining needs something to hold the parts together: rope or wire to lash them "
                        "(carry it or name it with 'with'), or a welding flame for metal")
        a["_t"], a["_e"] = 30, 0.03
        return None

    def end_join(self, a):
        w = self.w
        parts = []
        for ref in a["items"]:
            it, err = self.find(ref)
            if err:
                return self._fail(a, err)
            parts.append(it)
        binder = None
        if "with" in a:
            binder, _ = self.find(a["with"])
        if binder is None:
            binder = next((it for it in self.items() if it not in parts and affordances(it).get("bind")), None)
        if binder is None:
            return self._fail(a, "the binding was lost")
        spec = [(KINDS.get(it.kind, {}).get("form", it.kind), it.mat, it.total_mass) for it in parts]
        role, props = recognise_assembly(spec, binder)
        main = max(parts, key=lambda it: (it.kind in HEADS, it.mass))
        mass = sum(it.total_mass for it in parts)
        if "wire_m" in binder.props:
            binder.props["wire_m"] -= 5
            binder.mass = max(1.0, binder.mass - 5)
        elif affordances(binder).get("bind"):
            binder.mass -= 5
            if binder.mass < 1:
                w.remove(binder)
        for it in parts:
            w.remove(it)
        new = w.new_item("assembly", main.mat, mass, role=role, parts=spec, **props)
        if mass <= self.free_kg():
            new.holder = self.id
            self.carrying.append(new.id)
        else:
            w.put(new, self.pos)
        self.stats["made"] += 1
        can = affordances(new)
        return f"Joined them into a {new.name} (#{new.id})." + (f" It can: {can}." if can else
                                                                  " It has no special function yet.")

    def begin_mix(self, a):
        mats = set()
        for ref in a.get("items") or []:
            it, err = self.find(ref)
            if err:
                return err
            mats.add(it.mat)
        for need, water, product in REACTIONS:
            if need <= mats:
                if water and not self._wet():
                    return "this mixture needs water to hand"
                a["_t"], a["_product"], a["_need"] = 15, product, need
                return None
        return f"mixing {', '.join(sorted(mats)) or 'nothing'} does nothing useful"

    def end_mix(self, a):
        w = self.w
        used = [w.items[int(r)] for r in a["items"] if int(r) in w.items and w.items[int(r)].mat in a["_need"]]
        if not used:
            return self._fail(a, "the ingredients are gone")
        part = min(it.mass for it in used)
        for it in used:
            it.mass -= part
            w.remove(it) if it.mass < 0.5 else w.mark(it)
        new = w.new_item("bulk", a["_product"], part * len(used), self.pos)
        return f"Mixed {kg(new.mass)} of {new.name} (#{new.id})."

    # --- fire, liquids, energy ------------------------------------------------------------
    def ignition(self):
        w = self.w
        items = self.items()
        for it in items:
            if affordances(it).get("ignite"):
                return it.name
        if any(it.mat == "flint" for it in items) and any(it.mat == "steel" for it in items):
            return "flint struck on steel"
        if any(affordances(it).get("focus_sunlight") for it in items) and w.daylight() > 0.3 and not w.raining:
            return "sunlight through a lens"
        if any(it.props.get("charge", 0) >= 0.5 for it in items) and \
                any(affordances(it).get("wire_m") or affordances(it).get("conducts") for it in items):
            return "a spark from a shorted battery"
        return None

    def begin_ignite(self, a):
        w = self.w
        src = self.ignition()
        if src is None:
            return ("you have nothing to start a fire with. Fire needs a flame, a spark or focused sunlight: "
                    "think about what could give one")
        if "item" in a:
            it, err = self.find(a["item"])
            if err:
                return err
            if it.sub.flammability <= 0 and it.pos not in w.soaked:
                return f"{it.name} does not burn"
        else:
            p = self.xyz(a)
            if p is None or not self.reach(*p):
                return "give an item id, or x, y, z within reach"
            if w.mat(*p).flammability <= 0 and p not in w.soaked:
                return f"{w.mat(*p).name} does not burn"
            a["_p"] = p
        a["_t"], a["_src"] = 4, src
        return None

    def end_ignite(self, a):
        w = self.w
        if "item" in a:
            it, err = self.find(a["item"])
            if err:
                return self._fail(a, err)
            P.ignite_item(w, it)
            w.emit("fire", f"{self.name} lit a fire.", it.pos or self.pos, radius=120)
            return f"Lit {it.name} with {a['_src']}."
        p = a["_p"]
        if not P.ignite_voxel(w, p, force=True):
            if p in w.soaked:
                w.burning[p] = 30
            else:
                return self._fail(a, "it would not catch (no air, or too wet)")
        w.emit("fire", f"{self.name} lit a fire.", p, radius=120)
        return f"Lit the {w.mat(*p).name} at {fmt(w, p)} with {a['_src']}."

    def begin_extinguish(self, a):
        p = self.xyz(a)
        if p is None or not self.reach(*p):
            return "give x, y, z within reach"
        water = next((it for it in self.items() if it.props.get("contents", {}).get("water", 0) >= 200), None)
        dirt = next((it for it in self.items() if it.bulk and it.mat in ("soil", "sand", "gravel")
                     and it.mass >= 1000), None)
        if not water and not dirt:
            return "putting out a fire takes 200 kg of water in a container, or a tonne of soil or sand"
        a["_t"], a["_p"], a["_with"] = 4, p, (water or dirt).id
        return None

    def end_extinguish(self, a):
        w = self.w
        it = w.items.get(a["_with"])
        if it is None:
            return self._fail(a, "what you were using is gone")
        if it.bulk:
            it.mass -= 1000
            w.remove(it) if it.mass < 0.5 else w.mark(it)
        else:
            it.props["contents"]["water"] -= 200
        x, k, z = a["_p"]
        n = 0
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    q = (x + dx, k + dk, z + dz)
                    if w.burning.pop(q, None) is not None:
                        n += 1
                    for iid in w.items_at.get(q, ()):
                        o = w.items.get(iid)
                        if o and o.props.pop("burning", None):
                            w.burning_items.discard(o.id)
                            w.mark(o)
                            n += 1
        w.rev += 1
        return f"Put out {n} burning thing{'s' if n != 1 else ''} around {fmt(w, a['_p'])}."

    def begin_fill(self, a):
        w = self.w
        it, err = self.find(a.get("container"))
        if err:
            return err
        cap = affordances(it).get("contain_l")
        if not cap:
            return f"{it.name} can't hold liquid"
        if "from" in a:
            src, err = self.find(a["from"])
            if err:
                return err
            if not src.props.get("contents"):
                return f"{src.name} is empty"
        else:
            p = self.xyz(a)
            if p is None or not self.reach(*p) or not w.t["liquid"][w.get(*p)]:
                return "give x, y, z of water within reach, or 'from': an item holding liquid"
            a["_p"] = p
        a["_t"] = 5
        return None

    def end_fill(self, a):
        w = self.w
        it, err = self.find(a.get("container"))
        if err:
            return self._fail(a, err)
        cap = affordances(it)["contain_l"]
        c = it.props.setdefault("contents", {})
        room = cap - sum(c.values())
        if "from" in a:
            src, err = self.find(a["from"])
            if err:
                return self._fail(a, err)
            sc = src.props.get("contents", {})
            moved = {}
            for liquid, amt in list(sc.items()):
                take = min(amt, room)
                if take <= 0:
                    continue
                sc[liquid] -= take
                if sc[liquid] <= 0.01:
                    del sc[liquid]
                c[liquid] = c.get(liquid, 0) + take
                room -= take
                moved[liquid] = round(take)
            w.mark(src)
            w.mark(it)
            return f"Moved {moved} (litres) from {src.name} into {it.name}."
        take = min(room, float(a.get("litres", room)))
        take = min(take, max(0.0, self.free_kg()))
        c["water"] = c.get("water", 0) + take
        w.mark(it)
        return f"Filled {it.name} with {take:.0f} L of water."

    def begin_pour(self, a):
        it, err = self.find(a.get("container"))
        if err:
            return err
        if not it.props.get("contents"):
            return f"{it.name} is empty"
        if "into" in a:
            dst, err = self.find(a["into"])
            if err:
                return err
            if not affordances(dst).get("contain_l"):
                return f"{dst.name} can't hold liquid"
        else:
            p = self.xyz(a) if "x" in a else self.pos
            if p is None or not self.reach(*p):
                return "the place to pour is out of reach"
            a["_p"] = p
        a["_t"] = 4
        return None

    def end_pour(self, a):
        w = self.w
        it, err = self.find(a.get("container"))
        if err:
            return self._fail(a, err)
        c = it.props.get("contents", {})
        if "into" in a:
            return self.end_fill({"container": a["into"], "from": it.id})
        p = a["_p"]
        out = []
        for liquid, amt in list(c.items()):
            take = min(amt, float(a.get("litres", amt)))
            c[liquid] -= take
            if c[liquid] <= 0.01:
                del c[liquid]
            out.append(f"{take:.0f} L of {liquid}")
            x, k, z = p
            if liquid == "fuel":
                r = 0 if take < 40 else 1
                for dx in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        for dk in (-1, 0):
                            w.soaked.add((x + dx, k + dk, z + dz))
            elif liquid == "water" and take >= 100:
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for dk in (-1, 0, 1):
                            q = (x + dx, k + dk, z + dz)
                            w.burning.pop(q, None)
                            w.soaked.discard(q)
                            for iid in w.items_at.get(q, ()):
                                o = w.items.get(iid)
                                if o and o.props.pop("burning", None):
                                    w.burning_items.discard(o.id)
        w.mark(it)
        w.rev += 1
        return f"Poured {', '.join(out)} at {fmt(w, p)}."

    def begin_consume(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return err
        fuel = it.props.get("contents", {}).get("fuel", 0)
        if fuel <= 0 and (it.sub.flammability <= 0 or it.sub.energy <= 0 or not it.bulk):
            return (f"{it.name} is not fuel your reactor can burn. It takes loose combustible material "
                    f"(wood, charcoal, plants...) or liquid fuel from a container")
        if self.energy >= self.max_energy - 1:
            return "your energy is already full"
        a["_t"] = 6
        return None

    def end_consume(self, a):
        w = self.w
        it, err = self.find(a.get("item"))
        if err:
            return self._fail(a, err)
        room = self.max_energy - self.energy
        c = it.props.get("contents", {})
        if c.get("fuel", 0) > 0:
            per_l = M.SUBSTANCES["fuel"].energy * 0.75 / 1000.0
            litres = min(c["fuel"], room / per_l)
            c["fuel"] -= litres
            if c["fuel"] <= 0.01:
                del c["fuel"]
            self.energy += litres * per_l
            w.mark(it)
            return f"Burned {litres:.0f} L of fuel: +{litres * per_l:.0f} kWh. Energy {self.energy:.0f}/{self.max_energy:.0f}."
        per_kg = it.sub.energy / 1000.0
        mass = min(it.mass, room / per_kg, float(a.get("kg", it.mass)))
        it.mass -= mass
        self.energy += mass * per_kg
        w.remove(it) if it.mass < 0.5 else w.mark(it)
        return f"Burned {kg(mass)} of {it.mat}: +{mass * per_kg:.0f} kWh. Energy {self.energy:.0f}/{self.max_energy:.0f}."

    def begin_charge(self, a):
        if "to" in a:
            g = self._other(a["to"])
            if g is None:
                return f"no giant called '{a['to']}' within reach"
            amt = min(float(a.get("kwh", 100)), self.energy - 20, g.max_energy - g.energy)
            if amt <= 0:
                return "you have no energy to spare, or they are full"
            a["_amt"] = amt
        else:
            it, err = self.find(a.get("from"))
            if err:
                return err
            if it.props.get("charge", 0) <= 0:
                return f"{it.name} holds no charge"
            a["_amt"] = min(it.props["charge"], self.max_energy - self.energy)
            if a["_amt"] <= 0:
                return "your energy is already full"
        a["_t"] = max(2, int(a["_amt"] / 5))
        return None

    def end_charge(self, a):
        if "to" in a:
            g = self._other(a["to"], dist=REACH + 1)
            if g is None:
                return self._fail(a, "they moved away")
            amt = min(a["_amt"], self.energy - 1)
            self.energy -= amt
            g.energy += amt
            g.inbox.append({"t": self.w.tick, "type": "charged",
                            "text": f"{self.name} gave you {amt:.0f} kWh of energy."})
            return f"Gave {amt:.0f} kWh to {g.name}. Energy {self.energy:.0f}."
        it, err = self.find(a.get("from"))
        if err:
            return self._fail(a, err)
        amt = min(a["_amt"], it.props.get("charge", 0), self.max_energy - self.energy)
        it.props["charge"] -= amt
        self.energy += amt
        self.w.mark(it)
        return f"Drew {amt:.0f} kWh from {it.name}. Energy {self.energy:.0f}/{self.max_energy:.0f}."

    # --- electricity -----------------------------------------------------------------------
    def begin_connect(self, a):
        w = self.w
        ends = []
        for key in ("a", "b"):
            it = w.items.get(int(a.get(key, -1)))
            if it is None or it.pos is None:
                return f"item '{a.get(key)}' must be standing in the world (not carried) to be wired"
            if max(abs(it.pos[0] - self.x), abs(it.pos[2] - self.z)) > 40:
                return f"{it.name} is too far away to run a cable to from here (40 voxels at most)"
            ends.append(it)
        metres = (abs(ends[0].pos[0] - ends[1].pos[0]) + abs(ends[0].pos[2] - ends[1].pos[2])
                  + abs(ends[0].pos[1] - ends[1].pos[1]) + 1) * w.cell
        wire = next((it for it in self.items() if affordances(it).get("wire_m", 0) >= metres), None)
        if wire is None:
            return f"that link needs {metres:.0f} m of wire in one piece; carry a long enough cable"
        a["_t"], a["_m"], a["_wire"] = max(5, int(metres / w.cell)), metres, wire.id
        return None

    def end_connect(self, a):
        w = self.w
        wire = w.items.get(a["_wire"])
        ia, ib = int(a["a"]), int(a["b"])
        if wire is None or ia not in w.items or ib not in w.items:
            return self._fail(a, "something was moved before the cable was laid")
        m = a["_m"]
        if "wire_m" in wire.props:
            wire.props["wire_m"] -= m
        wire.mass = max(1.0, wire.mass - m)
        w.mark(wire)
        w.links.append((ia, ib, m))
        w.rev += 1
        note = ""
        for t, d in ((w.items[ia], w.items[ib]), (w.items[ib], w.items[ia])):
            tk, dk = KINDS.get(t.kind, {}), KINDS.get(d.kind, {})
            if (tk.get("comp") == "trigger" or tk.get("trigger")) and dk.get("comp") == "sink" \
                    and not dk.get("trigger"):
                d.props["trigger"] = t.id
                d.props["on"] = True
                w.mark(d)
                note = f" The {d.name} will now run only while the {t.name} is active."
                break
        return (f"Wired {w.items[ia].name} (#{ia}) to {w.items[ib].name} (#{ib}) with {m:.0f} m of cable." + note)

    def begin_disconnect(self, a):
        w = self.w
        ia, ib = int(a.get("a", -1)), int(a.get("b", -1))
        for it_id in (ia, ib):
            it = w.items.get(it_id)
            if it and it.pos and self.reach(*it.pos):
                a["_t"] = 4
                return None
        return "stand within reach of one end of the cable"

    def end_disconnect(self, a):
        w = self.w
        ia, ib = int(a["a"]), int(a["b"])
        before = len(w.links)
        cut = [l for l in w.links if {l[0], l[1]} == {ia, ib}]
        w.links = [l for l in w.links if {l[0], l[1]} != {ia, ib}]
        for x, y in ((ia, ib), (ib, ia)):
            d = w.items.get(x)
            if d is not None and d.props.get("trigger") == y:
                d.props.pop("trigger", None)
        if len(w.links) == before:
            return self._fail(a, "there is no cable between those")
        w.new_item("wire", "copper", max(1.0, cut[0][2]), self.pos, wire_m=cut[0][2])
        w.rev += 1
        return f"Cut the cable between #{ia} and #{ib}; the wire is at your feet."

    def begin_switch(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return err
        if "on" not in it.props and KINDS.get(it.kind, {}).get("comp") not in ("trigger", "sink"):
            return f"{it.name} has no switch"
        it.props.setdefault("on", False)
        return None

    def end_switch(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return self._fail(a, err)
        it.props["on"] = bool(a.get("on", not it.props["on"]))
        if it.kind == "timer":
            it.props["seconds"] = max(5, min(3600, int(a.get("seconds", it.props.get("seconds", 60)))))
            it.props["armed_at"] = self.w.tick
        if it.kind == "radio_trigger":
            it.props.pop("fired", None)
        it.props.pop("fired_once", None)
        self.w.mark(it)
        extra = f" It will activate in {it.props['seconds']} s." if it.kind == "timer" and it.props["on"] else ""
        return f"Switched {it.name} {'on' if it.props['on'] else 'off'}.{extra}"

    def begin_fan(self, a):
        p = self.xyz(a)
        if p is None or not self.reach(*p):
            return "give x, y, z of the fire, within reach"
        if not self.best("blow")[0]:
            return "forcing air into a fire needs bellows: something flexible between two boards"
        a["_t"], a["_e"], a["_pos"] = min(120, max(5, int(a.get("seconds", 30)))), 0.02, p
        return None

    def end_fan(self, a):
        return f"Worked the bellows at {fmt(self.w, a['_pos'])}."

    # --- social --------------------------------------------------------------------------------
    def begin_say(self, a):
        if not str(a.get("text", "")).strip():
            return "say what?"
        return None

    def end_say(self, a):
        text = str(a["text"])[:400]
        self.said = (text, self.w.tick)
        self.stats["said"] += 1
        self.w.emit("heard", f'{self.name} says: "{text}"', self.pos, radius=HEAR,
                    data={"from": self.name, "say": text})
        return None

    def begin_whisper(self, a):
        if self._other(a.get("to"), dist=4) is None:
            return f"'{a.get('to')}' is not close enough to whisper to (4 voxels)"
        return None

    def end_whisper(self, a):
        g = self._other(a.get("to"), dist=5)
        if g is None:
            return self._fail(a, "they moved away")
        text = str(a.get("text", ""))[:400]
        g.inbox.append({"t": self.w.tick, "type": "heard", "from": self.name, "private": True,
                        "text": f'{self.name} whispers to you: "{text}"'})
        self.w.log.append({"t": self.w.tick, "type": "whisper", "text": f"{self.name} -> {g.name}: {text}"})
        return None

    def begin_radio(self, a):
        if not any(it.kind == "radio_set" for it in self.items()):
            return "you are not carrying a radio"
        return None

    def end_radio(self, a):
        text = str(a.get("text", ""))[:400]
        self.energy -= 0.1
        to = [g.id for g in self.w.giants.values() if g is not self
              and any(it.kind == "radio_set" for it in g.items())]
        self.w.emit("radio", f'[radio] {self.name}: "{text}"', to=to, data={"from": self.name, "say": text})
        for it in self.w.items.values():
            code = str(it.props.get("text", "")).strip().lower()
            if it.kind == "radio_trigger" and it.props.get("on") and code and code in text.lower():
                it.props["fired"] = True
        return f"Transmitted to {len(to)} listener{'s' if len(to) != 1 else ''}."

    def begin_write(self, a):
        if "item" in a:
            _it, err = self.find(a["item"])
            return err
        p = self.xyz(a)
        if p is None or not self.reach(*p) or not self.w.t["solid"][self.w.get(*p)]:
            return "give an item id, or x, y, z of a solid voxel within reach, to write on"
        a["_p"] = p
        a["_t"] = 5
        return None

    def end_write(self, a):
        text = str(a.get("text", ""))[:200]
        if "item" in a:
            it, err = self.find(a["item"])
            if err:
                return self._fail(a, err)
            it.props["text"] = text
            self.w.mark(it)
            return f"Wrote on {it.name}."
        self.w.signs[a["_p"]] = text
        self.w.rev += 1
        return f"Wrote on the {self.w.mat(*a['_p']).name} at {fmt(self.w, a['_p'])}."

    def begin_label(self, a):
        _it, err = self.find(a.get("item"))
        return err

    def end_label(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return self._fail(a, err)
        it.props["label"] = str(a.get("text", ""))[:40]
        self.w.mark(it)
        return f"Labelled it '{it.props['label']}'."

    def begin_hit(self, a):
        g = self._other(a.get("target"))
        if g is None:
            return f"no giant called '{a.get('target')}' within reach"
        a["_t"], a["_e"] = 3, 0.5
        return None

    def end_hit(self, a):
        g = self._other(a.get("target"), dist=REACH + 1)
        if g is None:
            return "They moved out of reach; your blow missed."
        power = 4 + 2 * self.best("hammer")[0] + self.best("cut")[0]
        g.hurt(power, f"a blow from {self.name}")
        self.w.emit("fight", f"{self.name} struck {g.name}.", self.pos, radius=60)
        return f"You struck {g.name} (-{power:.0f})."

    def begin_push(self, a):
        g = self._other(a.get("target"))
        if g is None:
            return f"no giant called '{a.get('target')}' within reach"
        a["_t"], a["_e"] = 2, 0.3
        return None

    def end_push(self, a):
        w = self.w
        g = self._other(a.get("target"), dist=REACH + 1)
        if g is None:
            return "They moved out of reach."
        dx = (g.x > self.x) - (g.x < self.x)
        dz = (g.z > self.z) - (g.z < self.z)
        if dx == 0 and dz == 0:
            dx = 1
        nx, nz = g.x + dx, g.z + dz
        if not (0 <= nx < w.X and 0 <= nz < w.Z):
            return f"{g.name} is against the edge of the region."
        col_top = w.surface(nx, nz)
        if col_top + 1 > g.k + 1 and w.t["solid"][w.get(nx, g.k, nz)]:
            return f"{g.name} is backed against something solid and does not move."
        g.x, g.z = nx, nz
        g._fall()
        if g.cur and g.cur.get("do") == "move_to":
            g.cur["_path"] = None
        g.inbox.append({"t": w.tick, "type": "pushed", "text": f"{self.name} pushed you."})
        return f"You pushed {g.name} to {fmt(w, g.pos)}."

    def begin_repair(self, a):
        target = self if a.get("target") in (None, "self", self.name) else self._other(a.get("target"))
        if target is None:
            return f"no giant called '{a.get('target')}' within reach"
        if target.integrity >= 99.5:
            return "nothing needs repairing"
        steel = sum(i.mass for i in self._stock("steel"))
        elec = sum(i.mass for i in self._stock("electronics"))
        if steel < 100 or elec < 5:
            return (f"repairs take steel and electronics (100 kg and 5 kg per 10 points); "
                    f"you have {kg(steel)} and {kg(elec)} to hand")
        points = min(100 - target.integrity, steel / 10.0, elec / 0.5, float(a.get("points", 100)))
        a["_t"], a["_e"], a["_points"], a["_who"] = max(5, int(points * 2)), 0.03, points, target.id
        return None

    def end_repair(self, a):
        g = self.w.giants.get(a["_who"])
        if g is None or (g is not self and self._other(g.name, dist=REACH + 1) is None):
            return self._fail(a, "they moved away")
        pts = a["_points"]
        self._use("steel", pts * 10)
        self._use("electronics", pts * 0.5)
        g.integrity = min(100.0, g.integrity + pts)
        if g is not self:
            g.inbox.append({"t": self.w.tick, "type": "repaired",
                            "text": f"{self.name} repaired you (+{pts:.0f}); integrity {g.integrity:.0f}%."})
        return f"Repaired {'yourself' if g is self else g.name} by {pts:.0f} points; integrity {g.integrity:.0f}%."

    def begin_throw(self, a):
        it, err = self.find(a.get("item"))
        if err:
            return err
        if it.holder != self.id:
            return f"pick {it.name} up before throwing it"
        w = self.w
        tx, tz = int(a["x"]), int(a["z"])
        m = it.total_mass
        rng = 40 if m <= 200 else max(3, int(40 * (200.0 / m) ** 0.5))
        d = max(abs(tx - self.x), abs(tz - self.z))
        if d > rng:                                       # falls short along the same line
            f = rng / d
            tx, tz = self.x + int(round((tx - self.x) * f)), self.z + int(round((tz - self.z) * f))
            a["_short"] = rng
        tx, tz = min(max(tx, 0), w.X - 1), min(max(tz, 0), w.Z - 1)
        a["_t"], a["_e"], a["_to"] = 3, 0.3, (tx, tz)
        return None

    def end_throw(self, a):
        w = self.w
        it, err = self.find(a.get("item"))
        if err or it.holder != self.id:
            return self._fail(a, err or "you no longer hold it")
        tx, tz = a["_to"]
        self.carrying.remove(it.id)
        pos = (tx, w.surface(tx, tz) + 1, tz)
        name, m = it.name, it.total_mass
        w.put(it, pos)
        pos = it.pos
        out = [f"Threw {name} to {fmt(w, pos)}" + (f" (as far as you can throw it: {a['_short']} voxels)"
                                                   if "_short" in a else "") + "."]
        for g in w.giants.values():
            if g is not self and g.x == tx and g.z == tz and g.status != "destroyed":
                g.hurt(min(45.0, 3.0 + m / 150.0), f"a {name} thrown by {self.name}")
                out.append(f"It hit {g.name}.")
        spilled = it.props.get("contents")
        if spilled:                                       # liquid slops out on impact
            x, k, z = pos
            for liquid, amt in list(spilled.items()):
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for dk in (-1, 0):
                            q = (x + dx, k + dk, z + dz)
                            if liquid == "fuel":
                                w.soaked.add(q)
                            elif liquid == "water" and amt >= 100:
                                w.burning.pop(q, None)
                out.append(f"{amt:.0f} L of {liquid} spilled.")
            it.props["contents"] = {}
        if it.sub.has("b") and not it.bulk and m > 20:
            w.add_bulk(it.mat, it.mass, pos)
            w.remove(it)
            out.append("It shattered.")
        w.emit("thrown", f"{self.name} threw a {name}.", pos, radius=40)
        return " ".join(out)

    def begin_wait(self, a):
        a["_t"] = min(600, max(1, int(a.get("seconds", 10))))
        return None

    def end_wait(self, a):
        return None


# ---------------------------------------------------------------------------
# Movement helpers
# ---------------------------------------------------------------------------
def stand_level(w, x, z, k):
    """Feet layer for a giant stepping into column (x, z) from layer k, or None.

    A giant steps up 1, climbs up to 3, drops up to 3, needs 4 voxels of
    headroom, and can wade water up to 3 deep.
    """
    if not (0 <= x < w.X and 0 <= z < w.Z):
        return None
    top = int(w.top[x, z])
    col = w.vox[x, z]
    liquid = w.t["liquid"]
    if k - 4 <= top <= k + 2:
        lv = top + 1
        if lv + 3 < w.Y and liquid[col[lv + 3]]:
            return None                              # water over its head
        return lv
    if top < k - 4:
        return None                                  # a drop too far to step down
    solid = w.t["solid"]
    for lv in range(min(k + 3, w.Y - 5), max(k - 4, 0), -1):
        if solid[col[lv - 1]] and not (solid[col[lv]] or solid[col[lv + 1]] or solid[col[lv + 2]]
                                       or solid[col[lv + 3]]):
            return None if liquid[col[lv + 3]] else lv
    return None


def step_cost(w, x, k, z, nx, nk, nz):
    """Seconds to move one voxel."""
    ground = int(w.vox[nx, nz, nk - 1])
    c = 0.5 if ground in FAST else (1.0 if ground in SLOW else 0.7)
    if w.t["liquid"][w.vox[nx, nz, nk]]:
        c = 2.0
    if ground in WEAK:
        c += 12.0                                    # it will break underfoot: avoid if possible
    d = nk - k
    if d > 0:
        c += 0.5 if d == 1 else 2.0 * d
    elif d < 0:
        c += 0.3 * -d
    return c


def find_path(w, start, goal, near=0, me=None, max_nodes=60000, goal_k=None):
    """A* over standable voxels. Returns (path, complete): if the goal can't be
    reached the path leads to the closest point found."""
    sx, sk, sz = start
    gx, gz = goal
    blocked = {(g.x, g.z) for g in w.giants.values() if g is not me and g.status != "destroyed"}
    blocked.discard((gx, gz))
    h0 = abs(sx - gx) + abs(sz - gz)
    openq = [(h0 * 0.75, 0.0, sx, sk, sz)]
    came = {(sx, sz, sk): None}
    cost = {(sx, sz, sk): 0.0}
    best_key, best_h = (sx, sz, sk), h0
    n = 0
    found = None
    while openq and n < max_nodes:
        _f, g, x, k, z = heapq.heappop(openq)
        key = (x, z, k)
        if g > cost.get(key, 1e18):
            continue
        n += 1
        if max(abs(x - gx), abs(z - gz)) <= near and (goal_k is None or abs(k - goal_k) <= 2):
            found = key
            break
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, nz = x + dx, z + dz
            if (nx, nz) in blocked:
                continue
            nk = stand_level(w, nx, nz, k)
            if nk is None:
                continue
            ng = g + step_cost(w, x, k, z, nx, nk, nz)
            nkey = (nx, nz, nk)
            if ng < cost.get(nkey, 1e18):
                cost[nkey] = ng
                came[nkey] = key
                h = abs(nx - gx) + abs(nz - gz)
                if h < best_h:
                    best_h, best_key = h, nkey
                heapq.heappush(openq, (ng + h * 0.75, ng, nx, nk, nz))
    end = found or best_key
    path = []
    while end is not None and came[end] is not None:
        path.append((end[0], end[2], end[1]))
        end = came[end]
    path.reverse()
    return path, found is not None


def fmt(w, p):
    """A world position as agents see it: (x, y, z) with y relative to sea level."""
    return f"({p[0]}, {p[1] - w.sea}, {p[2]})"


def kg(m):
    return f"{m / 1000:.1f} t" if m >= 1000 else f"{m:.0f} kg"
