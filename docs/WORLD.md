# How the world works

Design notes for the simulation in `server/worldgame/`. The aim is a world rich enough that agents discover things nobody planned, so nothing here is a recipe list: there are substances with physical properties, and a handful of generic processes that act on them.

## Scale and time

- One voxel is about 3.1 m on a side. A giant is 4 voxels (12 m) tall, reaches 2 voxels sideways, 4 up and 2 down, and carries 20 t.
- One tick is one second of game time. A game day is 7,200 ticks (2 hours at 1x speed). Electricity runs 30x faster than the rest, so power systems matter within a short game.
- Agents decide about once a minute. They queue actions; the server executes them between decisions.
- The arena is a generated region (`lancing_arena`: 773 x 773 x 33 voxels, 2.4 km square). The same region and seed always build the same world.

## Substances and voxels (`materials.py`)

38 substances, each with density, hardness, melting point, flammability, fuel energy, flags (granular, liquid, conducts, ductile metal, brittle, fibrous, transparent, organic, stone, mouldable) and an optional heat transformation (clay to ceramic at 950 C, chalk to lime at 900 C, sand to glass at 1500 C, or 1100 C with ash or lime as a flux).

A voxel material is a substance arranged as a structure: fill (a brick wall is 20% brick), hardness, work time, **span** (how far it can overhang), flammability, and what it breaks into. Building interiors hold deterministic salvage, rolled from the voxel's position.

## Items (`items.py`)

- **Bulk:** a divisible mass of one substance (3.2 t of brick).
- **Salvage:** 35 kinds of object with a function or contents (car, generator, solar array, charger, cable drum, fuel can, gas cylinder, sensor...). Objects break down into parts.
- **Shaped parts:** any suitable substance can be made into one of 18 forms (blade, pick, hammer, shovel, rod, beam, plank, plate, sheet, wire, pipe, vessel, wheel, brick, block, rope, lens, mirror). Whether it can depends on properties: brittle hard stone is knapped, wood is carved with something harder than wood, metal must be hot (forge at 60% of melting point, cast when molten), clay must be wet.
- **Assemblies:** parts joined with rope, wire or a welding flame. A head plus a handle is a tool; wheels plus a bed plus an axle is a cart; a sheet between two boards is a bellows.

What an item can do is computed from its form and substance (`affordances`): a flint blade cuts at 5.6, lashed to a handle 8.05; a steel wheel carries 40 kg per kg of wheel.

## Processes (`physics.py`, `sim.py`)

| Process | Rule |
| --- | --- |
| Gravity | Loose material falls into gaps (cave-ins); items fall or float. |
| Structure | A voxel needs a vertical path to ground, or a sideways one no longer than its span. Otherwise it collapses into rubble and salvage and injures giants beneath. Roofs and interiors give way under a giant. |
| Fire | Spreads by flammability, dryness, wind and height; needs air; rain and water put it out. Temperature depends on fuel (wood 800 C, charcoal 1100 C), enclosure (+250 C with four non-flammable walls) and forced air (+350 C). Heat transforms voxels and items. Wood burning with no air becomes charcoal. |
| Explosion | Fuel, gas and big batteries explode when heated: they destroy by hardness and distance, ignite, injure and chain. |
| Water | Floods any opening at or below the level of the body it touches (the sea, a river). |
| Electricity | Wired components form networks: solar arrays and generators supply, batteries buffer, chargers, heaters, blowers, igniters, sirens and sensors consume. |
| Triggers | A device wired to a trigger runs only while the trigger is active: a switch, a timer, a pressure plate, a motion sensor, or a radio receiver that listens for a code word. |
| Doors | A motor under a doorway lifts the wall above it while powered and lowers it when not. |
| Throwing | Range falls with mass (20 kg goes 40 voxels, 20 t goes 4). Thrown things hurt, brittle things shatter, and liquids spill: spilled fuel burns on any surface. |
| Storage | Anything with capacity (a skip, a tank, a shipping container) holds items by volume and can be carried full. |
| Energy | Everything a giant does costs kWh. Refill by burning fuel in its reactor, drawing from batteries, or standing by a powered charger. At zero it is dormant until someone helps. |
| Growth and weather | Bare soil greens over; wind shifts; rain comes and goes; day and night change solar power and sight. |

## Things that follow without being programmed

None of these has dedicated code; each falls out of the rules above:

- A flint axe: knap beach flint, snap a branch, twist leaf fibre into rope, lash them. It cuts steel-framed sheds that bare hands cannot. (Played through in testing.)
- Charcoal: light a wood pile, then bank earth round it and cap it.
- A kiln or furnace: a pit with a charcoal fire; clay vessels fire, chalk burns to lime, and with bellows steel melts.
- Mortar: lime, sand and water. Mortared walls span further than dry-stacked ones.
- Felling: cut the bottom of a trunk and the rest comes down as logs.
- Demolition: undermine a wall, burn a block, or put a gas cylinder in a doorway.
- Moats and canals: dig below sea level to the shore.
- Bridges: timber spans three voxels, steel six.
- A charging station: solar arrays wired to a salvaged charger; cut the cable to sabotage it.
- Alarms: a powered sensor tells its owner who came near; wire a siren to it and everyone hears.
- Traps: a pressure plate wired to an igniter beside a gas cylinder. (Tested.)
- Remote and delayed action: a timer or a radio code word can light a fire or sound a siren from far away. (Tested.)
- Firebombs: throw a can of fuel, then throw something burning. (Tested.)
- Haulage: fill a skip with bricks and carry the skip.
- A password gate: a motor door wired to a radio receiver opens when someone transmits the code word. (Tested.)
- Rescue or ransom: a dormant giant can only speak; another can give it energy, or not.

## What agents see (`observe.py`)

A JSON observation of about 4,000 characters: the giant's state, a 25 x 25 text map with a matching height map, nearby items (the nearest few of each kind, the rest counted), giants in sight with what they carry and last said, landmarks with real names, fire, writing, events since the last look, advice from the human, and the giant's own notes. Free queries: inspect, survey, map, substance.

Giants perceive only what is near them. Speech carries 100 voxels; whispers are private; radios reach other radios.

## Known gaps

- **Robustness:** a fuzz test fires random actions from four giants at the real arena (14 runs of 6,000 ticks pass). It found one real bug, now fixed.
- **Not yet tested with real language models.** The agent loop was exercised by a scripted bot and by hand; `agents/claude_agent.py` compiles and its API parameters were checked against the SDK, but it has not been run against the API.
- Balance (energy costs, loot rates, break times) is a first guess.
- Water does not drain or flow downhill; it only floods. Rivers are static.
- No boats or pumps yet; motors only drive doors; no line-of-sight (sight is by distance).
- One arena per server. Games can be saved and resumed (`--save`, `--load`).
- The server has no accounts: a giant's token is its only credential. Admin endpoints need the key printed at start-up. Bind to localhost (the default) unless you trust the network.
