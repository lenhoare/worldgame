extends SceneTree
## Headless checks for the deposit generator and saved world state.
## Run: godot --headless --path godot --script res://tests/test_deposits.gd

const REGION := "res://data/regions/brighton_worthing"
const SAVE := "user://test_save.json"

var failures := 0


func check(cond: bool, msg: String) -> void:
	if cond:
		print("  ok   ", msg)
	else:
		print("  FAIL ", msg)
		failures += 1


func _init() -> void:
	var region := RegionData.load_region(REGION)
	check(region != null, "region loads")
	check(region.sites.size() > 100, "real sites loaded (%d)" % region.sites.size())
	check(region.hex_count() > 1000 and region.hex_resolution == 9, "H3 res 9 hex table (%d hexes)" % region.hex_count())

	# Home hex: the generator's H3 id matches the hex under the home position.
	var home_id := String(region.meta.home.hex)
	var home := region.hex_index(home_id)
	check(home >= 0 and region.hex_at(float(region.meta.home.x), float(region.meta.home.z)) == home,
		"home position lies in home hex %s" % home_id)
	check(region.hex_neighbour_ids(home_id).size() == 6, "home hex has 6 neighbours")
	var c := region.hex_centre(home)
	check(region.hex_at(c.x, c.y) == home, "hex centre lies inside its hex")
	var ll := region.world_to_lonlat(c.x, c.y)
	var back := region.lonlat_to_world(ll.x, ll.y)
	check(back.distance_to(c) < 1.0, "lon/lat round trip within 1 m (Vector2 is 32-bit)")

	var gen := DepositGenerator.new(region)
	var a := gen.generate(home)
	var b := DepositGenerator.new(region).generate(home)
	check(a.size() > 0, "home hex has deposits (%d)" % a.size())
	check(JSON.stringify(a) == JSON.stringify(b), "same hex -> same deposits (deterministic)")
	var n0 := region.hex_index(region.hex_neighbour_ids(home_id)[0])
	check(JSON.stringify(a) != JSON.stringify(gen.generate(n0)), "neighbour differs")
	check(a.all(func(d): return d.has("lat") and d.has("lon")), "deposits carry lat/lon")

	# Geology: chalk downland should yield stone, noted as chalk.
	var types := {}
	var chalk_stone := false
	for i in range(0, region.hex_count(), 7):
		if not region.hex_complete(i):
			continue
		for d in gen.generate(i):
			types[d.type] = true
			if not ResourceTypes.INFO.has(d.type):
				check(false, "unknown resource type %s" % d.type)
			if d.type == "stone" and String(d.get("note", "")).contains("chalk"):
				chalk_stone = true
	check(types.size() == ResourceTypes.ORDER.size(), "all %d resource types occur: %s" % [types.size(), ", ".join(types.keys())])
	check(chalk_stone, "chalk downland yields stone (chalk)")

	# Airport hex should hold rare tech from the real airfield site.
	for s in region.sites:
		if s.kind == "airfield" and String(s.name).contains("Brighton City"):
			var idx := region.hex_at(float(s.x), float(s.z))
			check(gen.generate(idx).any(func(d): return d.type == "rare_tech"), "Brighton City Airport hex has rare tech")

	# Once seen, fixed: a save/load round trip keeps deposits and claims.
	var st := WorldState.new(region.hex_neighbour_ids)
	st.reset(SAVE)
	st.home = home_id
	st.record_scout(home_id, a)
	var nid := region.hex_ids[n0]
	st.record_scout(nid, gen.generate(n0))
	st.claimed.append(nid)
	st.save(SAVE)
	var st2 := WorldState.new(region.hex_neighbour_ids)
	check(st2.load_save(SAVE), "save loads")
	check(st2.home == home_id and st2.scouted.size() == 2 and st2.claimed == st.claimed, "home, scouted & claimed survive")
	check(int(st2.deposits(home_id)[0].amount) == int(a[0].amount), "deposit amounts survive")
	var far := ""
	for i in region.hex_count():
		if region.hex_centre(i).distance_to(c) > 3000.0:
			far = region.hex_ids[i]
			break
	check(st2.is_frontier(region.hex_neighbour_ids(home_id)[1]) and not st2.is_frontier(far), "frontier logic")
	st2.reset(SAVE)

	print("FAILED %d" % failures if failures else "ALL PASSED")
	quit(1 if failures else 0)
