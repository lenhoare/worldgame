class_name WorldState
extends RefCounted
## What this player knows and owns, keyed by global H3 hex ids, so it carries
## across regions. Scouted hexes keep the deposits found at the time ("once
## seen, fixed") plus when they were seen. Saved to user://.
## This becomes per-player server state when multiplayer arrives.

const SAVE_PATH := "user://worldgame_save.json"

var home := ""  ## H3 id of the home hex ("" = none)
var scouted := {}  ## H3 id -> {"t": unix seconds, "deposits": Array}
var claimed: PackedStringArray = []
## Callable(id: String) -> PackedStringArray of neighbouring hex ids.
var neighbours: Callable


func _init(neighbour_fn: Callable) -> void:
	neighbours = neighbour_fn


func is_scouted(id: String) -> bool:
	return scouted.has(id)


func is_owned(id: String) -> bool:
	return (home != "" and id == home) or claimed.has(id)


func touches(id: String, pred: Callable) -> bool:
	for n in neighbours.call(id):
		if pred.call(n):
			return true
	return false


## Unscouted, but next to something already scouted.
func is_frontier(id: String) -> bool:
	return not is_scouted(id) and touches(id, is_scouted)


func record_scout(id: String, deposits: Array) -> void:
	if scouted.has(id):
		scouted[id].t = Time.get_unix_time_from_system()  # deposits stay as first seen
	else:
		scouted[id] = {"t": Time.get_unix_time_from_system(), "deposits": deposits}


func deposits(id: String) -> Array:
	return scouted[id].deposits if scouted.has(id) else []


func save(path := SAVE_PATH) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"version": 2, "home": home, "scouted": scouted, "claimed": claimed}))


func load_save(path := SAVE_PATH) -> bool:
	if not FileAccess.file_exists(path):
		return false
	var f := FileAccess.open(path, FileAccess.READ)
	var data = JSON.parse_string(f.get_as_text()) if f else null
	if typeof(data) != TYPE_DICTIONARY or int(data.get("version", 0)) != 2:
		return false
	scouted = data.get("scouted", {})
	claimed = PackedStringArray(data.get("claimed", []))
	if String(data.get("home", "")) != "":
		home = String(data.home)
	return true


func reset(path := SAVE_PATH) -> void:
	scouted.clear()
	claimed.clear()
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
