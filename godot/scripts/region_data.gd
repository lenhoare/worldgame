class_name RegionData
extends RefCounted
## A generated region (see tools/mapgen/generate.py): grid geometry plus the
## height, land-cover and building layers, with helpers for world queries.
##
## World space: x = metres east of the region's west edge, z = metres south
## of its north edge, y = up. Cell (col, row) covers
## [col * cell_size, (col + 1) * cell_size) on x, and likewise rows on z.

const HIGH_GROUND := 45.0  ## metres; natural ground above this is chalk downland
const LOW_GROUND := 6.0  ## metres; natural ground below this is floodplain / clay
const NATURAL := ["grass", "farmland", "scrub", "wood", "bare", "golf", "park", "wetland"]

var path: String
var meta: Dictionary
var width: int
var height: int
var cell_size: float
var classes: Array = []
var class_ids := {}  ## name -> id
var sites: Array = []  ## real points of interest: {kind, x, z, name}
var heights: PackedFloat32Array  ## metres, row-major, row 0 = north
var cover: PackedByteArray  ## class id per cell
var buildings: PackedByteArray  ## (height_m, roof_variant) per cell
var height_image: Image  ## FORMAT_RH, for the GPU (filterable on WebGL2)
var cover_image: Image  ## FORMAT_R8


static func load_region(dir: String) -> RegionData:
	var meta_file := FileAccess.open(dir.path_join("meta.json"), FileAccess.READ)
	if meta_file == null:
		push_error("Region not found: %s" % dir)
		return null
	var r := RegionData.new()
	r.path = dir
	r.meta = JSON.parse_string(meta_file.get_as_text())
	r.width = int(r.meta.width)
	r.height = int(r.meta.height)
	r.cell_size = float(r.meta.cell_size)
	r.classes = r.meta.classes
	for c in r.classes:
		r.class_ids[String(c.name)] = int(c.id)
	if r.meta.layers.has("sites"):
		var sf := FileAccess.open(dir.path_join(r.meta.layers.sites.file), FileAccess.READ)
		if sf:
			r.sites = JSON.parse_string(sf.get_as_text())
	var n := r.width * r.height

	var layers: Dictionary = r.meta.layers
	var hbytes := _read_gz(dir.path_join(layers.height.file), n * 2)
	var cbytes := _read_gz(dir.path_join(layers.cover.file), n)
	var bbytes := _read_gz(dir.path_join(layers.buildings.file), n * 2)
	if hbytes.is_empty() or cbytes.is_empty() or bbytes.is_empty():
		return null

	r.height_image = Image.create_from_data(r.width, r.height, false, Image.FORMAT_RH, hbytes)
	var hf := r.height_image.duplicate() as Image
	hf.convert(Image.FORMAT_RF)
	r.heights = hf.get_data().to_float32_array()
	r.cover = cbytes
	r.cover_image = Image.create_from_data(r.width, r.height, false, Image.FORMAT_R8, cbytes)
	r.buildings = bbytes
	return r


static func _read_gz(file_path: String, expected: int) -> PackedByteArray:
	var f := FileAccess.open(file_path, FileAccess.READ)
	if f == null:
		push_error("Missing layer: %s" % file_path)
		return PackedByteArray()
	var data := f.get_buffer(f.get_length()).decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)
	if data.size() != expected:
		push_error("Layer %s has %d bytes, expected %d" % [file_path, data.size(), expected])
		return PackedByteArray()
	return data


func world_size() -> Vector2:
	return Vector2(width * cell_size, height * cell_size)


func contains(x: float, z: float) -> bool:
	return x >= 0.0 and z >= 0.0 and x < width * cell_size and z < height * cell_size


func cell_at(x: float, z: float) -> Vector2i:
	return Vector2i(
		clampi(int(floor(x / cell_size)), 0, width - 1),
		clampi(int(floor(z / cell_size)), 0, height - 1))


