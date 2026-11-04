extends Node
## WorldGame landscape prototype: loads a generated region, builds the pixel-art
## world inside a low-resolution SubViewport, and lets you scout hexes for
## resources and claim territory around your home.

const HEX_SIZE := 250.0
const PIXEL_SIZES := [1, 2, 3, 4]
const NO_HEX := Vector2i(1 << 20, 0)
enum HexState { UNKNOWN, FRONTIER, SCOUTED, CLAIMED, HOME }

@export var region_path := "res://data/regions/brighton_worthing"
@export var pixel_size := 2

var region: RegionData
var container: SubViewportContainer
var viewport: SubViewport
var world: Node3D
var terrain: Terrain
var rig: CameraRig
var sun: DirectionalLight3D
var beyond: MeshInstance3D

var title_label: Label
var info_label: Label
var help_label: Label
var loading_panel: PanelContainer
var loading_label: Label
var loading_bar: ProgressBar

var state: WorldState
var deposits: DepositGenerator
var markers: DepositMarkers
var giant: Giant
var hex_state_image: Image
var hex_state_texture: ImageTexture
var hex_origin := Vector2i.ZERO

var home_axial := NO_HEX
var hover_axial := NO_HEX
var show_hex := true
var show_buildings := true
var _survey_cache := {}
var _drag_button := -1
var _drag_moved := 0.0
var _mouse := Vector2.ZERO
var _pick_dirty := false
var _mouse_seen := false
var _ready_to_play := false
var _toast := ""
var _toast_until := 0.0


func _ready() -> void:
	_build_viewport()
	_build_environment()
	_build_ui()
	await get_tree().process_frame

	loading_label.text = "Loading region…"
	await get_tree().process_frame
	region = RegionData.load_region(region_path)
	if region == null:
		loading_label.text = "Could not load region at %s.\nRun tools/mapgen/generate.py first." % region_path
		return

	terrain = Terrain.new()
	terrain.name = "Terrain"
	world.add_child(terrain)
	terrain.progress.connect(_on_build_progress)
	terrain.region = region
	_setup_camera()
	_setup_home()
	await terrain.build(region)

	deposits = DepositGenerator.new(region, HEX_SIZE)
	markers = DepositMarkers.new()
	markers.name = "DepositMarkers"
	world.add_child(markers)
	_setup_hex_state()
	state = WorldState.new(String(region.meta.name))
	state.home = home_axial
	state.has_home = home_axial != NO_HEX
	if "--reset" in OS.get_cmdline_user_args():
		state.reset()
	if not state.load_save() or state.scouted.is_empty():
		_start_new_game()

	loading_panel.visible = false
	_ready_to_play = true
	_refresh_world()
	await _run_command_line()


## A new player has scouted their home hex and its six neighbours.
func _start_new_game() -> void:
	if not state.has_home:
		return
	_scout(home_axial, false)
	for d in WorldState.NEIGHBOURS:
		_scout(home_axial + d, false)
	state.save()


## Dev helpers: `godot -- --view=x,z,yaw_deg,pitch_deg,distance --screenshot=out.png`
## Also: --giant-view=yaw,pitch,dist  --scout-radius=N  --hover=px,py  --reset
func _run_command_line() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	if args.has("view"):
		var v := String(args.view).split_floats(",")
		rig.set_focus(Vector2(v[0], v[1]))
		rig.yaw = deg_to_rad(v[2])
		rig.pitch = deg_to_rad(v[3])
		rig.distance = v[4]
		rig.snap()
	if args.has("giant-view") and giant:  # dev: yaw_deg,pitch_deg,distance around the giant
		var g := String(args["giant-view"]).split_floats(",")
		rig.set_focus(Vector2(giant.position.x, giant.position.z))
		rig.yaw = deg_to_rad(g[0])
		rig.pitch = deg_to_rad(g[1])
		rig.distance = g[2]
		rig.snap()
	if args.has("scout-radius"):  # dev: reveal everything within N hexes of home
		var n := int(args["scout-radius"])
		for q in range(-n, n + 1):
			for r in range(maxi(-n, -q - n), mini(n, -q + n) + 1):
				_scout(home_axial + Vector2i(q, r), false)
		_refresh_world()
	if args.has("hover"):
		var h := String(args.hover).split_floats(",")
		_mouse = Vector2(h[0], h[1])
		_mouse_seen = true
		_update_hover()
	if args.has("screenshot"):
		for i in 10:
			await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		img.save_png(String(args.screenshot))
		print("Saved screenshot to ", args.screenshot)
		get_tree().quit()


