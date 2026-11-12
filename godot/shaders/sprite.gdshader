shader_type spatial;
render_mode unshaded, cull_disabled;

// Camera-facing item sprites from one atlas. INSTANCE_CUSTOM.x = cell index,
// INSTANCE_CUSTOM.y = 1 when burning (flickers).

uniform sampler2D atlas : source_color, filter_nearest, repeat_disable;
uniform float columns = 16.0;
uniform float rows = 6.0;
uniform float brightness = 1.0;

varying vec2 cell_xy;
varying float burning;

void vertex() {
	float idx = INSTANCE_CUSTOM.x;
	cell_xy = vec2(mod(idx, columns), floor(idx / columns));
	burning = INSTANCE_CUSTOM.y;
	float sc = length(MODEL_MATRIX[0].xyz);
	MODELVIEW_MATRIX = VIEW_MATRIX * mat4(INV_VIEW_MATRIX[0] * sc, INV_VIEW_MATRIX[1] * sc,
			INV_VIEW_MATRIX[2] * sc, MODEL_MATRIX[3]);
}

void fragment() {
	vec4 c = texture(atlas, (cell_xy + UV) / vec2(columns, rows));
	if (c.a < 0.5) {
		discard;
	}
	vec3 col = c.rgb * brightness;
	if (burning > 0.5) {
		col = mix(col, vec3(1.0, 0.45, 0.1), 0.5 + 0.3 * sin(TIME * 12.0));
	}
	ALBEDO = col;
}
