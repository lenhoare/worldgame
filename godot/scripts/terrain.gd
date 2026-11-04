class_name Terrain
extends Node3D
## Builds the 3D landscape for a RegionData in chunks:
## * terrain: a shared grid mesh per chunk, displaced on the GPU from the
##   height texture and coloured per cell from the land-cover texture;
## * buildings: one MultiMesh per chunk, one box per horizontal run of cells
##   with the same height and roof.

signal progress(done: int, total: int)

const CHUNK_CELLS := 256
const VERTEX_STEP := 2  ## cells between terrain vertices (source DEM is ~25 m)
const BUILDING_SINK := 3.0  ## metres buried below ground to hide slope gaps
const BUILDING_VIEW_DISTANCE := 9000.0
const TALL_BUILDING := 24  ## metres; tall blocks use concrete colours

var region: RegionData
var height_scale := 2.0  ## vertical exaggeration so the Downs read clearly
var terrain_material: ShaderMaterial
var building_material: ShaderMaterial
var building_nodes: Array[MultiMeshInstance3D] = []
var _roof_colours: Array[Color] = []
var _tall_colours: Array[Color] = [
	Color("#8d9196").srgb_to_linear(), Color("#a7a29a").srgb_to_linear(),
	Color("#6f7a84").srgb_to_linear(), Color("#bdb8ae").srgb_to_linear(),
]


func build(r: RegionData) -> void:
	region = r
	for c in r.meta.roof_colours:
		_roof_colours.append(Color(c).srgb_to_linear())
	_make_materials()

	var cs := r.cell_size
	var chunk_m := CHUNK_CELLS * cs
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(chunk_m, chunk_m)
	mesh.subdivide_width = CHUNK_CELLS / VERTEX_STEP - 1
	mesh.subdivide_depth = CHUNK_CELLS / VERTEX_STEP - 1
	mesh.center_offset = Vector3(chunk_m / 2.0, 0.0, chunk_m / 2.0)
	var top := float(r.meta.elevation_range[1]) * height_scale + 50.0
	mesh.custom_aabb = AABB(Vector3(0, -20, 0), Vector3(chunk_m, top + 20, chunk_m))

	var nx := ceili(float(r.width) / CHUNK_CELLS)
	var nz := ceili(float(r.height) / CHUNK_CELLS)
	var total := nx * nz
	var done := 0
	for cz in nz:
		for cx in nx:
			var chunk := MeshInstance3D.new()
			chunk.name = "Chunk_%d_%d" % [cx, cz]
			chunk.mesh = mesh
			chunk.material_override = terrain_material
			chunk.position = Vector3(cx * chunk_m, 0.0, cz * chunk_m)
			add_child(chunk)
			_build_buildings(cx * CHUNK_CELLS, cz * CHUNK_CELLS)
			done += 1
			progress.emit(done, total)
			await get_tree().process_frame


func _make_materials() -> void:
	var palette := Image.create(32, 1, false, Image.FORMAT_RGB8)
	for c in region.classes:
		palette.set_pixel(int(c.id), 0, Color(c.colour))
	terrain_material = ShaderMaterial.new()
	terrain_material.shader = preload("res://shaders/terrain.gdshader")
	terrain_material.set_shader_parameter("height_tex", ImageTexture.create_from_image(region.height_image))
	terrain_material.set_shader_parameter("cover_tex", ImageTexture.create_from_image(region.cover_image))
	terrain_material.set_shader_parameter("palette_tex", ImageTexture.create_from_image(palette))
	terrain_material.set_shader_parameter("grid_size", Vector2(region.width, region.height))
	terrain_material.set_shader_parameter("cell_size", region.cell_size)
	terrain_material.set_shader_parameter("height_scale", height_scale)

	building_material = ShaderMaterial.new()
	building_material.shader = preload("res://shaders/building.gdshader")


func _build_buildings(c0: int, r0: int) -> void:
	var w := region.width
	var c1 := mini(c0 + CHUNK_CELLS, w)
	var r1 := mini(r0 + CHUNK_CELLS, region.height)
	var cs := region.cell_size
	var b := region.buildings
	var buf := PackedFloat32Array()
	var count := 0
	var max_top := 0.0
	for row in range(r0, r1):
		var z := (row + 0.5) * cs
		var col := c0
		while col < c1:
			var i := (row * w + col) * 2
			var bh := b[i]
			if bh == 0:
				col += 1
				continue
			var roof := b[i + 1]
			var run := 1
			while col + run < c1 and b[i + run * 2] == bh and b[i + run * 2 + 1] == roof:
				run += 1
			var x := (col + run * 0.5) * cs
			var ground := region.height_at(x, z) * height_scale
			var base := ground - BUILDING_SINK
			var top := ground + bh
			var colour: Color
			if bh >= TALL_BUILDING:
				colour = _tall_colours[roof % _tall_colours.size()]
			else:
				colour = _roof_colours[(roof - 1) % _roof_colours.size()]
			# Transform rows (basis columns scaled) then colour.
			buf.append_array([run * cs, 0.0, 0.0, x,
				0.0, top - base, 0.0, (top + base) * 0.5,
				0.0, 0.0, cs, z,
				colour.r, colour.g, colour.b, 1.0])
			max_top = maxf(max_top, top)
			count += 1
			col += run
	if count == 0:
		return
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	var box := BoxMesh.new()
	mm.mesh = box
	mm.instance_count = count
	mm.buffer = buf
	mm.custom_aabb = AABB(Vector3(c0 * cs, -20.0, r0 * cs),
		Vector3((c1 - c0) * cs, max_top + 40.0, (r1 - r0) * cs))
	var node := MultiMeshInstance3D.new()
	node.multimesh = mm
	node.material_override = building_material
	node.visibility_range_end = BUILDING_VIEW_DISTANCE
	node.visibility_range_end_margin = 800.0
	node.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_DISABLED
	add_child(node)
	building_nodes.append(node)


func set_buildings_visible(on: bool) -> void:
	for n in building_nodes:
		n.visible = on


func world_height(x: float, z: float) -> float:
	if region == null or not region.contains(x, z):
		return 0.0
	return region.height_at(x, z) * height_scale
