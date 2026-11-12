"""Tests for the simulation's generic systems, on a small synthetic world.

Run: cd server && python3 -m pytest -q
"""

import os

import numpy as np
import pytest

from worldgame import materials as M
from worldgame import physics as P
from worldgame.items import affordances
from worldgame.observe import inspect, observe, survey
from worldgame.sim import add_giant, power_tick, step
from worldgame.world import World
import worldgame.sim as _sim

_sim.STRICT = True

ID = M.ID
GROUND = 10          # top ground layer in the test world
SEA = 8


def flat(X=40, Z=40, Y=28, surface="turf"):
    """Flat land: chalk bedrock, a layer of soil, turf on top at layer GROUND."""
    w = World(X, Z, Y, 3.0, SEA, seed=7)
    w.vox[:, :, :GROUND - 1] = ID["chalk"]
    w.vox[:, :, GROUND - 1] = ID["soil"]
    w.vox[:, :, GROUND] = ID[surface]
    w.rebuild_top()
    w.raining = 0
    w.meta = {"home": {"x": X * 1.5, "z": Z * 1.5}}
    return w


def giant(w, x=20, z=20, name="Ada"):
    g = add_giant(w, name)
    g.x, g.z = x, z
    g.k = w.surface(x, z) + 1
    return g


def run(w, g, actions, ticks=400):
    g.queue = list(actions)
    for _ in range(ticks):
        step(w)
        if g.cur is None and not g.queue:
            break
    return [e["text"] for e in g.inbox]


def y(k):
    return k - SEA


def house(w, x0, z0, n=4, storeys=2):
    """A small brick house with interior and tiled roof."""
    for x in range(x0, x0 + n):
        for z in range(z0, z0 + n):
            edge = x in (x0, x0 + n - 1) or z in (z0, z0 + n - 1)
            w.vox[x, z, GROUND] = ID["paving"]
            for s in range(1, storeys + 1):
                w.vox[x, z, GROUND + s] = ID["brick_wall"] if edge else ID["interior_home"]
            w.vox[x, z, GROUND + storeys + 1] = ID["roof_tile"]
    w.rebuild_top()


# --- movement -----------------------------------------------------------------
def test_walks_and_goes_round_a_house():
    w = flat()
    house(w, 18, 10)
    g = giant(w, 20, 20)
    run(w, g, [{"do": "move_to", "x": 20, "z": 5}])
    assert (g.x, g.z) == (20, 5)
    assert g.stats["walked"] >= 15
    assert g.energy < 600


def test_cannot_walk_into_deep_water():
    w = flat()
    w.vox[:, :10, GROUND - 5:GROUND + 1] = ID["seawater"]     # six voxels deep
    w.rebuild_top()
    g = giant(w, 20, 20)
    out = run(w, g, [{"do": "move_to", "x": 20, "z": 2}])
    assert g.z >= 10
    assert any("could not get closer" in t or "no walkable route" in t for t in out)


def test_fall_damage():
    w = flat()
    g = giant(w, 20, 20)
    for k in range(GROUND - 5, GROUND + 1):
        w.set(20, k, 20, M.AIR)
    step(w, 2)
    assert g.k == GROUND - 5
    assert g.integrity < 100


# --- breaking, carrying, building -------------------------------------------------
def test_break_yields_material_and_loot():
    w = flat()
    house(w, 21, 19)
    g = giant(w, 20, 20)
    out = run(w, g, [{"do": "break", "x": 21, "y": y(GROUND + 1), "z": 20}])
    assert w.get(21, GROUND + 1, 20) == M.AIR
    assert any("brick" in t for t in out)
    brick = [it for it in w.items.values() if it.mat == "brick"]
    assert brick and 7000 < brick[0].mass < 8500


