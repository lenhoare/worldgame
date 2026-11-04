class_name RegionData
extends RefCounted
## A generated region (see tools/mapgen/generate.py): grid geometry plus the
## height, land-cover, building, geology and hex layers, with helpers for
## world queries.
##
## World space: x = metres east of the region's west edge, z = metres south
## of its north edge, y = up. Cell (col, row) covers
## [col * cell_size, (col + 1) * cell_size) on x, and likewise rows on z.
##
## Hexes are global H3 cells. Each region numbers the hexes it touches with a
## local index (0..hex_count-1); `hex_ids[i]` is the worldwide id.

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
var geology: PackedByteArray  ## (bedrock unit, clay %, sand %) per cell
var hex_layer: PackedByteArray  ## uint16 little-endian local hex index per cell
var height_image: Image  ## FORMAT_RH, for the GPU (filterable on WebGL2)
var cover_image: Image  ## FORMAT_R8
var hex_image: Image  ## FORMAT_RG8 (low, high byte of the local hex index)

var units: Array = []  ## bedrock map units: {name, lith, rock, age}
var unit_rock: PackedByteArray  ## unit index -> rock id
var rock_ids := {}  ## rock name -> id
var hex_resolution := 0
var hexes: Array = []  ## local index -> {id, x, z, complete, cells, bounds, neighbours}
var hex_ids: PackedStringArray
var _hex_index := {}  ## H3 id -> local index


static func load_region(dir: String) -> RegionData:
	var meta_file := FileAccess.open(dir.path_join("meta.json"), FileAccess.READ)
	if meta_file == null:
		push_error("Region not found: %s" % dir)
		return null
	var r := RegionData.new()
	r.path = dir
	r.meta = JSON.parse_string(meta_file.get_as_text())
	if int(r.meta.get("format", 1)) < 2:
		push_error("Region %s is an old format; regenerate it with tools/mapgen/generate.py" % dir)
		return null
	r.width = int(r.meta.width)
	r.height = int(r.meta.height)
	r.cell_size = float(r.meta.cell_size)
	r.classes = r.meta.classes
	for c in r.classes:
		r.class_ids[String(c.name)] = int(c.id)
	var n := r.width * r.height

	var layers: Dictionary = r.meta.layers
	var hbytes := _read_gz(dir.path_join(layers.height.file), n * 2)
	r.cover = _read_gz(dir.path_join(layers.cover.file), n)
	r.buildings = _read_gz(dir.path_join(layers.buildings.file), n * 2)
	r.geology = _read_gz(dir.path_join(layers.geology.file), n * 3)
	r.hex_layer = _read_gz(dir.path_join(layers.hex.file), n * 2)
	for b in [hbytes, r.cover, r.buildings, r.geology, r.hex_layer]:
		if b.is_empty():
			return null

	r.height_image = Image.create_from_data(r.width, r.height, false, Image.FORMAT_RH, hbytes)
	var hf := r.height_image.duplicate() as Image
	hf.convert(Image.FORMAT_RF)
	r.heights = hf.get_data().to_float32_array()
	r.cover_image = Image.create_from_data(r.width, r.height, false, Image.FORMAT_R8, r.cover)
	r.hex_image = Image.create_from_data(r.width, r.height, false, Image.FORMAT_RG8, r.hex_layer)

	r.sites = _read_json(dir.path_join(layers.sites.file), [])
	var table: Dictionary = _read_json(dir.path_join(layers.hex.table), {})
	r.hex_resolution = int(table.get("resolution", 0))
	r.hexes = table.get("hexes", [])
	r.hex_ids.resize(r.hexes.size())
	for i in r.hexes.size():
		r.hex_ids[i] = String(r.hexes[i].id)
		r._hex_index[r.hex_ids[i]] = i

	for rock in r.meta.geology.rocks:
		r.rock_ids[String(rock.name)] = int(rock.id)
	r.units = r.meta.geology.units
	r.unit_rock.resize(r.units.size())
	for i in r.units.size():
		r.unit_rock[i] = r.rock_ids.get(String(r.units[i].rock), 0)
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


static func _read_json(file_path: String, fallback: Variant) -> Variant:
	var f := FileAccess.open(file_path, FileAccess.READ)
	if f == null:
		return fallback
	var v = JSON.parse_string(f.get_as_text())
	return v if v != null else fallback


func world_size() -> Vector2:
	return Vector2(width * cell_size, height * cell_size)


func contains(x: float, z: float) -> bool:
	return x >= 0.0 and z >= 0.0 and x < width * cell_size and z < height * cell_size


func cell_at(x: float, z: float) -> Vector2i:
	return Vector2i(
		clampi(int(floor(x / cell_size)), 0, width - 1),
		clampi(int(floor(z / cell_size)), 0, height - 1))


func cell_index_at(x: float, z: float) -> int:
	var c := cell_at(x, z)
	return c.y * width + c.x


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


## Bedrock map unit at a cell: {name, lith, rock, age}.
func unit_at(cell: Vector2i) -> Dictionary:
	return units[geology[(cell.y * width + cell.x) * 3]]


