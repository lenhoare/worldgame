"""Run the world server:  python3 -m worldgame --region ../godot/data/regions/lancing_arena"""

import argparse
import os
import time

from .server import Game, serve
from .sim import add_giant
from .worldgen import build_world

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGION = os.path.join(HERE, "..", "..", "godot", "data", "regions", "lancing_arena")


def main():
    ap = argparse.ArgumentParser(description="WorldGame simulation server")
    ap.add_argument("--region", default=DEFAULT_REGION, help="generated region folder (tools/mapgen/generate.py)")
    ap.add_argument("--seed", type=int, default=1, help="world seed: same region + seed = same world")
    ap.add_argument("--port", type=int, default=8377)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to let other machines connect")
    ap.add_argument("--speed", type=float, default=1.0, help="game seconds per real second (0 = paused)")
    ap.add_argument("--max-giants", type=int, default=8)
    ap.add_argument("--giants", default="", help="comma-separated names to create at start (tokens are printed)")
    args = ap.parse_args()

    t = time.time()
    w = build_world(args.region, args.seed)
    print(f"World '{w.meta.get('name')}' built in {time.time() - t:.1f}s: {w.X} x {w.Z} x {w.Y} voxels of "
          f"{w.cell:.2f} m, {len(w.items)} items, {len(w.sites)} landmarks", flush=True)
    game = Game(w, args.speed, args.max_giants)
    for name in [n.strip() for n in args.giants.split(",") if n.strip()]:
        g = add_giant(w, name, args.max_giants)
        print(f"  giant {g.name}: token {g.token} at ({g.x}, {g.k - w.sea}, {g.z})", flush=True)
    httpd = serve(game, args.host, args.port)
    print(f"Serving on http://{args.host}:{args.port}  (speed {args.speed}x). Ctrl+C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
