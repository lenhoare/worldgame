class_name RegionData
extends RefCounted
## A generated region (see tools/mapgen/generate.py): grid geometry plus the
## height, land-cover and building layers, with helpers for world queries.
##
## World space: x = metres east of the region's west edge, z = metres south
## of its north edge, y = up. Cell (col, row) covers
## [col * cell_size, (col + 1) * cell_size) on x, and likewise rows on z.

const RESOURCE_KEYS := ["biomass", "water", "metal", "energy"]

var path: String
var meta: Dictionary
var width: int
var height: int
var cell_size: float
var classes: Array = []
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


## Count land-cover cells and resources inside one hex.
func survey_hex(axial: Vector2i, hex_size: float) -> Dictionary:
	var centre := Hex.axial_to_world(axial, hex_size)
	var c0 := maxi(0, int(floor((centre.x - hex_size) / cell_size)))
	var c1 := mini(width - 1, int(ceil((centre.x + hex_size) / cell_size)))
	var r0 := maxi(0, int(floor((centre.y - hex_size) / cell_size)))
	var r1 := mini(height - 1, int(ceil((centre.y + hex_size) / cell_size)))
	var counts := PackedInt32Array()
	counts.resize(classes.size())
	var total := 0
	for row in range(r0, r1 + 1):
		var z := (row + 0.5) * cell_size
		for col in range(c0, c1 + 1):
			var x := (col + 0.5) * cell_size
			if Hex.world_to_axial(x, z, hex_size) != axial:
				continue
			counts[cover[row * width + col]] += 1
			total += 1
	var res := {}
	for key in RESOURCE_KEYS:
		res[key] = 0.0
	for id in classes.size():
		if counts[id] == 0:
			continue
		var r: Dictionary = classes[id].resources
		for key in RESOURCE_KEYS:
			res[key] += float(r[key]) * counts[id]
	# Scale so a hex full of a "3" resource reads as roughly 100.
	var scale := 100.0 / (3.0 * maxf(1.0, total))
	for key in RESOURCE_KEYS:
		res[key] = int(round(res[key] * scale))
	var top := []
	for id in classes.size():
		if counts[id] > 0:
			top.append([counts[id], id])
	top.sort_custom(func(a, b): return a[0] > b[0])
	return {"cells": total, "resources": res, "top": top.slice(0, 3)}