def test_bare_hands_cannot_break_steel_and_say_why():
    w = flat()
    w.set(21, GROUND + 1, 20, ID["steel_plate"])
    g = giant(w, 20, 20)
    out = run(w, g, [{"do": "break", "x": 21, "y": y(GROUND + 1), "z": 20}])
    assert w.get(21, GROUND + 1, 20) == ID["steel_plate"]
    assert any("needs a tool" in t for t in out)


def test_carry_limit_and_partial_pickup():
    w = flat()
    g = giant(w, 20, 20)
    pile = w.add_bulk("soil", 50000, (21, GROUND + 1, 20))
    run(w, g, [{"do": "pick_up", "item": pile.id}])
    assert abs(g.load() - 20000) < 1
    assert abs(pile.mass - 30000) < 1


def test_place_needs_enough_material_then_builds():
    w = flat()
    g = giant(w, 20, 20)
    a = w.add_bulk("brick", 10000, (20, GROUND + 1, 21))
    out = run(w, g, [{"do": "place", "material": "brick", "x": 21, "y": y(GROUND + 1), "z": 20}])
    assert any("takes" in t for t in out) and w.get(21, GROUND + 1, 20) == M.AIR
    a.mass = 40000
    run(w, g, [{"do": "place", "material": "brick", "x": 21, "y": y(GROUND + 1), "z": 20}])
    assert w.get(21, GROUND + 1, 20) == ID["masonry"]
    assert a.mass < 10000


# --- gravity and structure ---------------------------------------------------------
def test_loose_ground_caves_in():
    w = flat()
    w.set(5, GROUND - 1, 5, M.AIR)        # hollow under the turf
    step(w, 2)
    assert w.get(5, GROUND - 1, 5) == ID["turf"]
    assert w.get(5, GROUND, 5) == M.AIR


def test_house_collapses_when_undermined():
    w = flat()
    house(w, 10, 10)
    for x in range(10, 14):
        for z in range(10, 14):
            w.set(x, GROUND + 1, z, M.AIR)        # remove the whole ground floor
    step(w, 5)
    assert w.stats["collapsed"] > 10
    assert not (w.vox[10:14, 10:14, GROUND + 2:] == ID["brick_wall"]).any()
    assert any(it.mat in ("rubble", "brick") for it in w.items.values()) or (w.vox == ID["rubble"]).any()


def test_one_missing_wall_voxel_does_not_bring_the_house_down():
    w = flat()
    house(w, 10, 10)
    w.set(10, GROUND + 1, 11, M.AIR)
    step(w, 5)
    assert w.get(10, GROUND + 2, 11) == ID["brick_wall"]
    assert w.stats["collapsed"] == 0


def test_span_limits_overhang():
    w = flat()
    w.set(5, GROUND + 1, 5, ID["timber"])
    for i in range(1, 4):
        w.set(5 + i, GROUND + 1 + 0, 5, M.AIR)
    w.set(5, GROUND + 2, 5, ID["timber"])
    for i in range(1, 6):                          # timber spans 3
        w.set(5 + i, GROUND + 2, 5, ID["timber"])
    step(w, 5)
    assert w.get(8, GROUND + 2, 5) == ID["timber"]
    assert w.get(9, GROUND + 2, 5) == M.AIR and w.get(10, GROUND + 2, 5) == M.AIR


def test_felled_tree_comes_down_as_wood():
    w = flat()
    for k in (1, 2, 3):
        w.vox[6, 6, GROUND + k] = ID["wood"]
    w.rebuild_top()
    w.set(6, GROUND + 1, 6, M.AIR)
    step(w, 5)
    assert w.get(6, GROUND + 3, 6) == M.AIR
    assert sum(it.mass for it in w.items.values() if it.mat == "wood") > 3000


# --- fire and heat -----------------------------------------------------------------
def test_fire_spreads_through_a_house_and_burns_out():
    w = flat(surface="paving")
    house(w, 10, 10, n=5)
    assert P.ignite_voxel(w, (12, GROUND + 1, 12), force=True)
    step(w, 60)
    assert len(w.burning) > 3
    step(w, 1500)
    assert not w.burning
    assert w.stats["burnt"] >= 6
    assert not (w.vox[10:15, 10:15] == ID["interior_home"]).any()


