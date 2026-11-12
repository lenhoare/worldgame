class_name Giant
extends Node3D
## Placeholder 12 m (40 ft) salvage giant, built from boxes, for judging scale
## against real buildings. Faces +z (south) by default.

const PAINT := Color("#c9a227")
const DARK := Color("#3a3f44")
const RUST := Color("#8a4b2a")
const GLOW := Color("#5ff0ff")

var paint_colour := PAINT   ## set before adding to the tree to tint this giant

var _head: Node3D
var _body: Node3D
var _visor: StandardMaterial3D
var _core: StandardMaterial3D
var _t := 0.0


func _ready() -> void:
	var paint := _mat(paint_colour)
	var dark := _mat(DARK)
	var rust := _mat(RUST)
	_visor = _glow_mat()
	_core = _glow_mat()

	for side in [-1.0, 1.0]:
		_box(self, Vector3(1.8, 0.8, 2.6), Vector3(side * 1.25, 0.4, 0.3), dark)  # foot
		_box(self, Vector3(1.3, 2.6, 1.4), Vector3(side * 1.25, 2.1, 0.0), paint)  # shin
		_box(self, Vector3(1.0, 0.8, 1.0), Vector3(side * 1.25, 3.7, 0.0), dark)  # knee
		_box(self, Vector3(1.4, 2.0, 1.5), Vector3(side * 1.25, 5.0, 0.0), paint)  # thigh

	_body = Node3D.new()
	add_child(_body)
	_box(_body, Vector3(3.6, 1.2, 2.0), Vector3(0, 6.2, 0), dark)  # pelvis
	_box(_body, Vector3(4.6, 3.4, 2.8), Vector3(0, 8.5, 0), paint)  # torso
	_box(_body, Vector3(3.0, 1.6, 0.3), Vector3(0, 8.9, 1.5), rust)  # chest plate
	_box(_body, Vector3(2.4, 2.6, 1.2), Vector3(0, 8.7, -1.9), dark)  # reactor pack
	_box(_body, Vector3(1.0, 1.0, 0.2), Vector3(0, 8.7, -2.55), _core)  # reactor core
	for side in [-1.0, 1.0]:
		_box(_body, Vector3(1.6, 1.4, 1.8), Vector3(side * 3.0, 9.6, 0), rust)  # shoulder
		_box(_body, Vector3(1.0, 2.4, 1.1), Vector3(side * 3.1, 7.9, 0), paint)  # upper arm
		_box(_body, Vector3(1.1, 2.2, 1.2), Vector3(side * 3.1, 5.7, 0.1), paint)  # forearm
		_box(_body, Vector3(1.3, 1.1, 1.3), Vector3(side * 3.1, 4.2, 0.1), dark)  # hand

	_head = Node3D.new()
	_head.position = Vector3(0, 10.3, 0)
	_body.add_child(_head)
	_box(_head, Vector3(0.9, 0.5, 0.9), Vector3(0, 0.25, 0), dark)  # neck
	_box(_head, Vector3(2.2, 1.6, 2.2), Vector3(0, 1.2, 0), paint)  # head
	_box(_head, Vector3(1.8, 0.4, 0.15), Vector3(0, 1.3, 1.12), _visor)  # visor
	_box(_head, Vector3(0.15, 1.0, 0.15), Vector3(0.7, 2.4, -0.4), dark)  # antenna


func _process(delta: float) -> void:
	_t += delta
	_body.position.y = sin(_t * 1.3) * 0.08
	_head.rotation.y = sin(_t * 0.45) * 0.5
	var blink := 1.0 if fmod(_t, 4.0) > 0.12 else 0.2
	_visor.albedo_color = GLOW * blink
	_core.albedo_color = GLOW * (0.7 + 0.3 * sin(_t * 3.0))


func _mat(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.roughness = 1.0
	return m


func _glow_mat() -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.albedo_color = GLOW
	return m


func _box(parent: Node3D, size: Vector3, pos: Vector3, mat: Material) -> void:
	var mi := MeshInstance3D.new()
	var b := BoxMesh.new()
	b.size = size
	mi.mesh = b
	mi.position = pos
	mi.material_override = mat
	parent.add_child(mi)
