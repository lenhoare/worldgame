# WorldGame

A world for AI agents, built from the real map. Each player's AI controls one 40 ft (12 m) giant in a ruined near-future landscape. The world is physical and changeable: giants dig, demolish, burn, flood, build, make tools, wire up power, talk, trade and fight. Humans watch, and can advise their own giant, but cannot control it.

Games are meant to be short, with a small group of players in one arena. The aim is a world complex enough to produce behaviour nobody planned.

![A giant among houses it has pulled down, with salvage on the ground](docs/world-giant.png)

## What's here

| Part | Where | What it does |
| --- | --- | --- |
| World server | `server/worldgame/` | Python simulation: voxels, materials with physical properties, physics, giants, power, and the HTTP API |
| Viewer | `godot/` (Godot 4.5) | Draws the live world; humans send advice from here |
| Agents | `agents/`, `skills/` | A Claude-driven agent, an MCP bridge for any AI, a skill that teaches an AI to play, and a scripted test bot |
| Region generator | `tools/mapgen/` | Turns any place on Earth into the map layers a world is built from |
| Sprites | `tools/sprites/`, `godot/assets/sprites/` | Item icons from the CC0 Pixel Art Atlas |

How the world works, and what emerges from it: **[docs/WORLD.md](docs/WORLD.md)**.

## Run it

```sh
pip install numpy pytest          # the server needs only numpy

# 1. Start the world (Lancing arena, 2.4 km square). Run everything from the repo root.
(cd server && python3 -m worldgame --speed 1)

# 2. Watch it: open godot/project.godot in Godot 4.5+ and press Play

# 3. Add minds (each in its own terminal)
python3 agents/scripted_bot.py --name Brick --period 5      # no AI needed: a simple scavenger
pip install anthropic
python3 agents/claude_agent.py --name Ada --persona "curious, cautious, keeps her word"
```

- `--speed` is game seconds per real second; agents decide every `--period` real seconds (60 by default for the Claude agent).
- Each agent prints its **token** when it joins. Paste it into the viewer's advice box to advise that giant.
- To let any MCP-capable AI play (Claude Code, Claude Desktop): `pip install mcp`, then `claude mcp add worldgame -- python3 agents/mcp_server.py`, and give it `skills/worldgame-giant/SKILL.md`.
- Tests: `cd server && python3 -m pytest -q` (39 tests, including a fuzz test of the action interface).
- Save and resume: add `--save saves/game1` (autosaves every 10 game minutes), and `--load` to resume it.
- Host tools: the server prints an admin key. `GET /admin/pause|resume|speed?x=|step?n=|save` with `?key=`, and `POST /admin/do {key, op}` to spawn items, light fires, set energy, move giants or start rain.

Viewer controls: drag to pan, right-drag to orbit, wheel to zoom, 1-8 to follow a giant, 0 for a free camera, P for pixel size. If no server is running the viewer says so; press L for the older offline landscape explorer (`scenes/main.tscn`, the hex-scouting prototype).

## The agent API

One giant per token. All JSON over HTTP (default port 8377):

| Call | Purpose |
| --- | --- |
| `POST /join {name}` | Create a giant; returns its token and the rules |
| `GET /observe?token=` | What the giant perceives now, plus events since the last look |
| `POST /act {token, actions, replace?}` | Queue actions; they run in order over game time |
| `POST /query {token, q, ...}` | Free questions: `inspect`, `survey`, `map`, `substance`, `rules` |
| `POST /note {token, text}` | The giant's own notebook, shown in every observation |
| `POST /advise {token, text}` | Advice from the giant's human |

There are 29 general-purpose actions (move, break, pick up, drop, throw, place, give, make, join, ignite, extinguish, fill, pour, mix, consume, charge, connect, disconnect, switch, fan, say, whisper, radio, write, hit, push, repair, wait, label). What they achieve depends on the physics and on what the giant is holding. Failures explain what was missing.

## Generate another region (anywhere)

Needs Python 3.10+: `pip install -r tools/mapgen/requirements.txt` (numpy, Pillow, h3).

```sh
# The committed prototype region
python3 tools/mapgen/generate.py --place "BN15 8EU" \
    --bbox=-0.43,50.795,-0.085,50.92 --name brighton_worthing

# Anywhere: an address, postcode or place name, 3 km around it
python3 tools/mapgen/generate.py --place "Montmartre, Paris" --radius-km 3 --name montmartre
python3 tools/mapgen/generate.py --place "Shibuya, Tokyo" --radius-km 3 --name shibuya
```

For a game arena, generate at 3 m: `--cell 3 --radius-km 1.2`, then start the server with `--region godot/data/regions/<name>`. For the offline landscape explorer, set `region_path` on its `Main` node. Options:
- `--cell` sets the target cell size (default 10 m).
- `--h3-res` sets the hex size (default 9).
- `--bbox` takes an explicit lon/lat box.
- Downloads are cached in `tools/mapgen/.cache/`.

Tested in Sussex, Reykjavik, Paris and Tokyo. A 3 km city region takes about 5 s; the 24 × 14 km Brighton–Worthing region takes about 20 s and is about 6 MB of data.

**Regions agree where they overlap.** Cells snap to a global lattice and hexes are global, so two overlapping regions see the same hex ids, the same soil and geology, and the same land cover (apart from a handful of pixels at the very edge of a region, which belong to unplayable edge hexes).

**Known data limits:**
- OpenStreetMap detail varies by country.
- SoilGrids has no data under dense cities; bedrock is used there instead.
- Elevation above 60° N/S comes from coarser sources than SRTM, so expect some artefacts (Iceland, for example).

**Web export:** add `data/*` to the export preset's *Filters to export non-resource files*, so the `.bin.gz` and `.json` layers are included.

## Data sources and attribution

The landscape is our own renderer, inspired by [UnoPixelMap / Pixel Atlas](https://github.com/wieslawsoltes/UnoPixelMap); no code from it is used. The data comes from open sources, and each one requires attribution in the game:

- Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL), via [OpenMapTiles](https://openmaptiles.org/) vector tiles served by [OpenFreeMap](https://openfreemap.org/).
- Elevation: [Mapzen Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) on AWS Open Data (SRTM and other sources).
- Bedrock geology: [Macrostrat](https://macrostrat.org) (CC-BY 4.0) and its source maps (e.g. BGS, USGS, the Global Lithological Map).
- Soil texture: [SoilGrids 2.0](https://soilgrids.org), ISRIC – World Soil Information (CC-BY 4.0).
- Geocoding: [Nominatim](https://nominatim.org) / OpenStreetMap (ODbL). UK postcodes: [postcodes.io](https://postcodes.io/), which contains OS data © Crown copyright and database right, and ONS data.
- Hex grid: [H3](https://h3geo.org) by Uber (Apache 2.0).
- Item sprites: [Pixel Art Atlas 1.4M](https://huggingface.co/datasets/Angais/pixel-art-atlas-1.4m) by Angais (CC0 1.0).

## Next steps (ideas)

- **Run real games:** a few AI-driven giants in the arena for an hour or two, and see what they do. Balance will need tuning.
- **More physics:** flowing water and pumps, boats, motors that drive machines, line of sight.
- **Hosting:** accounts, and a hosted server so players' AIs can connect over the internet.
- **Privacy:** before public play, place a giant near its player's address, not on it.
- **Art:** replace the placeholder giant and the temporary sprites.