def test_fire_needs_air_and_smothered_wood_becomes_charcoal():
    w = flat()
    p = (5, GROUND - 2, 5)
    w.vox[5, 5, GROUND - 2] = ID["wood"]           # wood sealed inside the ground
    assert not P.ignite_voxel(w, p, force=True)
    logs = w.add_bulk("wood", 3000, (8, GROUND + 1, 8))
    P.ignite_item(w, logs)
    step(w, 6)
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in (1, 2):
            w.set(8 + dx, GROUND + k, 8 + dz, ID["soil"])      # bank earth round it
    w.set(8, GROUND + 2, 8, ID["stonework"])       # and cap it
    step(w, 6)
    assert logs.mat == "charcoal" and not logs.props.get("burning")


def test_kiln_fires_clay_and_burns_lime():
    w = flat(surface="paving")
    fuel = w.add_bulk("charcoal", 20000, (8, GROUND + 1, 8))
    pot = w.new_item("vessel", "clay", 400, (8, GROUND + 1, 8))
    chalk = w.add_bulk("chalk", 2000, (8, GROUND + 1, 8))
    P.ignite_item(w, fuel)
    step(w, 120)
    assert pot.mat == "ceramic" and pot.kind == "vessel"
    assert chalk.mat == "lime"


def test_steel_needs_enclosure_and_forced_air_to_melt():
    w = flat(surface="paving")
    pos = (8, GROUND + 1, 8)
    assert P.fire_temp(w, pos, "charcoal") < 1500
    for dx, dz in ((1, 0), (-1, 0), (0, 1)):
        w.vox[8 + dx, 8 + dz, GROUND + 1] = ID["stonework"]
    assert 1300 <= P.fire_temp(w, pos, "charcoal") < 1500
    w.blow[pos] = w.tick + 100
    assert P.fire_temp(w, pos, "charcoal") >= 1500


def test_fuel_explodes_in_fire_and_craters():
    w = flat()
    can = P.spawn(w, "fuel_tank", (8, GROUND + 1, 8))
    can.props["contents"] = {"fuel": 600}
    g = giant(w, 10, 8)
    P.heat_item(w, can, 900, 2)
    step(w, 3)
    assert can.id not in w.items
    assert w.get(8, GROUND, 8) == M.AIR
    assert g.integrity < 100


# --- water ---------------------------------------------------------------------------
def test_canal_floods_from_the_sea():
    w = flat()
    w.vox[:, :6, GROUND - 3:GROUND + 1] = M.AIR
    w.vox[:, :6, GROUND - 3:SEA] = ID["seawater"]      # sea surface at layer SEA-1, below the land
    w.rebuild_top()
    for z in range(6, 12):                              # dig a trench inland, down to sea level
        for k in range(SEA - 1, GROUND + 1):
            w.set(20, k, z, M.AIR)
    step(w, 60)
    assert w.get(20, SEA - 1, 11) == ID["seawater"]
    assert w.get(20, SEA, 11) == M.AIR                  # but no higher than the sea


def test_water_puts_out_fire():
    w = flat()
    w.set(5, GROUND + 1, 5, ID["timber"])
    P.ignite_voxel(w, (5, GROUND + 1, 5), force=True)
    w.set(6, GROUND + 1, 5, ID["water"])
    step(w, 4)
    assert not w.burning


