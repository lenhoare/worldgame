extends Node
## Live viewer for the WorldGame simulation server (server/worldgame).
##
## The server owns the world. This scene only draws it: voxel faces arrive as
## ready-made MultiMesh buffers per chunk; giants, items, fires and cables come
## from a small JSON state polled twice a second. Humans can send advice to
## their giant, nothing more.
##
## Run the server first:  cd server && python3 -m worldgame --giants Ada,Bo
## Options after `--`:    --server=http://host:8377  --token=<giant token>
##                        --view=x,z,yaw,pitch,dist (voxels)  --follow=<name>
##                        --wait=<seconds>  --screenshot=out.png

const POLL := 0.5
const PIXEL_SIZES := [1, 2, 3, 4]

@export var server_url := "http://127.0.0.1:8377"
@export var pixel_size := 2

var meta := {}
var cell := 3.0
var sea := 8
var size := Vector3i.ZERO
var heights := PackedByteArray()

var container: SubViewportContainer
var world: Node3D          ## unscaled, metres
var voxels: Node3D         ## scaled by `cell`, holds chunk meshes in voxel units
var rig: CameraRig
var sun: DirectionalLight3D
var env: Environment
var voxel_material: ShaderMaterial
var chunk_nodes := {}
var quad := QuadMesh.new()

var items := {}            ## id -> {p: Vector3i, s: String, kg: float, burning: bool}
var item_mesh: MultiMeshInstance3D
var item_material: ShaderMaterial
var sprite_index := {}
var fire_mesh: MultiMeshInstance3D
var wire_mesh: MeshInstance3D
var giants := {}           ## id -> {node, label, target: Vector3, data}
var follow_id := -1

var state_req: HTTPRequest
var chunk_req: HTTPRequest
var misc_req: HTTPRequest
var state_busy := false
var chunk_busy := false
var items_rev := 0
var chunks_rev := 0
var pending_rev := 0
var connected := false
var _poll_t := 0.0
var _items_dirty := false

var title_label: Label
var giants_label: Label
var log_label: Label
var status_label: Label
var token_edit: LineEdit
var advice_edit: LineEdit
var args := {}
var _drag_button := -1
var _shot_wait := -1.0


func _ready() -> void:
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	if args.has("server"):
		server_url = String(args.server)
	_build_viewport()
	_build_environment()
	_build_ui()
	for n in ["state_req", "chunk_req", "misc_req"]:
		var r := HTTPRequest.new()
		r.use_threads = true
		r.timeout = 20.0
		add_child(r)
		set(n, r)
	state_req.request_completed.connect(_on_state)
	chunk_req.request_completed.connect(_on_chunks)
	_load_sprites()
	_connect_to_server()


# --- connection -------------------------------------------------------------
func _connect_to_server() -> void:
	status_label.text = "Connecting to %s …" % server_url
	var r := HTTPRequest.new()
	add_child(r)
	r.timeout = 5.0
	r.request_completed.connect(func(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
		r.queue_free()
		if result != HTTPRequest.RESULT_SUCCESS or code != 200:
			status_label.text = ("No world server at %s.\n\nStart it with:\n  cd server\n  python3 -m worldgame --giants Ada,Bo\n\n"
				+ "Press R to retry, or L for the offline landscape explorer.") % server_url
			return
		meta = JSON.parse_string(body.get_string_from_utf8())
		_setup_world()
		var h := HTTPRequest.new()
		add_child(h)
		h.request_completed.connect(func(res: int, c: int, _hh: PackedStringArray, b: PackedByteArray) -> void:
			h.queue_free()
			if res == HTTPRequest.RESULT_SUCCESS and c == 200:
				heights = b.decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)
			connected = true
			status_label.text = "Loading the world…")
		h.request(server_url + "/view/heights"))
	r.request(server_url + "/view/meta")


