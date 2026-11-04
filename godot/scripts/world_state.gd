class_name WorldState
extends RefCounted
## What this player knows and owns. Scouted hexes keep the deposits found at
## the time ("once seen, fixed") plus when they were seen. Saved to user://.
## This becomes per-player server state when multiplayer arrives.

const NEIGHBOURS: Array[Vector2i] = [
	Vector2i(1, 0), Vector2i(1, -1), Vector2i(0, -1),
	Vector2i(-1, 0), Vector2i(-1, 1), Vector2i(0, 1),
]

var region_name: String
var home := Vector2i(1 << 20, 0)
var has_home := false
var scouted := {}  ## Vector2i -> {"t": unix seconds, "deposits": Array}
var claimed: Array[Vector2i] = []


func _init(name: String) -> void:
	region_name = name


func save_path() -> String:
	return "user://save_%s.json" % region_name


func is_scouted(a: Vector2i) -> bool:
	return scouted.has(a)


func is_owned(a: Vector2i) -> bool:
	return (has_home and a == home) or claimed.has(a)


func touches(a: Vector2i, set_fn: Callable) -> bool:
	for d in NEIGHBOURS:
		if set_fn.call(a + d):
			return true
	return false


## Unscouted, but next to something already scouted.
func is_frontier(a: Vector2i) -> bool:
	return not is_scouted(a) and touches(a, is_scouted)


func record_scout(a: Vector2i, deposits: Array) -> void:
	if scouted.has(a):
		scouted[a].t = Time.get_unix_time_from_system()  # deposits stay as first seen
	else:
		scouted[a] = {"t": Time.get_unix_time_from_system(), "deposits": deposits}


func deposits(a: Vector2i) -> Array:
	return scouted[a].deposits if scouted.has(a) else []


func save() -> void:
	var s := {}
	for a in scouted:
		s["%d,%d" % [a.x, a.y]] = scouted[a]
	var c := []
	for a in claimed:
		c.append("%d,%d" % [a.x, a.y])
	var f := FileAccess.open(save_path(), FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"version": 1, "scouted": s, "claimed": c}))


func load_save() -> bool:
	if not FileAccess.file_exists(save_path()):
		return false
	var f := FileAccess.open(save_path(), FileAccess.READ)
	var data = JSON.parse_string(f.get_as_text()) if f else null
	if typeof(data) != TYPE_DICTIONARY:
		return false
	scouted.clear()
	claimed.clear()
	for key in data.get("scouted", {}):
		scouted[_parse(key)] = data.scouted[key]
	for key in data.get("claimed", []):
		claimed.append(_parse(key))
	return true


func reset() -> void:
	scouted.clear()
	claimed.clear()
	if FileAccess.file_exists(save_path()):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(save_path()))


static func _parse(key: String) -> Vector2i:
	var p := key.split(",")
	return Vector2i(int(p[0]), int(p[1]))
