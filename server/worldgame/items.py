"""Items: loose material, salvaged objects, and things giants make.

An item is either *bulk* (a divisible mass of one substance: 3.2 t of brick)
or a discrete object: salvage with a function (a car, a generator), a shaped
part (a steel blade), or an assembly of joined parts (an axe, a cart).

What an item can *do* is never looked up by name. `affordances()` derives it
from the item's form, substance and parts, so a flint blade, a glass blade and
a steel blade are all blades, with cutting power set by their hardness.
"""

from .materials import SUBSTANCES

# ---------------------------------------------------------------------------
# Salvage: discrete objects found in the world.
#   mass kg; parts = what it breaks down into [(substance or kind, kg or count)]
#   comp = electrical role with parameters
# ---------------------------------------------------------------------------
KINDS = {
    "car": dict(mass=1300, desc="an abandoned car",
                parts=[("steel", 800), ("aluminium", 120), ("glass", 40), ("plastic", 110),
                       ("copper", 15), ("electronics", 10), ("tyre", 4)]),
    "tyre": dict(mass=15, mat="rubber", desc="a car tyre on its wheel; rolls", wheel_kg=600),
    "battery_12v": dict(mass=18, mat="lead", desc="a 12 V car battery", comp="battery", cap_kwh=1.0),
    "ev_pack": dict(mass=400, mat="electronics", desc="an electric-car battery pack",
                    comp="battery", cap_kwh=60.0, parts=[("electronics", 150), ("aluminium", 150),
                                                         ("copper", 60)]),
    "battery_pack": dict(mass=800, mat="electronics", desc="an industrial battery bank",
                         comp="battery", cap_kwh=150.0, parts=[("electronics", 300), ("steel", 300),
                                                               ("copper", 120)]),
    "solar_array": dict(mass=200, mat="glass", desc="a rack of ten solar panels", comp="source",
                        kw=3.5, solar=True, parts=[("glass", 120), ("aluminium", 50), ("electronics", 20)]),
    "generator": dict(mass=1500, mat="steel", desc="a diesel generator; burns fuel to make power",
                      comp="source", kw=100.0, burns_l_per_kwh=0.3, cap_l=200,
                      parts=[("steel", 1100), ("copper", 250), ("electronics", 30)]),
    "charger": dict(mass=250, mat="steel", desc="a vehicle charger; recharges a giant standing next to it",
                    comp="sink", kw=150.0, parts=[("steel", 150), ("copper", 60), ("electronics", 30)]),
    "floodlight": dict(mass=40, mat="aluminium", desc="a floodlight", comp="sink", kw=1.0,
                       parts=[("aluminium", 25), ("glass", 8), ("electronics", 4)]),
    "radio_set": dict(mass=30, mat="electronics", desc="a two-way radio; reaches the whole region when powered",
                      comp="sink", kw=0.5, parts=[("electronics", 20), ("copper", 6)]),
    "motor": dict(mass=300, mat="steel", desc="an electric motor; set under a doorway it lifts the wall above it "
                                              "(up to 3 voxels) while powered, and lowers it again when not",
                  comp="sink", kw=50.0,
                  parts=[("steel", 180), ("copper", 110)]),
    "pump": dict(mass=200, mat="steel", desc="an electric pump", comp="sink", kw=15.0,
                 parts=[("steel", 150), ("copper", 40)]),
    "blower": dict(mass=120, mat="steel", desc="an electric blower; forces air into a fire", comp="sink",
                   kw=5.0, parts=[("steel", 90), ("copper", 25)]),
    "heater": dict(mass=400, mat="steel", desc="an electric furnace element; reaches 1600 C when powered",
                   comp="sink", kw=80.0, parts=[("steel", 300), ("copper", 80)]),
    "sensor": dict(mass=15, mat="electronics", desc="a motion sensor; when powered it reports giants that come "
                                                   "near to whoever set it down, and acts as a trigger",
                   comp="sink", kw=0.1, trigger=True, parts=[("electronics", 12)]),
    # Triggers: wire one to a device and the device only runs while the trigger is active.
    "switch": dict(mass=10, mat="steel", desc="a heavy switch; wire a device through it to turn it on and off",
                   comp="trigger", parts=[("steel", 8), ("copper", 2)]),
    "timer": dict(mass=8, mat="electronics", desc="a timer; once switched on it activates after its delay "
                                                  "(set 'seconds' when you switch it on)",
                  comp="trigger", parts=[("electronics", 6), ("copper", 1)]),
    "pressure_plate": dict(mass=120, mat="steel", desc="a pressure plate; active while a giant stands on it",
                           comp="trigger", parts=[("steel", 110), ("copper", 5)]),
    "radio_trigger": dict(mass=6, mat="electronics", desc="a radio receiver; activates when a radio message "
                                                          "contains the code word written on it",
                          comp="trigger", parts=[("electronics", 5)]),
    "igniter": dict(mass=12, mat="steel", desc="an electric igniter; lights whatever it sits on when it gets power",
                    comp="sink", kw=0.5, parts=[("steel", 8), ("copper", 3)]),
    "siren": dict(mass=25, mat="steel", desc="a siren; heard far away while powered", comp="sink", kw=0.5,
                  parts=[("steel", 18), ("copper", 5)]),
    "computer": dict(mass=20, mat="electronics", desc="a computer (rare tech)",
                     parts=[("electronics", 14), ("aluminium", 4), ("copper", 1)]),
    "medical_scanner": dict(mass=2000, mat="steel", desc="a hospital scanner (rare tech, full of copper and magnets)",
                            parts=[("steel", 1100), ("copper", 600), ("electronics", 250)]),
    "cable_drum": dict(mass=320, mat="copper", desc="a drum of heavy copper cable", wire_m=300,
                       parts=[("copper", 290), ("wood", 30)]),
    "fuel_can": dict(mass=5, mat="steel", desc="a fuel can", cap_l=20),
    "fuel_tank": dict(mass=350, mat="steel", desc="a steel fuel tank", cap_l=1000),
    "tank": dict(mass=400, mat="steel", desc="a steel water tank", cap_l=5000),
    "skip": dict(mass=900, mat="steel", desc="an open steel skip; holds loose material", cap_l=8000),
    "shipping_container": dict(mass=2200, mat="steel", desc="a shipping container", cap_l=33000),
    "gas_cylinder": dict(mass=40, mat="steel", desc="a pressurised gas cylinder; explodes in fire",
                         explosive=6.0),
    "blowtorch": dict(mass=15, mat="steel", desc="a gas blowtorch; lights fires and reaches 1300 C briefly",
                      ignites=True),
    "rail": dict(mass=900, mat="steel", desc="a length of steel rail", form="beam"),
    "sleeper": dict(mass=80, mat="wood", desc="a timber railway sleeper", form="beam"),
    "tarpaulin": dict(mass=30, mat="fabric", desc="a tarpaulin sheet", form="sheet"),
    "rope_coil": dict(mass=50, mat="fibre", desc="a coil of rope", form="rope"),
}