func _setup_world() -> void:
	cell = float(meta.cell)
	sea = int(meta.sea)
	size = Vector3i(int(meta.size[0]), int(meta.size[1]), int(meta.size[2]))
	voxels.scale = Vector3.ONE * cell
	voxels.position = Vector3(0, -sea * cell, 0)
	var flags := Image.create(256, 1, false, Image.FORMAT_R8)
	for m in meta.materials:
		var f := 0
		var tags: Array = m.tags
		if m.kind == "liquid":
			f = 2
		elif m.kind == "foliage":
			f = 3
		elif tags.has("window"):
			f = 4
		elif tags.has("wall") and not tags.has("built"):
			f = 1
		elif tags.has("roof"):
			f = 5
		elif tags.has("road"):
			f = 6
		flags.set_pixel(int(m.id), 0, Color8(f, 0, 0))
	voxel_material.set_shader_parameter("flags_tex", ImageTexture.create_from_image(flags))
	voxel_material.set_shader_parameter("cell", cell)
	voxel_material.set_shader_parameter("y_offset", sea * cell)
	var w := Vector2(size.x, size.z) * cell
	rig.bounds = Rect2(Vector2.ZERO, w)
	rig.ground_height = func(x: float, z: float) -> float: return _ground(x, z)
	var home = meta.get("home")
	rig.set_focus(Vector2(float(home.x), float(home.z)) if home else w * 0.5)
	rig.distance = 900.0
	rig.pitch = deg_to_rad(42.0)
	if args.has("view"):
		var v := String(args.view).split_floats(",")
		rig.set_focus(Vector2(v[0], v[1]) * cell)
		rig.yaw = deg_to_rad(v[2])
		rig.pitch = deg_to_rad(v[3])
		rig.distance = v[4] * cell
	rig.snap()
	title_label.text = "WORLDGAME · %s" % String(meta.name).replace("_", " ").capitalize()


func _ground(x: float, z: float) -> float:
	if heights.is_empty():
		return 0.0
	var cx := clampi(int(x / cell), 0, size.x - 1)
	var cz := clampi(int(z / cell), 0, size.z - 1)
	return (heights[cx * size.z + cz] + 1 - sea) * cell


func _process(delta: float) -> void:
	_camera_keys(delta)
	for id in giants:
		var g: Dictionary = giants[id]
		var node: Node3D = g.node
		node.position = node.position.lerp(g.target, 1.0 - exp(-delta * 6.0))
		var d: Vector3 = g.target - node.position
		if Vector2(d.x, d.z).length() > 0.3:
			node.rotation.y = lerp_angle(node.rotation.y, atan2(d.x, d.z), 1.0 - exp(-delta * 8.0))
	if follow_id in giants:
		var p: Vector3 = giants[follow_id].node.position
		rig.set_focus(Vector2(p.x, p.z))
	if _items_dirty:
		_items_dirty = false
		_rebuild_items()
	if not connected:
		return
	_poll_t -= delta
	if _poll_t <= 0.0 and not state_busy:
		_poll_t = POLL
		state_busy = true
		if state_req.request("%s/view/state?since=%d" % [server_url, items_rev]) != OK:
			state_busy = false
	if _shot_wait >= 0.0:
		_shot_wait -= delta
		if _shot_wait < 0.0:
			_screenshot()