# --- Scene setup -----------------------------------------------------------
func _build_viewport() -> void:
	container = SubViewportContainer.new()
	container.stretch = true
	container.stretch_shrink = pixel_size
	container.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	container.set_anchors_preset(Control.PRESET_FULL_RECT)
	container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(container)
	viewport = SubViewport.new()
	viewport.msaa_3d = Viewport.MSAA_DISABLED
	viewport.positional_shadow_atlas_size = 0
	container.add_child(viewport)
	world = Node3D.new()
	world.name = "World"
	viewport.add_child(world)


func _build_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color("#6fa7c9")
	sky_mat.sky_horizon_color = Color("#cfe0e3")
	sky_mat.ground_horizon_color = Color("#cfe0e3")
	sky_mat.ground_bottom_color = Color("#2c4a55")
	var sky := Sky.new()
	sky.sky_material = sky_mat
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("#b9c8d0")
	env.ambient_light_energy = 0.38
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	env.fog_enabled = true
	env.fog_light_color = Color("#c9dbe0")
	env.fog_mode = Environment.FOG_MODE_DEPTH
	env.fog_density = 0.55
	env.fog_depth_begin = 6000.0
	env.fog_depth_end = 32000.0
	env.fog_depth_curve = 1.6
	env.fog_sky_affect = 0.0
	var we := WorldEnvironment.new()
	we.environment = env
	world.add_child(we)

	sun = DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-40.0), deg_to_rad(-30.0), 0.0)  # from the south-west
	sun.light_energy = 1.5
	sun.light_color = Color("#fff4e0")
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	sun.directional_shadow_max_distance = 3500.0
	world.add_child(sun)

	# Unexplored world beyond the region edges.
	beyond = MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(200000, 200000)
	beyond.mesh = plane
	beyond.position = Vector3(0, -2.0, 0)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color("#9fb8bf")
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	beyond.material_override = mat
	world.add_child(beyond)


func _setup_camera() -> void:
	rig = CameraRig.new()
	rig.name = "CameraRig"
	world.add_child(rig)
	var size := region.world_size()
	rig.bounds = Rect2(Vector2.ZERO, size)
	beyond.position = Vector3(size.x * 0.5, -2.0, size.y * 0.5)
	rig.ground_height = func(x: float, z: float) -> float: return terrain.world_height(x, z)
	var home = region.meta.get("home")
	if home:
		rig.set_focus(Vector2(home.x, float(home.z) - 2500.0))
	else:
		rig.set_focus(size * 0.5)
	rig.distance = 7000.0
	rig.snap()


func _setup_home() -> void:
	var home = region.meta.get("home")
	if not home:
		return
	var x := float(home.x)
	var z := float(home.z)
	home_axial = Hex.world_to_axial(x, z, HEX_SIZE)
	var beacon := MeshInstance3D.new()
	var cyl := CylinderMesh.new()
	cyl.top_radius = 2.0
	cyl.bottom_radius = 2.0
	cyl.height = 160.0
	cyl.radial_segments = 6
	beacon.mesh = cyl
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color("#ffd04a")
	beacon.material_override = mat
	beacon.position = Vector3(x, terrain.world_height(x, z) + 100.0, z)  # floats above the postcode
	beacon.name = "HomeBeacon"
	world.add_child(beacon)

	# The player's first giant stands at the centre of the home hex.
	var c := _open_ground_near(Hex.axial_to_world(home_axial, HEX_SIZE))
	giant = Giant.new()
	giant.name = "Giant"
	giant.position = Vector3(c.x, terrain.world_height(c.x, c.y), c.y)
	world.add_child(giant)