# Loot rolled when a building voxel is broken: (chance, what, lo, hi).
# Substances give kg; kinds give a count.
LOOT = {
    "home": [(.9, "wood", 300, 900), (.7, "fabric", 50, 200), (.7, "plastic", 50, 200),
             (.6, "steel", 50, 250), (.6, "copper", 5, 25), (.4, "electronics", 5, 20),
             (.5, "glass", 20, 60), (.04, "battery_12v", 1, 1), (.03, "rope_coil", 1, 1)],
    "shop": [(.9, "plastic", 200, 600), (.7, "steel", 100, 300), (.6, "glass", 50, 150),
             (.5, "electronics", 10, 60), (.5, "fabric", 50, 300), (.5, "copper", 10, 30),
             (.03, "fuel_can", 1, 1), (.02, "battery_pack", 1, 1), (.03, "computer", 1, 2),
             (.02, "timer", 1, 1), (.02, "siren", 1, 1), (.015, "radio_trigger", 1, 1), (.01, "radio_set", 1, 1)],
    "industrial": [(.9, "steel", 500, 2500), (.6, "copper", 20, 100), (.5, "aluminium", 50, 300),
                   (.5, "plastic", 50, 300), (.4, "electronics", 10, 50), (.08, "motor", 1, 1),
                   (.05, "cable_drum", 1, 1), (.03, "pump", 1, 1), (.015, "generator", 1, 1),
                   (.03, "tank", 1, 1), (.02, "battery_pack", 1, 1), (.03, "floodlight", 1, 2),
                   (.04, "rope_coil", 1, 1), (.05, "tarpaulin", 1, 2), (.03, "blowtorch", 1, 1),
                   (.04, "gas_cylinder", 1, 2), (.02, "blower", 1, 1), (.01, "heater", 1, 1),
                   (.02, "sensor", 1, 2), (.01, "radio_set", 1, 1), (.03, "switch", 1, 2), (.02, "timer", 1, 1),
                   (.015, "pressure_plate", 1, 1), (.015, "igniter", 1, 2), (.015, "siren", 1, 1),
                   (.01, "radio_trigger", 1, 1)],
    "medical": [(.8, "plastic", 100, 400), (.7, "steel", 100, 400), (.8, "electronics", 30, 120),
                (.5, "copper", 10, 60), (.6, "fabric", 50, 200), (.2, "computer", 1, 2),
                (.03, "medical_scanner", 1, 1), (.08, "battery_pack", 1, 1),
                (.1, "gas_cylinder", 1, 2), (.03, "generator", 1, 1), (.05, "sensor", 1, 2),
                (.03, "radio_set", 1, 1)],
    "garage": [(.9, "steel", 300, 1200), (.6, "rubber", 50, 200), (.6, "tyre", 1, 4),
               (.35, "fuel_can", 1, 2), (.1, "blowtorch", 1, 1), (.15, "gas_cylinder", 1, 1),
               (.4, "battery_12v", 1, 2), (.03, "cable_drum", 1, 1), (.05, "rope_coil", 1, 1),
               (.05, "tarpaulin", 1, 1), (.03, "motor", 1, 1), (.04, "fuel_tank", 1, 1),
               (.02, "charger", 1, 1), (.05, "switch", 1, 1), (.04, "igniter", 1, 2), (.02, "timer", 1, 1)],
    "roof": [(.06, "solar_array", 1, 1)],
    "roof_big": [(.12, "solar_array", 1, 2)],
}