# --- state ----------------------------------------------------------------------
func _on_state(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	state_busy = false
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		status_label.text = "Lost contact with the server. Retrying…"
		return
	var s = JSON.parse_string(body.get_string_from_utf8())
	if typeof(s) != TYPE_DICTIONARY:
		return
	items_rev = int(s.rev)
	for it in s.items:
		var id := int(it.id)
		if it.has("p"):
			items[id] = {"p": Vector3i(int(it.p[0]), int(it.p[1]), int(it.p[2])), "s": String(it.s),
				"kg": float(it.kg), "burning": it.has("burning")}
			_items_dirty = true
		elif items.erase(id):
			_items_dirty = true
	for id in s.removed:
		if items.erase(int(id)):
			_items_dirty = true
	_update_giants(s.giants)
	_update_fires(s.fires)
	_update_wires(s.links)
	_update_light(float(s.daylight), bool(s.raining))
	_update_hud(s)
	if int(s.chunks) > 0 and not chunk_busy:
		chunk_busy = true
		pending_rev = items_rev
		if chunk_req.request("%s/view/chunks?since=%d" % [server_url, chunks_rev]) != OK:
			chunk_busy = false
	if args.has("screenshot") and _shot_wait < 0.0 and chunks_rev > 0 and not args.has("_shot"):
		args["_shot"] = true
		_shot_wait = float(args.get("wait", "2"))


func _on_chunks(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	chunk_busy = false
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		return
	var data := body.decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)
	if data.size() < 4:
		return
	var n := data.decode_u32(0)
	var pos := 4
	var chunk := int(meta.chunk)
	for i in n:
		var cx := data.decode_u16(pos)
		var cz := data.decode_u16(pos + 2)
		var count := data.decode_u32(pos + 4)
		pos += 8
		var key := Vector2i(cx, cz)
		var node: MultiMeshInstance3D = chunk_nodes.get(key)
		if node == null:
			node = MultiMeshInstance3D.new()
			node.material_override = voxel_material
			var mm := MultiMesh.new()
			mm.transform_format = MultiMesh.TRANSFORM_3D
			mm.use_colors = true
			mm.mesh = quad
			mm.custom_aabb = AABB(Vector3(cx * chunk, 0, cz * chunk), Vector3(chunk, size.y, chunk))
			node.multimesh = mm
			voxels.add_child(node)
			chunk_nodes[key] = node
		node.multimesh.instance_count = count
		if count > 0:
			node.multimesh.buffer = data.slice(pos, pos + count * 64).to_float32_array()
		pos += count * 64
	chunks_rev = pending_rev
	if n > 0:
		_refresh_heights()
	status_label.text = ""


func _refresh_heights() -> void:
	misc_req.cancel_request()
	if misc_req.request_completed.is_connected(_on_heights):
		misc_req.request_completed.disconnect(_on_heights)
	misc_req.request_completed.connect(_on_heights, CONNECT_ONE_SHOT)
	misc_req.request(server_url + "/view/heights")


func _on_heights(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
	if result == HTTPRequest.RESULT_SUCCESS and code == 200:
		heights = body.decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)


func _update_giants(list: Array) -> void:
	var seen := {}
	for d in list:
		var id := int(d.id)
		seen[id] = true
		var target := Vector3((float(d.p[0]) + 0.5) * cell, (float(d.p[1]) - sea) * cell, (float(d.p[2]) + 0.5) * cell)
		if not giants.has(id):
			var node := Giant.new()
			node.paint_colour = Color(String(d.colour))
			node.position = target
			world.add_child(node)
			var label := Label3D.new()
			label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
			label.no_depth_test = true
			label.fixed_size = true
			label.pixel_size = 0.0011
			label.font_size = 28
			label.outline_size = 8
			label.position = Vector3(0, 15, 0)
			node.add_child(label)
			giants[id] = {"node": node, "label": label, "target": target, "data": d}
			if args.get("follow", "") == String(d.name):
				follow_id = id
		var g: Dictionary = giants[id]
		g.target = target
		g.data = d
		var text := String(d.name)
		if d.state != "active":
			text += " (%s)" % d.state
		if d.has("said"):
			text += "\n“%s”" % String(d.said).left(60)
		g.label.text = text
		g.label.modulate = Color(1, 0.6, 0.5) if d.state != "active" else Color.WHITE
	for id in giants.keys():
		if not seen.has(id):
			giants[id].node.queue_free()
			giants.erase(id)


func _rebuild_items() -> void:
	var mm := item_mesh.multimesh
	mm.instance_count = items.size()
	var buf := PackedFloat32Array()
	buf.resize(items.size() * 16)
	var i := 0
	for id in items:
		var it: Dictionary = items[id]
		var s := 1.2 + 0.35 * log(maxf(10.0, it.kg)) / log(10.0)      # metres, grows gently with mass
		if it.s == "car":
			s = 4.2
		var jitter := Vector2(((id * 73) % 100) / 100.0 - 0.5, ((id * 37) % 100) / 100.0 - 0.5) * 0.5
		var p: Vector3i = it.p
		var o := i * 16
		buf[o] = s
		buf[o + 3] = (p.x + 0.5 + jitter.x) * cell
		buf[o + 5] = s
		buf[o + 7] = (p.y - sea) * cell + s * 0.5
		buf[o + 10] = s
		buf[o + 11] = (p.z + 0.5 + jitter.y) * cell
		buf[o + 12] = float(sprite_index.get(it.s, sprite_index.get("default", 0)))
		buf[o + 13] = 1.0 if it.burning else 0.0
		i += 1
	if items.size() > 0:
		mm.buffer = buf


func _update_fires(list: Array) -> void:
	var mm := fire_mesh.multimesh
	mm.instance_count = list.size()
	for i in list.size():
		var p: Array = list[i]
		mm.set_instance_transform(i, Transform3D(Basis.from_scale(Vector3.ONE * cell * 1.08),
			Vector3((float(p[0]) + 0.5) * cell, (float(p[1]) - sea + 0.5) * cell, (float(p[2]) + 0.5) * cell)))


func _update_wires(list: Array) -> void:
	var im: ImmediateMesh = wire_mesh.mesh
	im.clear_surfaces()
	if list.is_empty():
		return
	im.surface_begin(Mesh.PRIMITIVE_LINES)
	for l in list:
		for j in [0, 3]:
			im.surface_add_vertex(Vector3((float(l[j]) + 0.5) * cell, (float(l[j + 1]) - sea) * cell + 1.5,
				(float(l[j + 2]) + 0.5) * cell))
	im.surface_end()


func _update_light(daylight: float, raining: bool) -> void:
	var d := clampf(daylight, 0.0, 1.0)
	var lit := sqrt(d)                                  # dawn and dusk stay readable
	sun.light_energy = (0.25 + 1.45 * lit) * (0.6 if raining else 1.0)
	sun.rotation.x = deg_to_rad(-20.0 - 35.0 * d)
	env.ambient_light_energy = 0.3 + 0.25 * lit
	env.background_energy_multiplier = 0.2 + 0.8 * lit
	item_material.set_shader_parameter("brightness", 0.5 + 0.5 * lit)


func _update_hud(s: Dictionary) -> void:
	var w := "rain" if s.raining else "dry"
	title_label.text = "WORLDGAME · %s\n%s · %s · %.0fx%s" % [
		String(meta.get("name", "")).replace("_", " ").capitalize(), s.clock, w, float(s.speed),
		" · PAUSED" if s.paused else ""]
	var lines := []
	var n := 1
	for d in s.giants:
		lines.append("%d  %s   %d kWh · %d%% · %s%s" % [n, d.name, d.energy, d.integrity, d.doing,
			("  [" + ", ".join(d.carrying) + "]") if d.carrying.size() > 0 else ""])
		n += 1
	if lines.is_empty():
		lines.append("No giants yet. Agents join with POST /join.")
	giants_label.text = "\n".join(lines)
	var log := []
	for e in s.log:
		if e.type in ["result", "failed"]:
			continue
		log.append("%s  %s" % [_hhmm(int(e.t)), String(e.text).left(110)])
	log_label.text = "\n".join(log.slice(maxi(0, log.size() - 9)))


func _hhmm(tick: int) -> String:
	return "%02d:%02d" % [tick / 60, tick % 60]


# --- scene ---------------------------------------------------------------------------
func _build_viewport() -> void:
	container = SubViewportContainer.new()
	container.stretch = true
	container.stretch_shrink = pixel_size
	container.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	container.set_anchors_preset(Control.PRESET_FULL_RECT)
	container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(container)
	var viewport := SubViewport.new()
	viewport.msaa_3d = Viewport.MSAA_DISABLED
	container.add_child(viewport)
	world = Node3D.new()
	viewport.add_child(world)
	voxels = Node3D.new()
	world.add_child(voxels)
	voxel_material = ShaderMaterial.new()
	voxel_material.shader = preload("res://shaders/voxel.gdshader")
	quad.size = Vector2.ONE

	item_mesh = MultiMeshInstance3D.new()
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_custom_data = true
	mm.mesh = quad
	mm.custom_aabb = AABB(Vector3(-1e5, -1e3, -1e5), Vector3(2e5, 2e3, 2e5))
	item_mesh.multimesh = mm
	item_material = ShaderMaterial.new()
	item_material.shader = preload("res://shaders/sprite.gdshader")
	item_mesh.material_override = item_material
	item_mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	world.add_child(item_mesh)

	fire_mesh = MultiMeshInstance3D.new()
	var fm := MultiMesh.new()
	fm.transform_format = MultiMesh.TRANSFORM_3D
	fm.mesh = BoxMesh.new()
	fm.custom_aabb = mm.custom_aabb
	fire_mesh.multimesh = fm
	var fmat := ShaderMaterial.new()
	fmat.shader = preload("res://shaders/fire.gdshader")
	fire_mesh.material_override = fmat
	fire_mesh.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	world.add_child(fire_mesh)

	wire_mesh = MeshInstance3D.new()
	wire_mesh.mesh = ImmediateMesh.new()
	var wmat := StandardMaterial3D.new()
	wmat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	wmat.albedo_color = Color("#ffb347")
	wire_mesh.material_override = wmat
	world.add_child(wire_mesh)

	rig = CameraRig.new()
	world.add_child(rig)


func _build_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color("#6fa7c9")
	sky_mat.sky_horizon_color = Color("#cfe0e3")
	sky_mat.ground_horizon_color = Color("#cfe0e3")
	sky_mat.ground_bottom_color = Color("#2c4a55")
	var sky := Sky.new()
	sky.sky_material = sky_mat
	env = Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("#b9c8d0")
	env.ambient_light_energy = 0.4
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	var we := WorldEnvironment.new()
	we.environment = env
	world.add_child(we)
	sun = DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-45.0), deg_to_rad(-30.0), 0.0)
	sun.light_energy = 1.4
	sun.light_color = Color("#fff4e0")
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	sun.directional_shadow_max_distance = 900.0
	world.add_child(sun)