## Nearest cell centre to `p` with no building or water, searching outwards.
func _open_ground_near(p: Vector2) -> Vector2:
	var blocked := [region.class_ids.sea, region.class_ids.water, region.class_ids.building]
	var c0 := region.cell_at(p.x, p.y)
	for radius in 30:
		for dz in range(-radius, radius + 1):
			for dx in range(-radius, radius + 1):
				if maxi(absi(dx), absi(dz)) != radius:
					continue
				var c := Vector2i(clampi(c0.x + dx, 0, region.width - 1), clampi(c0.y + dz, 0, region.height - 1))
				if region.building_height_at(c) == 0 and not blocked.has(region.class_at(c)):
					return (Vector2(c) + Vector2(0.5, 0.5)) * region.cell_size
	return p


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.07, 0.15, 0.17, 0.86)
	style.set_corner_radius_all(6)
	style.set_content_margin_all(10)

	var title_panel := _panel(layer, style, Control.PRESET_TOP_LEFT)
	title_label = Label.new()
	title_label.text = "WORLDGAME"
	title_panel.add_child(title_label)

	var info_panel := _panel(layer, style, Control.PRESET_BOTTOM_LEFT)
	info_label = Label.new()
	info_label.text = "Move the mouse over the map."
	info_label.custom_minimum_size = Vector2(340, 0)
	info_panel.add_child(info_label)

	var help_panel := _panel(layer, style, Control.PRESET_BOTTOM_RIGHT)
	help_label = Label.new()
	help_label.text = "\n".join([
		"Left-drag / WASD  pan",
		"Right-drag / Q E  rotate & tilt",
		"Wheel / Z X  zoom",
		"Click faded hex  scout it",
		"Click scouted hex  claim / release",
		"Space  fly to your giant    H  hex grid",
		"B  buildings    P  pixel size    F8  new game",
	])
	help_label.add_theme_color_override("font_color", Color("#b8d0d4"))
	help_panel.add_child(help_label)

	loading_panel = _panel(layer, style, Control.PRESET_CENTER)
	var box := VBoxContainer.new()
	box.custom_minimum_size = Vector2(320, 0)
	loading_panel.add_child(box)
	loading_label = Label.new()
	loading_label.text = "Starting…"
	loading_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(loading_label)
	loading_bar = ProgressBar.new()
	loading_bar.show_percentage = false
	loading_bar.custom_minimum_size = Vector2(0, 10)
	box.add_child(loading_bar)


func _panel(layer: CanvasLayer, style: StyleBox, preset: int) -> PanelContainer:
	var p := PanelContainer.new()
	p.add_theme_stylebox_override("panel", style)
	p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(p)
	p.set_anchors_and_offsets_preset(preset, Control.PRESET_MODE_MINSIZE, 12)
	match preset:
		Control.PRESET_BOTTOM_LEFT:
			p.grow_vertical = Control.GROW_DIRECTION_BEGIN
		Control.PRESET_BOTTOM_RIGHT:
			p.grow_vertical = Control.GROW_DIRECTION_BEGIN
			p.grow_horizontal = Control.GROW_DIRECTION_BEGIN
		Control.PRESET_CENTER:
			p.grow_vertical = Control.GROW_DIRECTION_BOTH
			p.grow_horizontal = Control.GROW_DIRECTION_BOTH
	return p


func _on_build_progress(done: int, total: int) -> void:
	loading_label.text = "Generating landscape… chunk %d / %d" % [done, total]
	loading_bar.value = 100.0 * done / total


func _update_title() -> void:
	var lines := ["WORLDGAME · landscape prototype"]
	var home = region.meta.get("home")
	var nice_name := String(region.meta.name).replace("_", " ").capitalize()
	lines.append("%s · %.1f × %.1f km" % [nice_name, region.world_size().x / 1000.0, region.world_size().y / 1000.0])
	if home:
		lines.append("Home: %s" % home.postcode)
	lines.append("Scouted %d hexes · own %d" % [state.scouted.size(), state.claimed.size() + (1 if state.has_home else 0)])
	var totals := {}
	for a in state.scouted:
		for d in state.deposits(a):
			totals[d.type] = totals.get(d.type, 0) + int(d.amount)
	var parts := []
	for t in ResourceTypes.ORDER:
		if totals.has(t):
			parts.append("%s %d" % [ResourceTypes.display_name(t), totals[t]])
	if parts.size() > 0:
		lines.append("Known deposits:")
		for i in range(0, parts.size(), 3):
			lines.append("  " + "   ".join(parts.slice(i, i + 3)))
	title_label.text = "\n".join(lines)


