extends SceneTree
## Headless checks for the deposit generator and saved world state.
## Run: godot --headless --path godot --script res://tests/test_deposits.gd

const REGION := "res://data/regions/brighton_worthing"

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

	var gen := DepositGenerator.new(region, 250.0)
	var home := Hex.world_to_axial(float(region.meta.home.x), float(region.meta.home.z), 250.0)
	var a := gen.generate(home)
	var b := DepositGenerator.new(region, 250.0).generate(home)
	check(a.size() > 0, "home hex has deposits (%d)" % a.size())
	check(JSON.stringify(a) == JSON.stringify(b), "same hex -> same deposits (deterministic)")
	check(JSON.stringify(a) != JSON.stringify(gen.generate(home + Vector2i(1, 0))), "neighbour differs")

	var types := {}
	for q in range(-6, 7):
		for r in range(-6, 7):
			for d in gen.generate(home + Vector2i(q, r)):
				types[d.type] = true
				if not ResourceTypes.INFO.has(d.type):
					check(false, "unknown resource type %s" % d.type)
	check(types.size() >= 12, "variety near home: %s" % ", ".join(types.keys()))

	# Airport hex should hold rare tech from the real airfield site.
	for s in region.sites:
		if s.kind == "airfield" and String(s.name).contains("Brighton City"):
			var ax := Hex.world_to_axial(float(s.x), float(s.z), 250.0)
			var found := gen.generate(ax).any(func(d): return d.type == "rare_tech")
			check(found, "Brighton City Airport hex has rare tech")

	# Once seen, fixed: a save/load round trip keeps deposits and claims.
	var st := WorldState.new("test_region")
	st.reset()
	st.home = home
	st.has_home = true
	st.record_scout(home, a)
	st.record_scout(home + Vector2i(1, 0), gen.generate(home + Vector2i(1, 0)))
	st.claimed.append(home + Vector2i(1, 0))
	st.save()
	var st2 := WorldState.new("test_region")
	check(st2.load_save(), "save loads")
	check(st2.scouted.size() == 2 and st2.claimed == st.claimed, "scouted & claimed survive")
	check(int(st2.deposits(home)[0].amount) == int(a[0].amount), "deposit amounts survive")
	check(st2.is_frontier(home + Vector2i(0, 1)) and not st2.is_frontier(home + Vector2i(5, 5)), "frontier logic")
	st2.reset()

	print("FAILED %d" % failures if failures else "ALL PASSED")
	quit(1 if failures else 0)