func _load_sprites() -> void:
	var f := FileAccess.open("res://assets/sprites/items.json", FileAccess.READ)
	if f == null:
		return
	var info: Dictionary = JSON.parse_string(f.get_as_text())
	sprite_index = info.index
	item_material.set_shader_parameter("atlas", load("res://assets/sprites/items.png"))
	item_material.set_shader_parameter("columns", float(info.columns))
	item_material.set_shader_parameter("rows", float(info.rows))


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.07, 0.15, 0.17, 0.86)
	style.set_corner_radius_all(6)
	style.set_content_margin_all(10)

	title_label = _label(_panel(layer, style, Control.PRESET_TOP_LEFT), "WORLDGAME")
	giants_label = _label(_panel(layer, style, Control.PRESET_TOP_RIGHT), "")
	log_label = _label(_panel(layer, style, Control.PRESET_BOTTOM_LEFT), "")
	log_label.custom_minimum_size = Vector2(520, 0)
	log_label.add_theme_color_override("font_color", Color("#cfe3e6"))

	var advice := _panel(layer, style, Control.PRESET_BOTTOM_RIGHT)
	var box := VBoxContainer.new()
	advice.add_child(box)
	var help := _label(box, "Drag pan · right-drag orbit · wheel zoom\n1-8 follow a giant · 0 free camera · P pixels\nAdvise your giant (advice only):")
	help.add_theme_color_override("font_color", Color("#b8d0d4"))
	token_edit = LineEdit.new()
	token_edit.placeholder_text = "your giant's token"
	token_edit.text = String(args.get("token", ""))
	box.add_child(token_edit)
	advice_edit = LineEdit.new()
	advice_edit.placeholder_text = "advice, then Enter"
	advice_edit.custom_minimum_size = Vector2(320, 0)
	advice_edit.text_submitted.connect(_send_advice)
	box.add_child(advice_edit)

	var mid := _panel(layer, style, Control.PRESET_CENTER)
	status_label = _label(mid, "")
	status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	status_label.item_rect_changed.connect(func() -> void: mid.visible = status_label.text != "")