# --- Input -----------------------------------------------------------------
func _unhandled_input(event: InputEvent) -> void:
	if not _ready_to_play:
		return
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		_mouse = mb.position
		if mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_UP:
			rig.zoom(0.85)
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			rig.zoom(1.0 / 0.85)
		elif mb.button_index in [MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT, MOUSE_BUTTON_MIDDLE]:
			if mb.pressed:
				_drag_button = mb.button_index
				_drag_moved = 0.0
			elif mb.button_index == _drag_button:
				if _drag_button == MOUSE_BUTTON_LEFT and _drag_moved < 6.0:
					_click_hex()
				_drag_button = -1
	elif event is InputEventMouseMotion:
		var mm := event as InputEventMouseMotion
		_mouse = mm.position
		_mouse_seen = true
		_pick_dirty = true
		if _drag_button != -1:
			_drag_moved += mm.relative.length()
			var orbit := _drag_button != MOUSE_BUTTON_LEFT or mm.shift_pressed
			if orbit:
				rig.orbit(mm.relative)
			else:
				rig.pan_pixels(mm.relative, get_viewport().get_visible_rect().size.y)
	elif event is InputEventKey and event.pressed and not event.echo:
		match (event as InputEventKey).keycode:
			KEY_H:
				show_hex = not show_hex
				_update_hex_uniforms()
			KEY_B:
				show_buildings = not show_buildings
				terrain.set_buildings_visible(show_buildings)
			KEY_P:
				pixel_size = PIXEL_SIZES[(PIXEL_SIZES.find(pixel_size) + 1) % PIXEL_SIZES.size()]
				container.stretch_shrink = pixel_size
			KEY_SPACE, KEY_HOME:
				if giant:
					rig.set_focus(Vector2(giant.position.x, giant.position.z))
					rig.distance = 240.0
					rig.pitch = deg_to_rad(24.0)
			KEY_F8:
				state.reset()
				_start_new_game()
				_refresh_world()
				_flash("New game: your home and its neighbours are scouted.")


func _process(delta: float) -> void:
	if not _ready_to_play:
		return
	var move := Vector2.ZERO
	if Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT):
		move.x -= 1
	if Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT):
		move.x += 1
	if Input.is_key_pressed(KEY_W) or Input.is_key_pressed(KEY_UP):
		move.y += 1
	if Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN):
		move.y -= 1
	if move != Vector2.ZERO:
		rig.pan_metres(move.normalized() * rig.distance * 0.9 * delta)
		_pick_dirty = true
	if Input.is_key_pressed(KEY_Q):
		rig.yaw += 1.4 * delta
		_pick_dirty = true
	if Input.is_key_pressed(KEY_E):
		rig.yaw -= 1.4 * delta
		_pick_dirty = true
	if Input.is_key_pressed(KEY_Z):
		rig.zoom(1.0 - 1.5 * delta)
	if Input.is_key_pressed(KEY_X):
		rig.zoom(1.0 + 1.5 * delta)
	markers.set_view_distance(rig.distance)
	if _toast != "" and Time.get_ticks_msec() / 1000.0 > _toast_until:
		_toast = ""
		_pick_dirty = true
	if _mouse_seen and (_pick_dirty or _drag_button != -1):
		_pick_dirty = false
		_update_hover()