# ---------------------------------------------------------------------------
# Forms: shapes a giant can give to material. min_kg is a giant-sized part.
# ---------------------------------------------------------------------------
FORMS = {
    "blade": 150, "pick": 300, "hammer": 600, "shovel": 250, "rod": 200, "beam": 800,
    "plank": 300, "plate": 500, "sheet": 30, "wire": 50, "pipe": 300, "vessel": 400,
    "wheel": 400, "brick": 1000, "block": 2000, "rope": 40, "lens": 60, "mirror": 100,
}
HEADS = ("blade", "pick", "hammer", "shovel")
HANDLES = ("rod", "beam", "plank")
BINDERS = ("rope", "wire")


def can_make(form, sub, ctx):
    """How could `form` be made from substance `sub`? Returns (method, None) or (None, reason).

    ctx: temp (item temperature, C), cut (best cutting power carried), wet (water to hand).
    """
    if form not in FORMS:
        return None, f"unknown form '{form}'. Forms: {', '.join(FORMS)}"
    hot, cut, wet = ctx.get("temp", 15), ctx.get("cut", 0), ctx.get("wet", False)
    if sub.has("l"):
        return None, "liquids can't be shaped"
    if sub.metal or sub.name == "glass":
        if form == "rope":
            return None, "twist wire instead: make 'wire' first"
        if hot >= sub.melt:
            return "cast", None
        if sub.metal and form != "lens" and hot >= 0.6 * sub.melt:
            return "forge", None
        if sub.name == "glass" and form in ("blade", "pick"):
            return "knap", None
        need = f"molten (at least {sub.melt:.0f} C)"
        if sub.metal:
            need = f"hot enough to forge (at least {0.6 * sub.melt:.0f} C) or " + need
        return None, f"{sub.name} must be {need}; it is at {hot:.0f} C. Heat it in a fire first"
    if form in ("lens", "mirror", "wire"):
        return None, f"a {form} needs glass or metal"
    if sub.has("m"):
        if form in ("vessel", "brick", "plate", "pipe", "block"):
            return ("mould", None) if wet else (None, "clay must be wet to mould: have water to hand "
                                                "(carry a container of water or stand beside water)")
        return None, f"clay can be moulded into vessel, brick, plate, pipe or block, not {form}"
    if sub.has("f"):
        if form in ("rope", "sheet"):
            return "twist", None
        if sub.name == "wood":
            if form == "rod":
                return "snap", None
            if form in ("beam", "plank", "wheel", "vessel", "block", "shovel", "hammer", "plate"):
                return ("carve", None) if cut > sub.hardness else (
                    None, f"carving wood needs a cutting tool harder than {sub.hardness}; best carried: {cut:.1f}")
        return None, f"{sub.name} can't be made into a {form}"
    if sub.has("b") and sub.hardness >= 5 and form in ("blade", "pick"):
        return "knap", None
    if sub.has("s"):
        if form in ("block", "plate", "wheel", "hammer", "vessel", "brick"):
            return ("carve", None) if cut > sub.hardness else (
                None, f"cutting {sub.name} needs a tool harder than {sub.hardness}; best carried: {cut:.1f}")
        return None, f"{sub.name} is too brittle to make a {form}"
    if sub.name in ("plastic", "rubber") and form in ("sheet", "rope", "wheel", "pipe", "vessel"):
        return "cut", None
    return None, f"no way is known to make a {form} from {sub.name}"


