shader_type spatial;
render_mode cull_back, diffuse_lambert, specular_disabled;

// Buildings are one box per run of same-height cells (see terrain.gd).
// Roof colour comes from the instance colour; walls get a floor/window grid.

uniform float floor_height = 3.0;
uniform float window_spacing = 3.3;
uniform vec3 wall_tint : source_color = vec3(0.88, 0.85, 0.78);
uniform vec3 glass : source_color = vec3(0.32, 0.4, 0.48);
uniform vec3 lit_glass : source_color = vec3(1.0, 0.86, 0.55);

varying vec3 local_normal;

float hash12(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

void vertex() {
	local_normal = NORMAL;
}

void fragment() {
	vec3 wpos = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
	vec3 roof = COLOR.rgb;
	if (local_normal.y > 0.5) {
		ALBEDO = roof;
	} else {
		vec3 wall = mix(roof, wall_tint, 0.65);
		float u = abs(local_normal.x) > 0.5 ? wpos.z : wpos.x;
		float fl = wpos.y / floor_height;
		float fy = fract(fl);
		float fx = fract(u / window_spacing);
		if (fy > 0.35 && fy < 0.8 && fx > 0.28 && fx < 0.72) {
			float h = hash12(vec2(floor(u / window_spacing), floor(fl)));
			wall = h > 0.93 ? lit_glass : glass;
		}
		ALBEDO = wall;
	}
}

void light() {
	float ndl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
	ndl = floor(ndl * 4.0 + 0.5) / 4.0;
	DIFFUSE_LIGHT += ndl * ATTENUATION * LIGHT_COLOR / PI;
}