# --- Picking & hexes -------------------------------------------------------
func _pick_ground(screen_pos: Vector2) -> Variant:
	var cam := rig.camera
	var vp_pos := screen_pos / float(pixel_size)
	var origin := cam.project_ray_origin(vp_pos)
	var dir := cam.project_ray_normal(vp_pos)
	var t := 0.0
	var step := maxf(region.cell_size, rig.distance * 0.004)
	var prev := 0.0
	for i in 800:
		var p := origin + dir * t
		if p.y <= terrain.world_height(p.x, p.z):
			var a := prev
			var b := t
			for j in 14:
				var m := (a + b) * 0.5
				var q := origin + dir * m
				if q.y <= terrain.world_height(q.x, q.z):
					b = m
				else:
					a = m
			return origin + dir * b
		if p.y < -5.0 and dir.y >= 0.0:
			break
		prev = t
		t += step
		step *= 1.012
		if t > 90000.0:
			break
	return null


func _update_hover() -> void:
	var hit = _pick_ground(_mouse)
	if hit == null or not region.contains(hit.x, hit.z):
		info_label.text = _with_toast(["Beyond the generated region."])
		_set_hover(NO_HEX)
		return
	var p: Vector3 = hit
	var cell := region.cell_at(p.x, p.z)
	var cls := region.class_at(cell)
	var bh := region.building_height_at(cell)
	var ll := region.world_to_lonlat(p.x, p.z)
	var axial := Hex.world_to_axial(p.x, p.z, HEX_SIZE)
	_set_hover(axial)
	var survey: Dictionary = _survey(axial)
	var top_names := []
	for t in survey.top:
		top_names.append("%s %d%%" % [region.class_name_of(t[1]), round(100.0 * t[0] / maxf(1, survey.cells))])
	var lines := [
		"%.5f, %.5f   elev %.0f m" % [ll.y, ll.x, region.height_at(p.x, p.z)],
		"Ground: %s%s" % [region.class_name_of(cls), ("  ·  building %d m" % bh) if bh > 0 else ""],
		"",
		"Hex %d,%d · %s" % [axial.x, axial.y, ", ".join(top_names)],
	]
	match _hex_state(axial):
		HexState.UNKNOWN:
			lines.append("Unscouted. Scout a neighbouring hex first.")
		HexState.FRONTIER:
			lines.append("Unscouted. Click to scout it.")
		_:
			var owner := "HOME" if axial == home_axial else ("yours · click to release" if state.claimed.has(axial) \
				else ("click to claim" if _can_claim(axial) else "not next to your land"))
			lines.append("Scouted %s · %s" % [_ago(float(state.scouted[axial].t)), owner])
			lines.append_array(_deposit_lines(state.deposits(axial)))
	info_label.text = _with_toast(lines)


func _deposit_lines(list: Array) -> Array:
	if list.is_empty():
		return ["Nothing worth salvaging here."]
	var totals := {}
	var counts := {}
	var sites := []
	for d in list:
		totals[d.type] = totals.get(d.type, 0) + int(d.amount)
		counts[d.type] = counts.get(d.type, 0) + 1
		if d.has("site") and d.site != "" and not sites.has(d.site):
			sites.append(d.site)
	var parts := []
	for t in ResourceTypes.ORDER:
		if totals.has(t):
			parts.append("%s %d%s" % [ResourceTypes.display_name(t), totals[t], (" ×%d" % counts[t]) if counts[t] > 1 else ""])
	var out := []
	for i in range(0, parts.size(), 3):
		out.append("   ".join(parts.slice(i, i + 3)))
	if sites.size() > 0:
		out.append("Sites: " + ", ".join(sites.slice(0, 3)))
	return out


func _ago(t: float) -> String:
	var s := Time.get_unix_time_from_system() - t
	if s < 60:
		return "just now"
	if s < 3600:
		return "%d min ago" % int(s / 60)
	if s < 86400:
		return "%d h ago" % int(s / 3600)
	return "%d days ago" % int(s / 86400)


func _with_toast(lines: Array) -> String:
	if _toast != "":
		lines = [">> " + _toast, ""] + lines
	return "\n".join(lines)


func _flash(msg: String) -> void:
	_toast = msg
	_toast_until = Time.get_ticks_msec() / 1000.0 + 3.0
	_pick_dirty = true


func _survey(axial: Vector2i) -> Dictionary:
	if not _survey_cache.has(axial):
		_survey_cache[axial] = region.survey_hex(axial, HEX_SIZE)
	return _survey_cache[axial]