# ---------------------------------------------------------------------------
class Item:
    __slots__ = ("id", "kind", "mat", "mass", "pos", "holder", "inside", "props", "rev")

    def __init__(self, iid, kind, mat, mass, pos=None, **props):
        self.id = iid
        self.kind = kind          # "bulk", a KINDS key, a FORMS key, or "assembly"
        self.mat = mat
        self.mass = float(mass)
        self.pos = pos            # (x, y, z) when lying in the world
        self.holder = None        # giant id when carried
        self.inside = None        # container item id when stored
        self.props = props
        self.rev = 0

    @property
    def bulk(self):
        return self.kind == "bulk"

    @property
    def sub(self):
        return SUBSTANCES[self.mat]

    @property
    def total_mass(self):
        m = self.mass + self.props.get("stored_kg", 0.0)
        for kg in self.props.get("contents", {}).values():
            m += kg
        return m

    @property
    def name(self):
        if self.props.get("label"):
            return self.props["label"]
        if self.bulk:
            return self.mat
        if self.kind == "assembly":
            return self.props.get("role", "assembly")
        if self.kind in FORMS:
            return f"{self.mat} {self.kind}"
        return self.kind.replace("_", " ")

    def brief(self):
        d = {"id": self.id, "name": self.name, "kg": round(self.total_mass)}
        p = self.props
        if "cap_kwh" in p:
            d["charge_kwh"] = round(p.get("charge", 0), 1)
        if p.get("contents"):
            d["holds"] = {k: round(v) for k, v in p["contents"].items()}
        if p.get("stored"):
            d["items_inside"] = len(p["stored"])
        if p.get("burning"):
            d["burning"] = True
        if p.get("temp", 15) > 80:
            d["temp_c"] = round(p["temp"])
        if p.get("text"):
            d["text"] = p["text"]
        if p.get("on") is False:
            d["switched"] = "off"
        return d

    def describe(self):
        d = self.brief()
        k = KINDS.get(self.kind)
        if k:
            d["what"] = k["desc"]
            if k.get("parts"):
                d["breaks_into"] = dict(k["parts"])
        d["made_of"] = self.mat
        d["substance"] = self.sub.describe()
        if "cap_l" in self.props:
            d["capacity_litres"] = self.props["cap_l"]
        if "wire_m" in self.props:
            d["wire_metres"] = round(self.props["wire_m"])
        if self.props.get("parts"):
            d["parts"] = [f"{pm} {pk}" for pk, pm, _kg in self.props["parts"]]
        d["can_do"] = affordances(self)
        return d