# --- making things -------------------------------------------------------------------
def test_flint_axe_cuts_what_hands_cannot():
    w = flat()
    g = giant(w, 20, 20)
    flint = w.add_bulk("flint", 600, (20, GROUND + 1, 21))
    logs = w.add_bulk("wood", 2000, (20, GROUND + 1, 21))
    rope = P.spawn(w, "rope_coil", (20, GROUND + 1, 21))
    out = run(w, g, [
        {"do": "pick_up", "item": flint.id}, {"do": "pick_up", "item": logs.id},
        {"do": "pick_up", "item": rope.id},
        {"do": "make", "form": "blade", "from": flint.id},
        {"do": "make", "form": "rod", "from": logs.id},
    ])
    blade = next(it for it in g.items() if it.kind == "blade")
    rod = next(it for it in g.items() if it.kind == "rod")
    assert affordances(blade)["cut"] == pytest.approx(5.6)
    out = run(w, g, [{"do": "join", "items": [blade.id, rod.id]}])
    axe = next(it for it in g.items() if it.kind == "assembly")
    assert axe.props["role"] == "tool" and affordances(axe)["cut"] > 8
    w.set(21, GROUND + 1, 20, ID["steel_plate"])
    run(w, g, [{"do": "break", "x": 21, "y": y(GROUND + 1), "z": 20}])
    assert w.get(21, GROUND + 1, 20) == M.AIR


def test_metal_must_be_hot_to_shape():
    w = flat()
    g = giant(w, 20, 20)
    steel = w.add_bulk("steel", 2000, (20, GROUND + 1, 21))
    out = run(w, g, [{"do": "make", "form": "blade", "from": steel.id}])
    assert any("Heat it" in t for t in out)
    steel.props["temp"] = 1000
    out = run(w, g, [{"do": "make", "form": "blade", "from": steel.id}])
    assert any(it.kind == "blade" and it.mat == "steel" for it in w.items.values())


def test_cart_from_wheels_raises_capacity():
    w = flat()
    g = giant(w, 20, 20)
    parts = [w.new_item("wheel", "steel", 500, (20, GROUND + 1, 21)) for _ in range(2)]
    parts.append(w.new_item("plate", "steel", 800, (20, GROUND + 1, 21)))
    parts.append(w.new_item("rod", "steel", 300, (20, GROUND + 1, 21)))
    rope = P.spawn(w, "rope_coil", (20, GROUND + 1, 21))
    run(w, g, [{"do": "pick_up", "item": rope.id}, {"do": "join", "items": [p.id for p in parts]}])
    cart = next(it for it in g.items() if it.kind == "assembly")
    assert cart.props["role"] == "cart" and g.haul() == 40000


# --- energy and power -----------------------------------------------------------------
def test_consume_wood_and_draw_from_battery():
    w = flat()
    g = giant(w, 20, 20)
    g.energy = 100
    logs = w.add_bulk("wood", 2000, (20, GROUND + 1, 21))
    pack = P.spawn(w, "ev_pack", (21, GROUND + 1, 20))
    pack.props["charge"] = 50
    run(w, g, [{"do": "pick_up", "item": logs.id}, {"do": "consume", "item": logs.id},
               {"do": "charge", "from": pack.id}])
    assert g.energy == pytest.approx(100 + 300 + 50, abs=3)


def test_running_out_of_energy_makes_dormant_until_helped():
    w = flat()
    g = giant(w, 20, 20)
    helper = giant(w, 21, 20, "Bo")
    g.energy = 0.001
    step(w, 2)
    assert g.status == "dormant"
    run(w, g, [{"do": "move_to", "x": 5, "z": 5}], 5)
    assert g.x == 20
    run(w, helper, [{"do": "charge", "to": "Ada", "kwh": 50}])
    step(w, 2)
    assert g.status == "active" and g.energy > 40


