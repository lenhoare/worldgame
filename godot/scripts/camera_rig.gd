class_name CameraRig
extends Node3D
## Orbit / RTS camera around a focus point on the ground, with smoothing.

const MIN_DISTANCE := 120.0
const MAX_DISTANCE := 26000.0
const MIN_PITCH := deg_to_rad(12.0)
const MAX_PITCH := deg_to_rad(88.0)

var camera: Camera3D
var bounds := Rect2(0, 0, 1000, 1000)  ## focus limits on x/z
var ground_height: Callable = func(_x: float, _z: float) -> float: return 0.0

var focus := Vector2.ZERO  ## x/z
var yaw := 0.0  ## 0 = looking north
var pitch := deg_to_rad(38.0)
var distance := 2500.0

var _focus := Vector2.ZERO
var _yaw := 0.0
var _pitch := pitch
var _distance := distance
var _ground := 0.0


func _ready() -> void:
	camera = Camera3D.new()
	camera.fov = 40.0
	camera.far = 80000.0
	add_child(camera)


func snap() -> void:
	_focus = focus
	_yaw = yaw
	_pitch = pitch
	_distance = distance
	_ground = ground_height.call(focus.x, focus.y)
	_apply()


func _process(delta: float) -> void:
	var k := 1.0 - exp(-delta * 9.0)
	_focus = _focus.lerp(focus, k)
	_yaw = lerp_angle(_yaw, yaw, k)
	_pitch = lerpf(_pitch, pitch, k)
	_distance = exp(lerpf(log(_distance), log(distance), k))
	_ground = lerpf(_ground, ground_height.call(_focus.x, _focus.y), k)
	_apply()


func _apply() -> void:
	var target := Vector3(_focus.x, _ground, _focus.y)
	var dir := Vector3(sin(_yaw) * cos(_pitch), sin(_pitch), cos(_yaw) * cos(_pitch))
	camera.position = target + dir * _distance
	camera.look_at(target, Vector3.UP)
	camera.near = clampf(_distance * 0.004, 0.5, 30.0)


## Screen-space vectors along the ground for the current yaw.
func _right() -> Vector2:
	return Vector2(cos(yaw), -sin(yaw))


func _forward() -> Vector2:
	return Vector2(-sin(yaw), -cos(yaw))


## Drag the ground: `pixels` is mouse motion in viewport pixels.
func pan_pixels(pixels: Vector2, viewport_height: float) -> void:
	var mpp := 2.0 * distance * tan(deg_to_rad(camera.fov) * 0.5) / maxf(1.0, viewport_height)
	var move := -_right() * pixels.x * mpp + _forward() * pixels.y * mpp / maxf(0.35, sin(pitch))
	set_focus(focus + move)


## Move in camera-relative directions (x = right, y = forward), in metres.
func pan_metres(v: Vector2) -> void:
	set_focus(focus + _right() * v.x + _forward() * v.y)


func set_focus(p: Vector2) -> void:
	focus = p.clamp(bounds.position, bounds.end)


func orbit(pixels: Vector2) -> void:
	yaw -= pixels.x * 0.006
	pitch = clampf(pitch + pixels.y * 0.004, MIN_PITCH, MAX_PITCH)


func zoom(factor: float) -> void:
	distance = clampf(distance * factor, MIN_DISTANCE, MAX_DISTANCE)