func _label(parent: Node, text: String) -> Label:
	var l := Label.new()
	l.text = text
	parent.add_child(l)
	return l


func _panel(layer: CanvasLayer, style: StyleBox, preset: int) -> PanelContainer:
	var p := PanelContainer.new()
	p.add_theme_stylebox_override("panel", style)
	layer.add_child(p)
	p.set_anchors_and_offsets_preset(preset, Control.PRESET_MODE_MINSIZE, 12)
	match preset:
		Control.PRESET_TOP_RIGHT:
			p.grow_horizontal = Control.GROW_DIRECTION_BEGIN
		Control.PRESET_BOTTOM_LEFT:
			p.grow_vertical = Control.GROW_DIRECTION_BEGIN
		Control.PRESET_BOTTOM_RIGHT:
			p.grow_vertical = Control.GROW_DIRECTION_BEGIN
			p.grow_horizontal = Control.GROW_DIRECTION_BEGIN
		Control.PRESET_CENTER:
			p.grow_vertical = Control.GROW_DIRECTION_BOTH
			p.grow_horizontal = Control.GROW_DIRECTION_BOTH
	if preset in [Control.PRESET_TOP_LEFT, Control.PRESET_TOP_RIGHT, Control.PRESET_BOTTOM_LEFT, Control.PRESET_CENTER]:
		p.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return p


