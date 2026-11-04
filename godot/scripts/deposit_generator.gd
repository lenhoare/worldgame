class_name DepositGenerator
extends RefCounted
## Deterministic resource deposits per hex, anywhere in the world.
##
## The random stream is seeded from a secret world seed plus the hex's global
## H3 id, and the weights come from the real landscape: land cover, building
## volume, bedrock geology (Macrostrat), soil texture (SoilGrids) and real
## sites (fuel stations, hospitals, airfields...). So a hex produces the same
## deposits in every region that contains it. Nothing is stored until a hex
## is scouted; WorldState then freezes what was found.
##
## In multiplayer this runs on the server only, so the seed never reaches
## players and the resource map can't be extracted from the client.

const WORLD_SEED := "worldgame-dev-seed-1"  ## server secret once multiplayer exists
const MAX_PER_TYPE := 2

## How hard/quarryable each rock class is: stone weight per natural cell.
const ROCK_STONE := {
	"unknown": 0.25, "carbonate": 0.5, "sandstone": 0.45, "mudstone": 0.1,
	"sediment": 0.12, "igneous": 0.7, "metamorphic": 0.6,
}

## Land/salvage resources: how much weight makes one deposit on average, and
## where deposits may be placed.
const RULES := {
	"timber": {"per_deposit": 220.0, "place": ["wood"]},
	"biomass": {"per_deposit": 450.0, "place": ["grass", "park", "scrub", "farmland", "golf", "wetland"]},
	"water": {"per_deposit": 60.0, "place": ["water", "wetland"]},
	"stone": {"per_deposit": 380.0, "place": ["grass", "scrub", "farmland", "bare", "wood"]},
	"clay": {"per_deposit": 220.0, "place": ["wetland", "grass", "farmland", "park", "scrub"]},
	"sand": {"per_deposit": 90.0, "place": ["beach", "grass", "scrub", "farmland"]},
	"steel": {"per_deposit": 260.0, "place": ["building", "industrial", "rail"]},
	"copper": {"per_deposit": 300.0, "place": ["building", "commercial", "industrial"]},
	"concrete": {"per_deposit": 320.0, "place": ["building", "road_major", "runway"]},
	"glass": {"per_deposit": 300.0, "place": ["building", "commercial"]},
	"plastics": {"per_deposit": 280.0, "place": ["building", "commercial", "urban"]},
	"electronics": {"per_deposit": 340.0, "place": ["building", "commercial"]},
}

## Real sites -> special deposits: [type, min, max, chance].
const SITE_YIELDS := {
	"fuel_station": [["fuel", 300, 650, 1.0], ["steel", 30, 80, 0.6]],
	"charging_station": [["power_cells", 120, 280, 1.0], ["copper", 30, 90, 0.7]],
	"car_park": [["power_cells", 15, 60, 0.35], ["steel", 30, 90, 0.5]],
	"garage": [["fuel", 30, 90, 0.7], ["steel", 40, 110, 0.8], ["power_cells", 20, 60, 0.4]],
	"recycling": [["plastics", 40, 120, 0.8], ["glass", 30, 90, 0.6]],
	"hospital": [["rare_tech", 80, 220, 1.0], ["electronics", 60, 160, 0.9], ["power_cells", 40, 100, 0.6]],
	"college": [["electronics", 80, 200, 0.9], ["rare_tech", 30, 90, 0.5]],
	"station": [["steel", 150, 320, 1.0], ["electronics", 40, 120, 0.7], ["copper", 60, 150, 0.8]],
	"airfield": [["rare_tech", 200, 500, 1.0], ["fuel", 200, 600, 0.9], ["steel", 100, 300, 0.8]],
}

var region: RegionData
var _sites_by_hex := {}


func _init(r: RegionData) -> void:
	region = r
	for s in r.sites:
		var idx := r.hex_at(float(s.x), float(s.z))
		if idx >= 0:
			if not _sites_by_hex.has(idx):
				_sites_by_hex[idx] = []
			_sites_by_hex[idx].append(s)


func sites_in(idx: int) -> Array:
	return _sites_by_hex.get(idx, [])


