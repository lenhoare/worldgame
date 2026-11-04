class_name DepositGenerator
extends RefCounted
## Deterministic resource deposits per hex.
##
## The same hex always produces the same deposits: the random stream is seeded
## from a secret world seed plus the hex coordinates, and the weights come from
## the real landscape (land cover, buildings, height) and real sites (fuel
## stations, hospitals, the airport...). Nothing is stored until a hex is
## scouted; WorldState then freezes what was found.
##
## In multiplayer this runs on the server only, so the seed never reaches
## players and the resource map can't be extracted from the client.

const WORLD_SEED := "worldgame-dev-seed-1"  ## server secret once multiplayer exists
const MAX_PER_TYPE := 2

## Land/salvage resources: which classes count towards the weight, how much
## weight makes one deposit on average, and where deposits may be placed.
const RULES := {
	"timber": {"per_deposit": 220.0, "place": ["wood"]},
	"biomass": {"per_deposit": 450.0, "place": ["grass", "park", "scrub", "farmland", "golf", "wetland"]},
	"water": {"per_deposit": 60.0, "place": ["water", "wetland"]},
	"stone": {"per_deposit": 380.0, "place": ["grass", "scrub", "farmland", "bare"]},
	"clay": {"per_deposit": 160.0, "place": ["wetland", "grass", "farmland", "park"]},
	"sand": {"per_deposit": 70.0, "place": ["beach"]},
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
var hex_size: float
var _sites_by_hex := {}


func _init(r: RegionData, size: float) -> void:
	region = r
	hex_size = size
	for s in r.sites:
		var a := Hex.world_to_axial(float(s.x), float(s.z), hex_size)
		if not _sites_by_hex.has(a):
			_sites_by_hex[a] = []
		_sites_by_hex[a].append(s)


func sites_in(axial: Vector2i) -> Array:
	return _sites_by_hex.get(axial, [])


## Weights in "cell equivalents" for each land/salvage resource.
func _weights(s: Dictionary) -> Dictionary:
	var c: Dictionary = s.counts_by_name
	var vol: float = s.building_volume
	return {
		"timber": c.wood,
		"biomass": c.grass + c.park + c.scrub + c.farmland + c.golf + c.wetland,
		"water": c.water + c.wetland,
		"stone": s.high_natural + c.bare * 3.0,
		"clay": s.low_natural * 0.6 + c.wetland * 2.0 + c.water * 0.5,
		"sand": c.beach * 2.0,
		"steel": vol / 10.0 + c.industrial * 2.0 + c.rail * 2.0 + c.runway,
		"copper": vol / 22.0 + c.commercial + c.industrial * 0.5,
		"concrete": s.building_cells * 0.6 + c.road_major * 0.5 + c.runway,
		"glass": vol / 18.0 + c.commercial,
		"plastics": c.urban * 0.25 + c.commercial * 1.5 + s.building_cells * 0.2,
		"electronics": vol / 35.0 + c.commercial * 1.2,
	}


func generate(axial: Vector2i) -> Array:
	var survey := region.survey_hex(axial, hex_size)
	if survey.cells == 0:
		return []
	var rng := RandomNumberGenerator.new()
	rng.seed = ("%s:%d:%d" % [WORLD_SEED, axial.x, axial.y]).hash()
	var deposits := []

	var weights := _weights(survey)
	for type in RULES:  # fixed key order keeps the random stream deterministic
		var w: float = weights[type]
		var rule: Dictionary = RULES[type]
		var expected := w / float(rule.per_deposit)
		var n := mini(MAX_PER_TYPE, int(floor(expected + rng.randf())))
		for i in n:
			var cell := _pick_cell(survey, rule.place, rng)
			if cell < 0:
				break
			var amount := int(round(clampf(w / maxf(1.0, n) * 0.8, 20.0, 900.0) * rng.randf_range(0.6, 1.4)))
			deposits.append(_deposit(type, amount, cell, ""))

	for site in sites_in(axial):
		for y in SITE_YIELDS.get(site.kind, []):
			if rng.randf() <= float(y[3]):
				var cell := region.cell_index_at(float(site.x), float(site.z))
				deposits.append(_deposit(y[0], rng.randi_range(y[1], y[2]), cell, String(site.name)))
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


func _deposit(type: String, amount: int, cell: int, site: String) -> Dictionary:
	var cs := region.cell_size
	var d := {
		"type": type,
		"amount": amount,
		"x": (cell % region.width + 0.5) * cs,
		"z": (cell / region.width + 0.5) * cs,
	}
	if site != "":
		d["site"] = site
	return d
