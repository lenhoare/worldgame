#!/usr/bin/env python3
"""A simple rule-following giant, for testing the server without a language model.

It shows the agent loop every client uses: join, then once a "minute" observe
and send a short list of actions. This bot scavenges: it drains cars for fuel,
pulls down the nearest building, piles the bricks and builds a wall with them.

    python3 agents/scripted_bot.py --name Brick --server http://127.0.0.1:8377 --period 5
"""

import argparse
import json
import time
import urllib.request


def call(server, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server + path, data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def decide(obs, state):
    """Return a list of actions for the next minute."""
    you = obs["you"]
    x, y, z = you["at"]
    m = obs["map"]
    ox, oz = m["top_left"]
    items = obs["items_nearby"]
    if you["doing"] != "idle" or you["queued"]:
        return []
    # 1. Low on energy: drain the nearest car that still has fuel.
    if you["energy_kwh"] < 450:
        for it in items:
            if it["name"] == "car" and it.get("holds", {}).get("fuel", 0) > 2:
                return [{"do": "move_to", "target": it["id"]}, {"do": "consume", "item": it["id"]}]
    # 2. Carrying bricks: take them home and build.
    bricks = next((c for c in you["carrying"] if c["name"] == "brick"), None)
    hx, hz = state.setdefault("home", (x, z))
    if bricks and bricks["kg"] > 15000:
        return [{"do": "move_to", "x": hx, "z": hz, "near": 1}, {"do": "drop", "item": bricks["id"]}]
    # A voxel of masonry takes about 35 t of brick: build once the pile at home is big enough.
    pile = sum(it["kg"] for it in items if it["name"] == "brick" and it["dist"] <= 2)
    if pile >= 36000 and abs(x - hx) <= 1 and abs(z - hz) <= 1:
        n = state.get("built", 0)
        return [{"do": "place", "material": "brick", "x": hx + 2, "y": y + n // 5, "z": hz - 2 + n % 5},
                {"do": "say", "text": "Another block on the wall."}]
    # 3. Loose bricks nearby: pick them up.
    for it in items:
        if it["name"] == "brick" and 2 < it["dist"] <= 8:
            return [{"do": "move_to", "target": it["id"]}, {"do": "pick_up", "item": it["id"]}]
    # 4. Otherwise break the nearest brick wall on the local map.
    best = None
    for j, row in enumerate(m["surface"]):
        for i, ch in enumerate(row):
            if ch in "B^i":
                d = abs(ox + i - x) + abs(oz + j - z)
                if d > 1 and (best is None or d < best[0]):
                    best = (d, ox + i, oz + j)
    if best:
        _, bx, bz = best
        # The height map says how far the column rises above the ground under us (digits 1-9).
        h = m["height"][bz - oz][bx - ox]
        top = int(h) if h.isdigit() else 0
        return [{"do": "move_to", "x": bx, "z": bz, "near": 1}] + \
               [{"do": "break", "x": bx, "y": y - 1 + dy, "z": bz} for dy in range(min(top, 4), 0, -1)]
    # 5. Nothing in sight: wander.
    state["leg"] = state.get("leg", 0) + 1
    dx, dz = [(15, 0), (0, 15), (-15, 0), (0, -15)][state["leg"] % 4]
    return [{"do": "move_to", "x": x + dx, "z": z + dz}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8377")
    ap.add_argument("--name", default="Brick")
    ap.add_argument("--period", type=float, default=60.0, help="seconds between decisions")
    ap.add_argument("--turns", type=int, default=0, help="stop after this many decisions (0 = forever)")
    args = ap.parse_args()
    joined = call(args.server, "/join", {"name": args.name})
    token = joined["token"]
    print(f"{args.name} joined at {joined['at']}; token {token}")
    state = {}
    turn = 0
    while not args.turns or turn < args.turns:
        obs = call(args.server, f"/observe?token={token}")
        for e in obs["events"]:
            print(f"  [{e['type']}] {e['text']}")
        acts = decide(obs, state)
        if acts:
            if any(a["do"] == "place" for a in acts):
                state["built"] = state.get("built", 0) + 1
            call(args.server, "/act", {"token": token, "actions": acts})
            print(f"t={obs['time']['tick']} at {obs['you']['at']} energy {obs['you']['energy_kwh']:.0f}: "
                  + ", ".join(a["do"] for a in acts))
        turn += 1
        time.sleep(args.period)


if __name__ == "__main__":
    main()
