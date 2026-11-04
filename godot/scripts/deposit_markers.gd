class_name DepositMarkers
extends MultiMeshInstance3D
## Floating crystal markers for known deposits, coloured by resource type.
## Markers grow as the camera zooms out so they stay readable.

const SHADER := """
shader_type spatial;
render_mode unshaded, cull_disabled;
varying vec3 n;
void vertex() {
	n = NORMAL;
	VERTEX.y += sin(TIME * 2.0 + float(INSTANCE_ID) * 1.7) * 0.25;
}
void fragment() {
	float l = 0.7 + 0.3 * dot(normalize(n), normalize(vec3(-0.5, 0.8, 0.4)));
	ALBEDO = COLOR.rgb * l;
}
"""

var _items: Array = []  ## [Vector3 ground position, Color, float size]
var _view_scale := 1.0


func _ready() -> void:
	multimesh = MultiMesh.new()
	multimesh.transform_format = MultiMesh.TRANSFORM_3D
	multimesh.use_colors = true
	multimesh.mesh = _octahedron()
	var mat := ShaderMaterial.new()
	var sh := Shader.new()
	sh.code = SHADER
	mat.shader = sh
	material_override = mat
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF


## items: Array of [ground position, colour, base size in metres]
func set_items(items: Array) -> void:
	_items = items
	_rebuild()


func set_view_distance(distance: float) -> void:
	var s := clampf(distance / 450.0, 1.0, 12.0)
	if absf(s / _view_scale - 1.0) > 0.08:
		_view_scale = s
		_rebuild()


func _rebuild() -> void:
	multimesh.instance_count = _items.size()
	var lo := Vector3(INF, INF, INF)
	var hi := -lo
	for i in _items.size():
		var pos: Vector3 = _items[i][0]
		var size: float = _items[i][2] * _view_scale
		var origin := pos + Vector3(0, size * 1.6 + 4.0, 0)
		multimesh.set_instance_transform(i, Transform3D(Basis.from_scale(Vector3.ONE * size), origin))
		multimesh.set_instance_color(i, _items[i][1])
		lo = lo.min(origin)
		hi = hi.max(origin)
	if _items.size() > 0:
		var pad := Vector3.ONE * 80.0 * _view_scale
		multimesh.custom_aabb = AABB(lo - pad, hi - lo + pad * 2.0)


static func _octahedron() -> ArrayMesh:
	var top := Vector3(0, 1.6, 0)
	var bottom := Vector3(0, -1.6, 0)
	var ring := [Vector3(1, 0, 0), Vector3(0, 0, 1), Vector3(-1, 0, 0), Vector3(0, 0, -1)]
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for i in 4:
		var a: Vector3 = ring[i]
		var b: Vector3 = ring[(i + 1) % 4]
		for tri in [[top, b, a], [bottom, a, b]]:
			var nrm: Vector3 = (tri[0] + tri[1] + tri[2]).normalized()  # outward
			for v in tri:
				st.set_normal(nrm)
				st.add_vertex(v)
	return st.commit()