## Terrain height in metres, bilinear between cell centres (matches the GPU).
func height_at(x: float, z: float) -> float:
	var fx := clampf(x / cell_size - 0.5, 0.0, width - 1.001)
	var fz := clampf(z / cell_size - 0.5, 0.0, height - 1.001)
	var ix := int(fx)
	var iz := int(fz)
	var tx := fx - ix
	var tz := fz - iz
	var i := iz * width + ix
	var a := heights[i]
	var b := heights[i + 1]
	var c := heights[i + width]
	var d := heights[i + width + 1]
	return lerpf(lerpf(a, b, tx), lerpf(c, d, tx), tz)


func cell_index_at(x: float, z: float) -> int:
	var c := cell_at(x, z)
	return c.y * width + c.x


func class_at(cell: Vector2i) -> int:
	return cover[cell.y * width + cell.x]


func building_height_at(cell: Vector2i) -> int:
	return buildings[(cell.y * width + cell.x) * 2]


func class_name_of(id: int) -> String:
	return classes[id].name if id < classes.size() else "?"


## World position -> [longitude, latitude] via the local Web Mercator frame.
func world_to_lonlat(x: float, z: float) -> Vector2:
	var proj: Dictionary = meta.projection
	var n := pow(2.0, float(proj.zoom))
	var tx := float(proj.origin_tile_x) + x / float(proj.metres_per_tile)
	var ty := float(proj.origin_tile_y) + z / float(proj.metres_per_tile)
	var lon := tx / n * 360.0 - 180.0
	var lat := rad_to_deg(atan(sinh(PI * (1.0 - 2.0 * ty / n))))
	return Vector2(lon, lat)


## Land cover, buildings and terrain inside one hex. Public information:
## anyone can see the landscape; resources need scouting (DepositGenerator).
func survey_hex(axial: Vector2i, hex_size: float) -> Dictionary:
	var centre := Hex.axial_to_world(axial, hex_size)
	var c0 := maxi(0, int(floor((centre.x - hex_size) / cell_size)))
	var c1 := mini(width - 1, int(ceil((centre.x + hex_size) / cell_size)))
	var r0 := maxi(0, int(floor((centre.y - hex_size) / cell_size)))
	var r1 := mini(height - 1, int(ceil((centre.y + hex_size) / cell_size)))
	var natural := {}
	for n in NATURAL:
		natural[class_ids[n]] = true
	var cells_by_id := []
	for i in classes.size():
		cells_by_id.append(PackedInt32Array())
	var total := 0
	var building_cells := 0
	var building_volume := 0.0
	var high_natural := 0
	var low_natural := 0
	for row in range(r0, r1 + 1):
		var z := (row + 0.5) * cell_size
		for col in range(c0, c1 + 1):
			if Hex.world_to_axial((col + 0.5) * cell_size, z, hex_size) != axial:
				continue
			var i := row * width + col
			var cls := cover[i]
			cells_by_id[cls].append(i)
			total += 1
			var bh := buildings[i * 2]
			if bh > 0:
				building_cells += 1
				building_volume += bh
			if natural.has(cls):
				if heights[i] > HIGH_GROUND:
					high_natural += 1
				elif heights[i] < LOW_GROUND:
					low_natural += 1
	var counts := {}
	var cells := {}
	var top := []
	for c in classes:
		var pool: PackedInt32Array = cells_by_id[int(c.id)]
		counts[String(c.name)] = pool.size()
		cells[String(c.name)] = pool
		if pool.size() > 0:
			top.append([pool.size(), int(c.id)])
	top.sort_custom(func(a, b): return a[0] > b[0])
	return {
		"cells": total,
		"counts_by_name": counts,
		"cells_by_name": cells,
		"building_cells": building_cells,
		"building_volume": building_volume,
		"high_natural": high_natural,
		"low_natural": low_natural,
		"top": top.slice(0, 3),
	}