def test_solar_charger_network_recharges_a_giant():
    w = flat()
    w.tick = 1800                                        # around midday
    g = giant(w, 20, 20)
    g.energy = 100
    arrays = [P.spawn(w, "solar_array", (22 + i, GROUND + 1, 20)) for i in range(4)]
    charger = P.spawn(w, "charger", (21, GROUND + 1, 20))
    drum = P.spawn(w, "cable_drum", (20, GROUND + 1, 21))
    acts = [{"do": "pick_up", "item": drum.id}]
    acts += [{"do": "connect", "a": a.id, "b": charger.id} for a in arrays]
    run(w, g, acts, 600)
    assert len(w.links) == 4
    before = g.energy
    step(w, 600)
    assert g.energy > before + 5
    assert charger.props.get("powered") is True


# --- minds ---------------------------------------------------------------------------
def test_speech_is_heard_nearby_only():
    w = flat(X=300, Z=40)
    a, b, c = giant(w, 20, 20, "Ada"), giant(w, 60, 20, "Bo"), giant(w, 280, 20, "Cy")
    for g in (a, b, c):
        g.inbox = []
    run(w, a, [{"do": "say", "text": "anyone there?"}])
    assert any("anyone there?" in e["text"] for e in b.inbox)
    assert not any("anyone there?" in e["text"] for e in c.inbox)


def test_observation_and_queries_are_readable():
    w = flat()
    house(w, 22, 18)
    g = giant(w, 20, 20)
    w.add_bulk("flint", 500, (21, GROUND + 1, 21))
    obs = observe(w, g)
    assert obs["you"]["at"] == [20, y(GROUND + 1), 20]
    assert len(obs["map"]["surface"]) == 25 and obs["map"]["surface"][12][12] == "@"
    assert "B" in "".join(obs["map"]["surface"]) or "^" in "".join(obs["map"]["surface"])
    assert obs["items_nearby"][0]["name"] == "flint"
    col = inspect(w, g, {"x": 22, "z": 18, "y": y(GROUND + 1)})
    assert col["voxel"]["material"] == "brick_wall" and "breaks_into" in col["voxel"]
    s = survey(w, g, {"r": 10})
    assert s["structure_voxels"]["brick_wall"] > 0


def test_same_seed_same_world():
    region = os.path.join(os.path.dirname(__file__), "..", "..", "godot", "data", "regions", "lancing_arena")
    if not os.path.exists(region):
        pytest.skip("arena region not generated")
    from worldgame.worldgen import build_world
    a, b = build_world(region, 3), build_world(region, 3)
    assert np.array_equal(a.vox, b.vox)
    assert [(i.kind, i.pos, round(i.mass)) for i in a.items.values()] == \
           [(i.kind, i.pos, round(i.mass)) for i in b.items.values()]


def test_sensor_alarm_reaches_its_owner():
    w = flat(X=120)
    owner, intruder = giant(w, 20, 20, "Ada"), giant(w, 100, 20, "Bo")
    sensor = P.spawn(w, "sensor", (22, GROUND + 1, 20))
    pack = P.spawn(w, "battery_pack", (23, GROUND + 1, 20))
    drum = P.spawn(w, "cable_drum", (20, GROUND + 1, 21))
    run(w, owner, [{"do": "pick_up", "item": drum.id}, {"do": "pick_up", "item": sensor.id},
                   {"do": "drop", "item": sensor.id, "x": 22, "y": y(GROUND + 1), "z": 20},
                   {"do": "connect", "a": sensor.id, "b": pack.id},
                   {"do": "move_to", "x": 60, "z": 20}], 300)
    owner.inbox = []
    run(w, intruder, [{"do": "move_to", "x": 26, "z": 20}], 300)
    step(w, 10)
    assert any(e["type"] == "alarm" and "Bo" in e["text"] for e in owner.inbox)


def test_radio_reaches_only_radio_holders():
    w = flat(X=300)
    a, b, c = giant(w, 20, 20, "Ada"), giant(w, 280, 20, "Bo"), giant(w, 150, 20, "Cy")
    for g in (a, b):
        r = P.spawn(w, "radio_set", (g.x, GROUND + 1, g.z + 1))
        run(w, g, [{"do": "pick_up", "item": r.id}])
    for g in (a, b, c):
        g.inbox = []
    run(w, a, [{"do": "radio", "text": "meet at the station"}])
    assert any("meet at the station" in e["text"] for e in b.inbox)
    assert not any("meet at the station" in e["text"] for e in c.inbox)


