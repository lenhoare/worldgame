"""Fuzz the action interface: random (often nonsensical) actions must never raise.

Run longer by hand:  FUZZ_TICKS=20000 python3 -m pytest -q tests/test_fuzz.py
"""

import os
import random

import pytest

import worldgame.sim as sim
from worldgame import physics as P
from worldgame.giants import VERBS
from worldgame.items import FORMS, KINDS
from worldgame.materials import PLACE_AS
from worldgame.observe import inspect, observe, region_map, survey
from worldgame.worldgen import build_world

REGION = os.path.join(os.path.dirname(__file__), "..", "..", "godot", "data", "regions", "lancing_arena")


def random_action(r, w, g, names):
    near = w.items_near(g.x, g.k, g.z, 3, 4)
    ids = [it.id for it in near] + g.carrying
    if not ids or r.random() < 0.12:
        ids = ids + [r.randint(1, 3000), -1, "x"]          # sometimes nonsense
    pick = lambda: r.choice(ids)
    home = w.fuzz_home
    xyz = lambda: {"x": g.x + r.randint(-3, 3), "y": g.k - w.sea + r.randint(-3, 5), "z": g.z + r.randint(-3, 3)}
    verb = r.choice(VERBS)
    a = {"do": verb}
    if verb == "move_to":
        a.update(r.choice([{"x": home[0] + r.randint(-7, 7), "z": home[1] + r.randint(-7, 7)}] * 4 +
                          [{"target": pick()}, {"target": r.choice(names)}, {"x": -5, "z": 99999},
                           {"x": g.x + r.randint(-40, 40), "z": g.z + r.randint(-40, 40)}]))
    elif verb in ("break", "ignite"):
        a.update(r.choice([xyz(), {"item": pick()}]))
    elif verb in ("pick_up", "consume", "label", "switch", "throw"):
        a.update({"item": pick(), "kg": r.choice([1, 500, 1e9]), "text": "t", "on": r.random() < 0.5,
                  "x": g.x + r.randint(-30, 30), "z": g.z + r.randint(-30, 30)})
    elif verb == "drop":
        a.update({"item": pick()})
        a.update(r.choice([{}, xyz(), {"into": pick()}]))
    elif verb == "place":
        a.update(xyz())
        a["material"] = r.choice(list(PLACE_AS) + ["water", "nonsense"])
    elif verb in ("give", "charge", "whisper", "hit", "push", "repair"):
        a.update({"item": pick(), "to": r.choice(names), "target": r.choice(names), "from": pick(),
                  "text": "psst", "kwh": r.choice([5, 1e6])})
    elif verb == "make":
        a.update({"form": r.choice(list(FORMS) + ["sword"]), "from": pick(), "kg": r.choice([10, 300, 5000])})
    elif verb in ("join", "mix"):
        a["items"] = [pick() for _ in range(r.randint(0, 4))]
    elif verb in ("fill", "pour"):
        a.update({"container": pick()})
        a.update(r.choice([xyz(), {"from": pick()}, {"into": pick()}]))
    elif verb in ("connect", "disconnect"):
        a.update({"a": pick(), "b": pick()})
    elif verb in ("extinguish", "fan", "write"):
        a.update(xyz())
        a.update({"seconds": r.randint(1, 50), "text": "mine"})
    elif verb in ("say", "radio"):
        a["text"] = r.choice(["hello", "", "thunder", "x" * 900])
    elif verb == "wait":
        a["seconds"] = r.choice([1, 5, -3, "soon"])
    if r.random() < 0.05:
        a = r.choice([{}, {"do": None}, {"do": verb, "x": "a", "y": [], "z": {}}, {"do": verb, "item": None}])
    return a


@pytest.mark.parametrize("seed", [int(x) for x in os.environ.get("FUZZ_SEEDS", "11").split(",")])
def test_random_actions_never_break_the_world(seed):
    if not os.path.exists(REGION):
        pytest.skip("arena region not generated")
    ticks = int(os.environ.get("FUZZ_TICKS", "2500"))
    sim.STRICT = True
    r = random.Random(seed)
    w = build_world(REGION, 5)
    giants = [sim.add_giant(w, n) for n in ("Ada", "Bo", "Cy", "Di")]
    for g in giants[1:]:                                   # put them together so they interact
        g.x, g.z = giants[0].x + r.randint(-4, 4), giants[0].z + r.randint(-4, 4)
        g.k = w.surface(g.x, g.z) + 1
    names = [g.name for g in giants] + ["Nobody"]
    hx, hz = giants[0].x, giants[0].z
    w.fuzz_home = (hx, hz)
    for g in giants:                                       # everyone starts able to light fires and lash things
        for kind in ("blowtorch", "rope_coil"):
            it = P.spawn(w, kind, g.pos, r)
            w.lift(it)
            it.holder = g.id
            g.carrying.append(it.id)
    for kind in list(KINDS) * 2:                           # a pile of every kind of thing to play with
        P.spawn(w, kind, (hx + r.randint(-6, 6), w.Y - 2, hz + r.randint(-6, 6)), r)
    for mat in ("wood", "flint", "steel", "clay", "sand", "lime", "brick", "charcoal", "fibre", "copper"):
        w.add_bulk(mat, r.uniform(500, 40000), (hx + r.randint(-6, 6), w.Y - 2, hz + r.randint(-6, 6)))
    for t in range(ticks):
        for g in giants:
            if g.status != "destroyed" and len(g.queue) < 3 and r.random() < 0.5:
                g.queue.append(random_action(r, w, g, names))
            if g.status == "dormant" and r.random() < 0.02:
                g.energy = 300
        sim.step(w)
        if t % 97 == 0:
            for g in giants:
                observe(w, g)
                survey(w, g, {"r": r.randint(1, 60)})
                inspect(w, g, r.choice([{"x": g.x, "z": g.z, "y": 2}, {"item": r.randint(1, 3000)},
                                        {"giant": "Bo"}, {}]))
                region_map(w, g)
    assert w.tick >= ticks
    internal = [e for g in giants for e in g.inbox if "internal error" in e.get("text", "")]
    assert not internal, internal[:3]
    # The fuzz is only meaningful if things actually happened.
    done = sum(g.stats["broken"] + g.stats["made"] + g.stats["placed"] + g.stats["said"] for g in giants)
    assert done > 20 and sum(g.stats["walked"] for g in giants) > 50
    print("fuzz stats:", w.stats, [dict(g.stats, status=g.status, integrity=round(g.integrity)) for g in giants])