func _send_advice(text: String) -> void:
	if text.strip_edges() == "" or token_edit.text.strip_edges() == "":
		return
	var r := HTTPRequest.new()
	add_child(r)
	r.request_completed.connect(func(_res: int, code: int, _h: PackedStringArray, _b: PackedByteArray) -> void:
		r.queue_free()
		advice_edit.placeholder_text = "sent" if code == 200 else "not sent: check the token")
	r.request(server_url + "/advise", ["Content-Type: application/json"], HTTPClient.METHOD_POST,
		JSON.stringify({"token": token_edit.text.strip_edges(), "text": text}))
	advice_edit.text = ""
	advice_edit.release_focus()


# --- input -----------------------------------------------------------------------------
func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_UP:
			rig.zoom(0.85)
		elif mb.pressed and mb.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			rig.zoom(1.0 / 0.85)
		elif mb.button_index in [MOUSE_BUTTON_LEFT, MOUSE_BUTTON_RIGHT, MOUSE_BUTTON_MIDDLE]:
			_drag_button = mb.button_index if mb.pressed else -1
			if mb.pressed:
				advice_edit.release_focus()
				token_edit.release_focus()
	elif event is InputEventMouseMotion and _drag_button != -1:
		var mm := event as InputEventMouseMotion
		if _drag_button != MOUSE_BUTTON_LEFT or mm.shift_pressed:
			rig.orbit(mm.relative)
		else:
			follow_id = -1
			rig.pan_pixels(mm.relative, get_viewport().get_visible_rect().size.y)
	elif event is InputEventKey and event.pressed and not event.echo:
		var key := (event as InputEventKey).keycode
		if key >= KEY_1 and key <= KEY_8:
			var ids := giants.keys()
			ids.sort()
			if key - KEY_1 < ids.size():
				follow_id = ids[key - KEY_1]
				rig.distance = minf(rig.distance, 220.0)
		elif key == KEY_0:
			follow_id = -1
		elif key == KEY_P:
			pixel_size = PIXEL_SIZES[(PIXEL_SIZES.find(pixel_size) + 1) % PIXEL_SIZES.size()]
			container.stretch_shrink = pixel_size
		elif key == KEY_R and not connected:
			_connect_to_server()
		elif key == KEY_L and not connected:
			get_tree().change_scene_to_file("res://scenes/main.tscn")


func _camera_keys(delta: float) -> void:
	if advice_edit.has_focus() or token_edit.has_focus():
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
		follow_id = -1
		rig.pan_metres(move.normalized() * rig.distance * 0.9 * delta)
	if Input.is_key_pressed(KEY_Q):
		rig.yaw += 1.4 * delta
	if Input.is_key_pressed(KEY_E):
		rig.yaw -= 1.4 * delta
	if Input.is_key_pressed(KEY_Z):
		rig.zoom(1.0 - 1.5 * delta)
	if Input.is_key_pressed(KEY_X):
		rig.zoom(1.0 + 1.5 * delta)


func _screenshot() -> void:
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(String(args.screenshot))
	print("Saved screenshot to ", args.screenshot)
	get_tree().quit()