def test_push_off_an_edge_and_hit():
    w = flat()
    for k in range(GROUND - 4, GROUND + 1):
        for z in range(18, 23):
            w.vox[22, z, k] = M.AIR
    w.rebuild_top()
    a, b = giant(w, 20, 20, "Ada"), giant(w, 21, 20, "Bo")
    run(w, a, [{"do": "hit", "target": "Bo"}, {"do": "push", "target": "Bo"}])
    step(w, 2)
    assert b.x == 22 and b.k < a.k
    assert b.integrity < 96


def test_save_and_load_round_trip(tmp_path):
    from worldgame import persist
    w = flat()
    house(w, 10, 10)
    g = giant(w, 20, 20)
    flint = w.add_bulk("flint", 600, (20, GROUND + 1, 21))
    run(w, g, [{"do": "pick_up", "item": flint.id}, {"do": "make", "form": "blade", "from": flint.id}])
    P.ignite_voxel(w, (11, GROUND + 1, 11), force=True)
    w.signs[(10, GROUND + 1, 10)] = "keep out"
    g.notes.append("remember the flint")
    g.queue = [{"do": "move_to", "x": 30, "z": 30}]
    path = str(tmp_path / "game")
    persist.save(w, path)
    w2 = persist.load(path)
    g2 = w2.giants[g.id]
    assert np.array_equal(w.vox, w2.vox) and w2.tick == w.tick
    assert g2.token == g.token and g2.notes == g.notes and [it.name for it in g2.items()] == [it.name for it in g.items()]
    assert w2.burning == w.burning and w2.signs == w.signs
    step(w, 200)
    step(w2, 200)                                   # same state + same random stream -> same future
    assert (g2.x, g2.z) == (g.x, g.z) == (30, 30)
    assert np.array_equal(w.vox, w2.vox)


# --- throwing, storage, triggers ------------------------------------------------------
def test_thrown_fuel_then_a_torch_starts_a_fire():
    w = flat(surface="paving")
    house(w, 30, 18, n=4)
    g = giant(w, 20, 20)
    can = P.spawn(w, "fuel_can", (20, GROUND + 1, 21))
    can.props["contents"] = {"fuel": 15}
    torch = w.add_bulk("wood", 150, (19, GROUND + 1, 18))   # well away from the fuel
    P.ignite_item(w, torch)
    out = run(w, g, [{"do": "pick_up", "item": can.id}, {"do": "throw", "item": can.id, "x": 31, "z": 20},
                     {"do": "pick_up", "item": torch.id}, {"do": "throw", "item": torch.id, "x": 31, "z": 20}])
    assert any("spilled" in t for t in out)
    assert any(p[0] in (30, 31, 32) for p in w.soaked)
    step(w, 40)
    assert w.burning or w.stats["burnt"] > 0


def test_heavy_things_fall_short_and_hurt():
    w = flat()
    a, b = giant(w, 20, 20, "Ada"), giant(w, 24, 20, "Bo")
    rock = w.add_bulk("rock", 5000, (20, GROUND + 1, 21))
    out = run(w, a, [{"do": "pick_up", "item": rock.id}, {"do": "throw", "item": rock.id, "x": 24, "z": 20}])
    assert b.integrity < 100
    rock2 = w.add_bulk("rock", 18000, (a.x, GROUND + 1, a.z + 1))
    out = run(w, a, [{"do": "pick_up", "item": rock2.id}, {"do": "throw", "item": rock2.id, "x": 39, "z": 20}])
    assert any("as far as you can throw" in t for t in out)