func _set_hover(axial: Vector2i) -> void:
	if axial == hover_axial:
		return
	hover_axial = axial
	terrain.terrain_material.set_shader_parameter("hover_hex", Vector2(axial))


func _hex_state(a: Vector2i) -> int:
	if state.has_home and a == home_axial:
		return HexState.HOME
	if state.claimed.has(a):
		return HexState.CLAIMED
	if state.is_scouted(a):
		return HexState.SCOUTED
	if state.is_frontier(a):
		return HexState.FRONTIER
	return HexState.UNKNOWN


func _can_claim(a: Vector2i) -> bool:
	return state.is_scouted(a) and not state.is_owned(a) and state.touches(a, state.is_owned)


func _scout(a: Vector2i, save := true) -> void:
	if _survey(a).cells == 0:
		return  # outside the generated region
	state.record_scout(a, deposits.generate(a) if not state.is_scouted(a) else [])
	if save:
		state.save()


func _click_hex() -> void:
	var a := hover_axial
	if a == NO_HEX:
		return
	match _hex_state(a):
		HexState.UNKNOWN:
			_flash("Too far into the unknown. Scout a neighbouring hex first.")
		HexState.FRONTIER:
			_scout(a)
			var n := state.deposits(a).size()
			_flash("Scouted hex %d,%d: %d deposit%s found." % [a.x, a.y, n, "" if n == 1 else "s"])
		HexState.CLAIMED:
			state.claimed.erase(a)
			state.save()
			_flash("Released hex %d,%d." % [a.x, a.y])
		HexState.SCOUTED:
			if _can_claim(a):
				state.claimed.append(a)
				state.save()
				_flash("Claimed hex %d,%d." % [a.x, a.y])
			else:
				_flash("You can only claim hexes next to your own land.")
		HexState.HOME:
			_flash("This is home.")
	_refresh_world()


# --- Hex state texture & markers ------------------------------------------
func _setup_hex_state() -> void:
	var size := region.world_size()
	var q0 := int(floor(-size.y / 3.0 / HEX_SIZE)) - 2
	var q1 := int(ceil(Hex.SQRT3 / 3.0 * size.x / HEX_SIZE)) + 2
	var r1 := int(ceil(2.0 / 3.0 * size.y / HEX_SIZE)) + 2
	hex_origin = Vector2i(q0, -2)
	hex_state_image = Image.create(q1 - q0 + 1, r1 + 3, false, Image.FORMAT_R8)
	hex_state_texture = ImageTexture.create_from_image(hex_state_image)
	var m := terrain.terrain_material
	m.set_shader_parameter("hex_state_tex", hex_state_texture)
	m.set_shader_parameter("hex_origin", hex_origin)
	m.set_shader_parameter("hex_dims", Vector2i(hex_state_image.get_width(), hex_state_image.get_height()))


func _refresh_world() -> void:
	hex_state_image.fill(Color(0, 0, 0))
	var mark := func(a: Vector2i) -> void:
		var t := a - hex_origin
		if t.x >= 0 and t.y >= 0 and t.x < hex_state_image.get_width() and t.y < hex_state_image.get_height():
			hex_state_image.set_pixel(t.x, t.y, Color8(_hex_state(a), 0, 0))
	var items := []
	for a in state.scouted:
		mark.call(a)
		for d in WorldState.NEIGHBOURS:
			mark.call(a + d)
		for d in state.deposits(a):
			var x := float(d.x)
			var z := float(d.z)
			var size := 1.4 + log(1.0 + float(d.amount)) * 0.3
			items.append([Vector3(x, terrain.world_height(x, z), z), ResourceTypes.colour(d.type), size])
	hex_state_texture.update(hex_state_image)
	markers.set_items(items)
	var m := terrain.terrain_material
	m.set_shader_parameter("hex_size", HEX_SIZE)
	m.set_shader_parameter("show_hex", show_hex)
	_update_title()
	_pick_dirty = true


func _update_hex_uniforms() -> void:
	terrain.terrain_material.set_shader_parameter("show_hex", show_hex)
