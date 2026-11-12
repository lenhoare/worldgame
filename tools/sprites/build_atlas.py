#!/usr/bin/env python3
"""Build the item sprite atlas for the Godot viewer from the Pixel Art Atlas dataset.

Source: https://huggingface.co/datasets/Angais/pixel-art-atlas-1.4m (CC0 1.0),
1.4 million AI-generated 16x16 sprites. Download and unzip
`pixel-art-16x16-1.4m.zip`, then:

    python3 -I tools/sprites/build_atlas.py /path/to/unzipped

Writes godot/assets/sprites/items.png (a grid of 16x16 sprites) and items.json
(game item key -> cell index). One sprite is picked per key: among the
subject's sprites, the one whose filled area is closest to typical, preferring
more colours, so the choice is deterministic.

The dataset is untrusted input: it is only read with numpy (no pickle), json
and Pillow.
"""

import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "godot", "assets", "sprites")
COLS = 16

# game key -> dataset subject
SPRITES = {
    "default": "crate", "fire": "flame",
    # salvage
    "car": "car", "tyre": "old tire", "battery_12v": "car battery", "ev_pack": "battery pack",
    "battery_pack": "battery", "solar_array": "solar panel", "generator": "electric generator",
    "charger": "fuel pump", "floodlight": "street lamp", "radio_set": "radio", "motor": "electric motor",
    "pump": "water pump", "blower": "electric fan", "heater": "space heater", "sensor": "digital camera",
    "computer": "desktop computer", "medical_scanner": "handheld scanner", "cable_drum": "wire spool",
    "fuel_can": "hazard barrel", "fuel_tank": "barrel", "tank": "rain barrel", "skip": "dumpster",
    "shipping_container": "shipping container", "gas_cylinder": "propane tank", "blowtorch": "welding torch",
    "rail": "rail segment", "sleeper": "plank stack", "tarpaulin": "tarp", "rope_coil": "coil of rope",
    # loose substances
    "brick": "brick pile", "rubble": "rubble pile", "concrete": "concrete slab", "steel": "ingot pile",
    "copper": "copper ore", "aluminium": "metal sheet", "lead": "ingot", "glass": "glass marble",
    "plastic": "food storage container", "rubber": "rubber ball", "electronics": "circuit board",
    "wood": "wooden log", "charcoal": "charcoal lump", "ash": "ash pile", "flint": "flint nodule",
    "chalk": "piece of chalk", "soil": "dirt pile", "clay": "lump of clay", "sand": "sand pile",
    "gravel": "gravel pile", "tile": "roof tile", "ceramic": "stock pot", "lime": "mortar and pestle",
    "mortar": "tar bucket", "biomass": "pile of leaves", "fibre": "straw bundle", "fabric": "fabric bolt",
    "rock": "rock pile", "sandstone": "cut stone", "mudstone": "rock", "basalt": "jagged rock",
    "slate": "pointed rock", "asphalt": "rubble chunk", "salt": "sand pile",
    # shapes giants make
    "blade": "blade blank", "pick": "pickaxe head", "hammer": "hammer head", "shovel": "shovel",
    "rod": "stick", "beam": "support beam", "plank": "plank", "plate": "metal sheet", "sheet": "tarp",
    "wire": "wire coil", "pipe": "pipe", "vessel": "bucket", "wheel": "wagon wheel", "block": "stone block",
    "rope": "coil of rope", "lens": "camera lens", "mirror": "mirror",
    # assemblies
    "axe": "axe", "pickaxe": "pickaxe", "hammer_tool": "hammer", "cart": "mine cart", "bellows": "bellows",
    "bundle": "rod bundle",
}


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    tokens = np.load(os.path.join(src, "tokens.npy"), mmap_mode="r", allow_pickle=False)
    palette = np.load(os.path.join(src, "palette.npy"), allow_pickle=False)
    with open(os.path.join(src, "objects.json"), encoding="utf-8") as f:
        subjects = json.load(f)
    rows_by_subject = {}
    wanted = set(SPRITES.values())
    for i, s in enumerate(subjects):
        if s in wanted:
            rows_by_subject.setdefault(s, []).append(i)

    keys = list(SPRITES)
    rows = (len(keys) + COLS - 1) // COLS
    atlas = np.zeros((rows * 16, COLS * 16, 4), np.uint8)
    index, chosen = {}, {}
    for n, key in enumerate(keys):
        cand = rows_by_subject.get(SPRITES[key])
        if not cand:
            print(f"  no sprites for subject {SPRITES[key]!r} ({key}); using blank")
            continue
        cand = cand[:120]
        px = np.asarray(tokens[cand])                      # (n, 256) palette indices, 0 = transparent
        filled = (px != 0).sum(axis=1)
        colours = np.array([len(np.unique(p)) for p in px])
        score = -np.abs(filled - np.median(filled)) + 0.5 * colours
        best = cand[int(np.argmax(score))]
        p = np.asarray(tokens[best]).reshape(16, 16)
        rgba = np.dstack((palette[p], (p != 0).astype(np.uint8) * 255))
        r, c = divmod(n, COLS)
        atlas[r * 16:(r + 1) * 16, c * 16:(c + 1) * 16] = rgba
        index[key] = n
        chosen[key] = {"subject": SPRITES[key], "row": int(best)}

    os.makedirs(OUT, exist_ok=True)
    Image.fromarray(atlas, "RGBA").save(os.path.join(OUT, "items.png"), optimize=True)
    with open(os.path.join(OUT, "items.json"), "w") as f:
        json.dump({"cell": 16, "columns": COLS, "rows": rows, "index": index, "source": chosen,
                   "credit": "Pixel Art Atlas 1.4M by Angais, CC0 1.0, "
                             "https://huggingface.co/datasets/Angais/pixel-art-atlas-1.4m"}, f, indent=1)
    print(f"Wrote {len(index)} sprites to {OUT}/items.png ({COLS * 16} x {rows * 16})")


if __name__ == "__main__":
    main()
