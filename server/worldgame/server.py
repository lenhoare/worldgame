"""HTTP API for agents, humans and the viewer. Standard library only.

Agents (one giant each, identified by a token from /join):
  POST /join     {name}                      -> {token, rules, ...}
  GET  /observe  ?token=                     -> what the giant perceives now
  POST /act      {token, actions, replace?}  -> queue actions (replace clears the queue first)
  POST /query    {token, q, ...}             -> inspect | survey | map | substance | rules
  POST /note     {token, text}               -> add to the giant's own notebook
Humans (advice only):
  POST /advise   {token, text}               -> shown to the giant in its next observation
Viewer:
  GET  /view/meta, /view/state?since=rev, /view/chunks?since=rev (gzip binary)
Admin (need ?key= unless the server runs with an empty admin key):
  GET  /admin/pause, /admin/resume, /admin/speed?x=, /admin/step?n=, /admin/save
  POST /admin/do {key, op: spawn|ignite|energy|integrity|teleport|rain, ...}
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import materials as M
from . import observe as O
from .giants import VERBS
from .mesher import MeshCache
from .sim import add_giant, step
from .world import CHUNK


class Game:
    def __init__(self, world, speed=1.0, max_giants=8, admin_key="", save_path="", autosave=0):
        self.w = world
        self.lock = threading.RLock()
        self.speed = speed
        self.paused = False
        self.max_giants = max_giants
        self.mesh = MeshCache(world)
        self.started = time.time()
        self.admin_key = admin_key          # "" = admin endpoints open (local testing only)
        self.save_path = save_path
        self.autosave = autosave            # game ticks between automatic saves (0 = never)

    # --- simulation thread ---------------------------------------------------
    def run(self):
        nxt = time.time()
        while True:
            if self.paused or self.speed <= 0:
                time.sleep(0.05)
                nxt = time.time()
                continue
            nxt += 1.0 / self.speed
            with self.lock:
                step(self.w)
                if self.autosave and self.save_path and self.w.tick % self.autosave == 0:
                    self.save()
            delay = nxt - time.time()
            if delay > 0:
                time.sleep(delay)
            elif delay < -2:
                nxt = time.time()           # fell behind: don't try to catch up

    def save(self):
        from . import persist
        with self.lock:
            persist.save(self.w, self.save_path)
        return self.save_path

    def admin(self, body):
        """Host tools: spawn items, light fires, set energy, move giants, change the weather."""
        from . import physics as P
        w = self.w
        op = body.get("op")
        with self.lock:
            if op == "spawn":
                x, z = int(body["x"]), int(body["z"])
                pos = (x, w.surface(x, z) + 1, z)
                if body.get("kind") in M.SUBSTANCES:
                    it = w.add_bulk(body["kind"], float(body.get("kg", 1000)), pos)
                else:
                    it = P.spawn(w, body["kind"], pos)
                return 200, {"item": it.id, "at": O.pos3(w, it.pos)}
            if op == "ignite":
                p = (int(body["x"]), int(body["y"]) + w.sea, int(body["z"]))
                return 200, {"lit": P.ignite_voxel(w, p, force=True)}
            g = next((g for g in w.giants.values() if g.name == body.get("giant")), None)
            if op in ("energy", "teleport", "integrity") and g is None:
                return 404, {"error": "no such giant"}
            if op == "energy":
                g.energy = float(body["value"])
                return 200, {"energy": g.energy}
            if op == "integrity":
                g.integrity = float(body["value"])
                return 200, {"integrity": g.integrity}
            if op == "teleport":
                g.x, g.z = int(body["x"]), int(body["z"])
                g.k = w.surface(g.x, g.z) + 1
                g.cur, g.queue = None, []
                return 200, {"at": O.pos3(w, g.pos)}
            if op == "rain":
                w.raining = int(body.get("ticks", 600))
                return 200, {"raining": w.raining}
        return 400, {"error": "op must be one of: spawn, ignite, energy, integrity, teleport, rain"}

    def giant(self, token):
        for g in self.w.giants.values():
            if g.token == token:
                return g
        return None

    # --- agent API --------------------------------------------------------------
    def join(self, body):
        name = str(body.get("name", "")).strip()[:20] or f"Giant{len(self.w.giants) + 1}"
        with self.lock:
            if any(g.name == name for g in self.w.giants.values()):
                return 409, {"error": f"the name '{name}' is taken"}
            if len(self.w.giants) >= self.max_giants:
                return 409, {"error": "the game is full"}
            g = add_giant(self.w, name, self.max_giants)
            return 200, {"token": g.token, "name": g.name, "id": g.id, "at": O.pos3(self.w, g.pos),
                         "region": self.w.meta.get("name"), "size_voxels": [self.w.X, self.w.Z],
                         "voxel_metres": round(self.w.cell, 2), "rules": O.RULES}

    def observe(self, token):
        g = self.giant(token)
        if g is None:
            return 401, {"error": "unknown token; POST /join first"}
        with self.lock:
            return 200, O.observe(self.w, g)

    def act(self, body):
        g = self.giant(body.get("token"))
        if g is None:
            return 401, {"error": "unknown token"}
        actions = body.get("actions")
        if isinstance(actions, dict):
            actions = [actions]
        if not isinstance(actions, list):
            return 400, {"error": "actions must be a list of {do: verb, ...}"}
        bad = [a for a in actions if not isinstance(a, dict) or a.get("do") not in VERBS]
        if bad:
            return 400, {"error": f"unknown action in {bad[:2]}", "verbs": list(VERBS)}
        with self.lock:
            if body.get("replace"):
                g.queue = []
                g.cur = None
                g.doing = "idle"
            room = 40 - len(g.queue)
            clean = [{k: v for k, v in a.items() if not str(k).startswith("_")} for a in actions[:room]]
            g.queue.extend(clean)
            return 200, {"queued": len(clean), "queue_length": len(g.queue), "tick": self.w.tick,
                         "dropped": max(0, len(actions) - room)}

    def query(self, body):
        g = self.giant(body.get("token"))
        if g is None:
            return 401, {"error": "unknown token"}
        q = body.get("q")
        with self.lock:
            if q == "inspect":
                return 200, O.inspect(self.w, g, body)
            if q == "survey":
                return 200, O.survey(self.w, g, body)
            if q == "map":
                return 200, O.region_map(self.w, g)
            if q == "substance":
                return 200, O.substance_info(body)
            if q == "rules":
                return 200, {"rules": O.RULES}
        return 400, {"error": "q must be one of: inspect, survey, map, substance, rules"}

    def note(self, body):
        g = self.giant(body.get("token"))
        if g is None:
            return 401, {"error": "unknown token"}
        with self.lock:
            g.notes.append(str(body.get("text", ""))[:500])
            g.notes = g.notes[-40:]
        return 200, {"notes": len(g.notes)}

    def advise(self, body):
        g = self.giant(body.get("token"))
        if g is None:
            return 401, {"error": "unknown token"}
        with self.lock:
            g.advice.append(str(body.get("text", ""))[:1000])
            self.w.log.append({"t": self.w.tick, "type": "advice", "text": f"(to {g.name}) {body.get('text', '')[:200]}"})
        return 200, {"ok": True}

    # --- viewer -------------------------------------------------------------------
    def view_meta(self):
        w = self.w
        return 200, {"name": w.meta.get("name"), "size": [w.X, w.Y, w.Z], "sea": w.sea, "cell": w.cell,
                     "chunk": CHUNK, "chunks": list(w.chunk_rev.shape),
                     "materials": [{"id": v.id, "name": v.name, "colour": v.colour, "kind": v.kind,
                                    "tags": list(v.tags)} for v in M.VOXELS],
                     "home": w.meta.get("home"), "attribution": w.meta.get("attribution", []),
                     "sites": w.sites}

    def view_state(self, since):
        w = self.w
        with self.lock:
            items = []
            for it in w.items.values():
                if it.rev > since:
                    e = {"id": it.id, "s": sprite_key(it), "name": it.name, "kg": round(it.total_mass)}
                    if it.pos is not None:
                        e["p"] = list(it.pos)
                    if it.props.get("burning"):
                        e["burning"] = True
                    if it.props.get("text"):
                        e["text"] = it.props["text"]
                    items.append(e)
            giants = []
            for g in w.giants.values():
                e = {"id": g.id, "name": g.name, "colour": g.colour, "p": [g.x, g.k, g.z], "doing": g.doing,
                     "state": g.status, "energy": round(g.energy), "integrity": round(g.integrity),
                     "carrying": [it.name for it in g.items()][:6]}
                if g.said and w.tick - g.said[1] < 30:
                    e["said"] = g.said[0]
                giants.append(e)
            fires = [list(p) for p in list(w.burning)[:4000]]
            fires += [list(w.items[i].pos) for i in w.burning_items if i in w.items and w.items[i].pos]
            import numpy as np
            cxs, czs = np.nonzero(w.chunk_rev > since)
            links = []
            for a, b, _m in w.links:
                ia, ib = w.items.get(a), w.items.get(b)
                if ia and ib and ia.pos and ib.pos:
                    links.append(list(ia.pos) + list(ib.pos))
            return 200, {
                "tick": w.tick, "clock": w.clock(), "rev": w.rev, "daylight": round(w.daylight(), 3),
                "raining": bool(w.raining), "wind": [round(v, 2) for v in w.wind], "paused": self.paused,
                "speed": self.speed, "giants": giants, "items": items,
                "removed": [i for r, i in w.removed_items if r > since],
                "fires": fires, "links": links,
                "signs": [{"p": list(p), "text": t} for p, t in w.signs.items()],
                "log": [e for e in list(w.log)[-40:]],
                "chunks": len(cxs), "stats": w.stats,
            }

    def view_heights(self):
        """Top solid layer of every column (uint8, x-major), gzip: for the camera and picking."""
        import gzip
        import numpy as np
        with self.lock:
            return gzip.compress(np.clip(self.w.top, 0, 255).astype(np.uint8).tobytes(), compresslevel=3)

    def view_chunks(self, since):
        with self.lock:
            return self.mesh.since(since)


def sprite_key(it):
    """Which sprite the viewer should draw for an item."""
    if it.bulk:
        return it.mat
    if it.kind == "assembly":
        role = it.props.get("role")
        if role == "tool":
            head = next((p[0] for p in it.props.get("parts", []) if p[0] in ("blade", "pick", "hammer", "shovel")), "")
            return {"blade": "axe", "pick": "pickaxe", "hammer": "hammer_tool", "shovel": "shovel"}.get(head, "axe")
        return role or "bundle"
    return it.kind


def make_handler(game):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, obj, raw=None, ctype="application/json"):
            data = raw if raw is not None else json.dumps(obj, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/observe":
                    return self._send(*game.observe(q.get("token")))
                if u.path == "/view/meta":
                    return self._send(*game.view_meta())
                if u.path == "/view/state":
                    return self._send(*game.view_state(int(q.get("since", 0))))
                if u.path == "/view/chunks":
                    return self._send(200, None, game.view_chunks(int(q.get("since", 0))),
                                      "application/octet-stream")
                if u.path == "/view/heights":
                    return self._send(200, None, game.view_heights(), "application/octet-stream")
                if u.path == "/rules":
                    return self._send(200, {"rules": O.RULES})
                if u.path.startswith("/admin/") and game.admin_key and q.get("key") != game.admin_key:
                    return self._send(403, {"error": "admin key required (?key=...)"})
                if u.path == "/admin/save":
                    if not game.save_path:
                        return self._send(400, {"error": "start the server with --save PATH"})
                    return self._send(200, {"saved": game.save()})
                if u.path == "/admin/pause":
                    game.paused = True
                    return self._send(200, {"paused": True})
                if u.path == "/admin/resume":
                    game.paused = False
                    return self._send(200, {"paused": False})
                if u.path == "/admin/speed":
                    game.speed = max(0.0, min(200.0, float(q.get("x", 1))))
                    return self._send(200, {"speed": game.speed})
                if u.path == "/admin/step":
                    with game.lock:
                        step(game.w, max(1, min(100000, int(q.get("n", 1)))))
                    return self._send(200, {"tick": game.w.tick})
                if u.path == "/":
                    w = game.w
                    return self._send(200, {"game": "worldgame", "region": w.meta.get("name"), "tick": w.tick,
                                            "clock": w.clock(), "giants": [g.name for g in w.giants.values()],
                                            "speed": game.speed, "paused": game.paused,
                                            "docs": "POST /join {name}; GET /rules"})
                return self._send(404, {"error": "not found"})
            except Exception as e:
                return self._send(500, {"error": repr(e)})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if not isinstance(body, dict):
                    return self._send(400, {"error": "send a JSON object"})
            except Exception:
                return self._send(400, {"error": "invalid JSON"})
            try:
                if u.path == "/admin/do":
                    if game.admin_key and body.get("key") != game.admin_key:
                        return self._send(403, {"error": "admin key required"})
                    return self._send(*game.admin(body))
                route = {"/join": game.join, "/act": game.act, "/query": game.query, "/note": game.note,
                         "/advise": game.advise}.get(u.path)
                if route is None:
                    return self._send(404, {"error": "not found"})
                return self._send(*route(body))
            except Exception as e:
                return self._send(500, {"error": repr(e)})

    return H


def serve(game, host="127.0.0.1", port=8377):
    httpd = ThreadingHTTPServer((host, port), make_handler(game))
    httpd.daemon_threads = True
    threading.Thread(target=game.run, daemon=True).start()
    return httpd