## Weights in "cell equivalents" for each land/salvage resource.
func _weights(s: Dictionary) -> Dictionary:
	var c: Dictionary = s.counts_by_name
	var rock: Dictionary = s.natural_by_rock
	var natural := 0.0
	var stone: float = c.bare * 3.0
	for r in rock:
		natural += rock[r]
		stone += rock[r] * float(ROCK_STONE.get(r, 0.25))
	var clay: float = c.wetland * 2.0 + c.water * 0.5 + rock.mudstone * 0.3
	var sand: float = c.beach * 2.0 + rock.sandstone * 0.15 + rock.sediment * 0.1
	if s.clay_pct >= 0.0:  # SoilGrids available
		clay += natural * float(s.clay_pct) / 100.0
		sand += natural * maxf(0.0, float(s.sand_pct) - 30.0) / 100.0
	else:  # no soil data: loose sediments stand in
		clay += rock.sediment * 0.25
	var vol: float = s.building_volume
	return {
		"timber": c.wood,
		"biomass": c.grass + c.park + c.scrub + c.farmland + c.golf + c.wetland,
		"water": c.water + c.wetland,
		"stone": stone,
		"clay": clay,
		"sand": sand,
		"steel": vol / 10.0 + c.industrial * 2.0 + c.rail * 2.0 + c.runway,
		"copper": vol / 22.0 + c.commercial + c.industrial * 0.5,
		"concrete": s.building_cells * 0.6 + c.road_major * 0.5 + c.runway,
		"glass": vol / 18.0 + c.commercial,
		"plastics": c.urban * 0.25 + c.commercial * 1.5 + s.building_cells * 0.2,
		"electronics": vol / 35.0 + c.commercial * 1.2,
	}


func generate(idx: int) -> Array:
	var survey := region.survey_hex(idx)
	if survey.cells == 0:
		return []
	var rng := RandomNumberGenerator.new()
	rng.seed = ("%s:%s" % [WORLD_SEED, region.hex_ids[idx]]).hash()
	var deposits := []
	var bedrock: Dictionary = survey.bedrock

	var weights := _weights(survey)
	for type in RULES:  # fixed key order keeps the random stream deterministic
		var w: float = weights[type]
		var rule: Dictionary = RULES[type]
		var n := mini(MAX_PER_TYPE, int(floor(w / float(rule.per_deposit) + rng.randf())))
		for i in n:
			var cell := _pick_cell(survey, rule.place, rng)
			if cell < 0:
				break
			var amount := int(round(clampf(w / maxf(1.0, n) * 0.8, 20.0, 900.0) * rng.randf_range(0.6, 1.4)))
			var note := ""
			if type in ["stone", "clay", "sand"] and String(bedrock.name) != "":
				note = String(bedrock.lith if type == "stone" else bedrock.name)
			deposits.append(_deposit(type, amount, cell, "", note))

	for site in sites_in(idx):
		for y in SITE_YIELDS.get(site.kind, []):
			if rng.randf() <= float(y[3]):
				var cell := region.cell_index_at(float(site.x), float(site.z))
				deposits.append(_deposit(y[0], rng.randi_range(y[1], y[2]), cell, String(site.name), ""))
	return deposits


func _pick_cell(survey: Dictionary, classes: Array, rng: RandomNumberGenerator) -> int:
	var pools := []
	var total := 0
	for name in classes:
		var pool: PackedInt32Array = survey.cells_by_name.get(name, PackedInt32Array())
		if pool.size() > 0:
			pools.append(pool)
			total += pool.size()
	if total == 0:
		return -1
	var k := rng.randi_range(0, total - 1)
	for pool in pools:
		if k < pool.size():
			return pool[k]
		k -= pool.size()
	return -1


## Deposits store latitude/longitude, so they stay valid in any region.
func _deposit(type: String, amount: int, cell: int, site: String, note: String) -> Dictionary:
	var cs := region.cell_size
	var ll := region.world_to_lonlat((cell % region.width + 0.5) * cs, (cell / region.width + 0.5) * cs)
	var d := {
		"type": type,
		"amount": amount,
		"lat": snappedf(ll.y, 0.000001),
		"lon": snappedf(ll.x, 0.000001),
	}
	if site != "":
		d["site"] = site
	if note != "":
		d["note"] = note
	return d