func soil_at(cell: Vector2i) -> Vector2i:
	var i := (cell.y * width + cell.x) * 3
	return Vector2i(geology[i + 1], geology[i + 2])  # clay %, sand %


# --- Hexes -----------------------------------------------------------------
func hex_count() -> int:
	return hexes.size()


func hex_at_cell(cell: Vector2i) -> int:
	return hex_layer.decode_u16((cell.y * width + cell.x) * 2)


## Local hex index at a world position, or -1 outside the region.
func hex_at(x: float, z: float) -> int:
	return hex_at_cell(cell_at(x, z)) if contains(x, z) else -1


func hex_index(id: String) -> int:
	return _hex_index.get(id, -1)


func hex_centre(idx: int) -> Vector2:
	return Vector2(float(hexes[idx].x), float(hexes[idx].z))


## Fully inside the region, so its whole landscape is known (playable).
func hex_complete(idx: int) -> bool:
	return idx >= 0 and bool(hexes[idx].complete)


func hex_neighbour_ids(id: String) -> PackedStringArray:
	var out := PackedStringArray()
	var idx := hex_index(id)
	if idx < 0:
		return out
	for n in hexes[idx].neighbours:
		if int(n) >= 0:
			out.append(hex_ids[int(n)])
	return out


## World position -> [longitude, latitude] via the local Web Mercator frame.
func world_to_lonlat(x: float, z: float) -> Vector2:
	var proj: Dictionary = meta.projection
	var n := pow(2.0, float(proj.zoom))
	var tx := float(proj.origin_tile_x) + x / float(proj.metres_per_tile)
	var ty := float(proj.origin_tile_y) + z / float(proj.metres_per_tile)
	var lon := tx / n * 360.0 - 180.0
	var lat := rad_to_deg(atan(sinh(PI * (1.0 - 2.0 * ty / n))))
	return Vector2(lon, lat)


## [longitude, latitude] -> world position (x, z) in this region.
func lonlat_to_world(lon: float, lat: float) -> Vector2:
	var proj: Dictionary = meta.projection
	var n := pow(2.0, float(proj.zoom))
	var tx := (lon + 180.0) / 360.0 * n
	var r := deg_to_rad(lat)
	var ty := (1.0 - log(tan(r) + 1.0 / cos(r)) / PI) / 2.0 * n
	var m := float(proj.metres_per_tile)
	return Vector2((tx - float(proj.origin_tile_x)) * m, (ty - float(proj.origin_tile_y)) * m)


## Land cover, buildings, geology and soil inside one hex. Public
## information: anyone can see the landscape; resources need scouting.
func survey_hex(idx: int) -> Dictionary:
	var empty := {"cells": 0, "top": []}
	if idx < 0 or idx >= hexes.size():
		return empty
	var b: Array = hexes[idx].bounds
	var natural := {}
	for name in NATURAL:
		natural[class_ids[name]] = true
	var cells_by_id := []
	for i in classes.size():
		cells_by_id.append(PackedInt32Array())
	var rock_cells := PackedInt32Array()  ## natural cells per rock id
	rock_cells.resize(rock_ids.size())
	var total := 0
	var building_cells := 0
	var building_volume := 0.0
	var clay_sum := 0.0
	var sand_sum := 0.0
	var soil_cells := 0
	var unit_counts := {}
	for row in range(int(b[1]), int(b[3]) + 1):
		for col in range(int(b[0]), int(b[2]) + 1):
			var i := row * width + col
			if hex_layer.decode_u16(i * 2) != idx:
				continue
			var cls := cover[i]
			cells_by_id[cls].append(i)
			total += 1
			var bh := buildings[i * 2]
			if bh > 0:
				building_cells += 1
				building_volume += bh
			var unit := geology[i * 3]
			unit_counts[unit] = unit_counts.get(unit, 0) + 1
			if natural.has(cls):
				rock_cells[unit_rock[unit]] += 1
			var clay := geology[i * 3 + 1]
			if clay > 0:
				clay_sum += clay
				sand_sum += geology[i * 3 + 2]
				soil_cells += 1
	var counts := {}
	var cells := {}
	var top := []
	for c in classes:
		var pool: PackedInt32Array = cells_by_id[int(c.id)]
		counts[String(c.name)] = pool.size()
		cells[String(c.name)] = pool
		if pool.size() > 0:
			top.append([pool.size(), int(c.id)])
	top.sort_custom(func(a, b2): return a[0] > b2[0])
	var rocks := {}
	for name in rock_ids:
		rocks[name] = rock_cells[rock_ids[name]]
	var main_unit := 0
	for u in unit_counts:
		if u != 0 and (main_unit == 0 or unit_counts[u] > unit_counts[main_unit]):
			main_unit = u
	return {
		"cells": total,
		"counts_by_name": counts,
		"cells_by_name": cells,
		"building_cells": building_cells,
		"building_volume": building_volume,
		"natural_by_rock": rocks,
		"clay_pct": clay_sum / soil_cells if soil_cells > 0 else -1.0,
		"sand_pct": sand_sum / soil_cells if soil_cells > 0 else -1.0,
		"bedrock": units[main_unit],
		"top": top.slice(0, 3),
	}