def affordances(it):
    """What this item can be used for, derived from its form and substance."""
    a = {}
    p, sub, k = it.props, it.sub, KINDS.get(it.kind, {})
    form = k.get("form", it.kind)
    parts = p.get("parts")
    if it.kind == "assembly":
        role = p.get("role")
        if role == "tool":
            head = next(x for x in parts if x[0] in HEADS)
            hs = SUBSTANCES[head[1]]
            if head[0] in ("blade", "pick"):
                a["cut"] = round(hs.hardness * 1.15, 2)   # a handle adds leverage
            if head[0] == "pick":
                a["dig"] = 2.0
            if head[0] == "shovel":
                a["dig"] = 3.0
            if head[0] == "hammer":
                a["hammer"] = round(hs.hardness * head[2] / 600.0, 2)
        elif role == "cart":
            a["haul_kg"] = p.get("haul_kg", 0)
        elif role == "bellows":
            a["blow"] = True
        return a
    if form in ("blade", "pick"):
        a["cut"] = round(sub.hardness * 0.8, 2)
        if form == "pick":
            a["dig"] = 1.5
    if form == "shovel":
        a["dig"] = 2.0
    if form == "hammer":
        a["hammer"] = round(sub.hardness * it.mass / 600.0, 2)
    if form == "wheel":
        a["wheel_kg"] = round(it.mass * (40 if sub.metal or sub.has("s") else 25))
    if "wheel_kg" in k:
        a["wheel_kg"] = k["wheel_kg"]
    if form == "vessel":
        a["contain_l"] = round(it.mass * 12)
        a["max_temp_c"] = sub.melt if sub.melt > 0 else (350 if sub.has("o") else 1500)
    if "cap_l" in p:
        a["contain_l"] = p["cap_l"]
        a["max_temp_c"] = sub.melt or 1500
    if form in ("rope", "wire") or "wire_m" in p:
        a["bind"] = True
    if form == "wire" or "wire_m" in p:
        a["wire_m"] = round(p.get("wire_m", it.mass * 1.0))
    if form == "lens" and sub.has("t"):
        a["focus_sunlight"] = True
    if k.get("ignites") or p.get("burning"):
        a["ignite"] = True
    if it.mat == "flint":
        a["spark_with_steel"] = True
    if sub.flammability > 0 and sub.energy > 0:
        a["fuel_kwh"] = round(sub.energy * it.mass / 1000.0, 1)
    if "cap_kwh" in p:
        a["stored_kwh"] = round(p.get("charge", 0), 1)
    if k.get("comp"):
        a["electrical"] = k["comp"]
        if k.get("kw"):
            a["kw"] = k["kw"]
    if k.get("comp") == "trigger" or k.get("trigger"):
        a["triggers_devices_wired_to_it"] = True
    if k.get("explosive"):
        a["explodes"] = True
    if sub.has("c") and form in ("rod", "beam", "plate", "wire"):
        a["conducts"] = True
    return a


def recognise_assembly(parts, binder):
    """Work out what a set of joined parts is. parts: [(form, substance, kg)].

    Returns (role, props) or (None, reason). New patterns can be added here;
    anything unrecognised is still a valid 'bundle'.
    """
    forms = [f for f, _s, _kg in parts]
    heads = [x for x in parts if x[0] in HEADS]
    handles = [x for x in parts if x[0] in HANDLES]
    wheels = [x for x in parts if x[0] in ("wheel", "tyre")]
    if len(heads) == 1 and len(handles) >= 1 and len(parts) == 2:
        return "tool", {"label": f"{heads[0][1]} {'axe' if heads[0][0] == 'blade' else heads[0][0]}"}
    beds = [x for x in parts if x[0] in ("plate", "plank", "skip", "shipping_container", "tank", "beam")]
    axles = [x for x in parts if x[0] == "rod"]
    if len(wheels) >= 2 and beds and axles:
        rating = 0.0
        for f, s, kg in wheels:
            sub = SUBSTANCES[s]
            rating += 600 if f == "tyre" else kg * (40 if sub.metal or sub.has("s") else 25)
        return "cart", {"label": "cart", "haul_kg": round(rating)}
    sheets = [x for x in parts if x[0] in ("sheet", "tarpaulin")]
    boards = [x for x in parts if x[0] in ("plank", "plate")]
    if sheets and len(boards) >= 2:
        return "bellows", {"label": "bellows"}
    return "bundle", {"label": "bundle of " + ", ".join(sorted(set(forms)))}
