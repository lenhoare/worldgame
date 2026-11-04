class_name Hex
extends RefCounted
## Pointy-top hex grid in world metres (x = east, z = south), axial coordinates.
## The same maths lives in terrain.gdshader so the overlay matches picking.

const SQRT3 := 1.7320508075688772


static func world_to_axial(x: float, z: float, size: float) -> Vector2i:
	var q := (SQRT3 / 3.0 * x - z / 3.0) / size
	var r := (2.0 / 3.0 * z) / size
	return cube_round(q, r)


static func cube_round(q: float, r: float) -> Vector2i:
	var s := -q - r
	var rq := roundf(q)
	var rr := roundf(r)
	var rs := roundf(s)
	var dq := absf(rq - q)
	var dr := absf(rr - r)
	var ds := absf(rs - s)
	if dq > dr and dq > ds:
		rq = -rr - rs
	elif dr > ds:
		rr = -rq - rs
	return Vector2i(int(rq), int(rr))


static func axial_to_world(a: Vector2i, size: float) -> Vector2:
	return Vector2(size * SQRT3 * (a.x + a.y * 0.5), size * 1.5 * a.y)