def test_store_things_in_a_container_and_carry_it():
    w = flat()
    g = giant(w, 20, 20)
    skip = P.spawn(w, "skip", (20, GROUND + 1, 21))
    bricks = w.add_bulk("brick", 6000, (21, GROUND + 1, 20))
    pack = P.spawn(w, "ev_pack", (21, GROUND + 1, 21))
    run(w, g, [{"do": "pick_up", "item": bricks.id}, {"do": "drop", "item": bricks.id, "into": skip.id},
               {"do": "pick_up", "item": pack.id}, {"do": "drop", "item": pack.id, "into": skip.id},
               {"do": "pick_up", "item": skip.id}, {"do": "move_to", "x": 30, "z": 30}])
    assert g.load() == pytest.approx(900 + 6000 + 400)
    assert inspect(w, g, {"item": skip.id})["inside"][0]["name"] == "brick"
    run(w, g, [{"do": "pick_up", "item": pack.id}])
    assert pack.holder == g.id and pack.inside is None and skip.props["stored"] == [bricks.id]
    run(w, g, [{"do": "break", "item": skip.id}])           # breaking the container spills what is left
    assert bricks.pos is not None and bricks.inside is None


def _wire(w, g, pairs):
    drum = P.spawn(w, "cable_drum", (g.x, g.k, g.z))
    run(w, g, [{"do": "pick_up", "item": drum.id}] + [{"do": "connect", "a": a.id, "b": b.id} for a, b in pairs], 600)


def test_pressure_plate_trap_sets_off_gas():
    w = flat(X=80)
    owner, victim = giant(w, 20, 20, "Ada"), giant(w, 60, 20, "Bo")
    plate = P.spawn(w, "pressure_plate", (30, GROUND + 1, 20))
    ign = P.spawn(w, "igniter", (31, GROUND + 1, 20))
    gas = P.spawn(w, "gas_cylinder", (31, GROUND + 1, 20))
    pack = P.spawn(w, "battery_pack", (29, GROUND + 1, 21))
    _wire(w, owner, [(pack, plate), (plate, ign)])
    assert ign.props["trigger"] == plate.id
    step(w, 30)
    assert gas.id in w.items                                 # armed but quiet
    run(w, victim, [{"do": "move_to", "x": 30, "z": 20}], 200)
    step(w, 12)
    assert gas.id not in w.items and victim.integrity < 100


def test_timer_and_radio_trigger():
    w = flat()
    g = giant(w, 20, 20)
    timer = P.spawn(w, "timer", (22, GROUND + 1, 20))
    siren = P.spawn(w, "siren", (23, GROUND + 1, 20))
    rx = P.spawn(w, "radio_trigger", (22, GROUND + 1, 22))
    ign = P.spawn(w, "igniter", (23, GROUND + 1, 22))
    pack = P.spawn(w, "battery_pack", (21, GROUND + 1, 21))
    radio = P.spawn(w, "radio_set", (20, GROUND + 1, 21))
    logs = w.add_bulk("wood", 500, (23, GROUND + 1, 22))
    _wire(w, g, [(pack, timer), (timer, siren), (pack, rx), (rx, ign)])
    run(w, g, [{"do": "switch", "item": timer.id, "on": True, "seconds": 40},
               {"do": "write", "item": rx.id, "text": "thunder"}, {"do": "switch", "item": rx.id, "on": True},
               {"do": "pick_up", "item": radio.id}], 200)
    start = w.tick
    g.inbox = []
    step(w, 20)
    assert not any(e["type"] == "siren" for e in g.inbox) and not logs.props.get("burning")
    step(w, 40)
    assert any(e["type"] == "siren" for e in g.inbox)
    run(w, g, [{"do": "radio", "text": "all quiet"}])
    step(w, 10)
    assert not logs.props.get("burning")
    run(w, g, [{"do": "radio", "text": "THUNDER now"}])
    step(w, 10)
    assert logs.props.get("burning") or logs.id not in w.items
