shader_type spatial;
render_mode cull_back, diffuse_lambert, specular_disabled;

// Voxel faces arrive as MultiMesh instances (see server/worldgame/mesher.py).
// Instance colour = material colour (linear); alpha = material id / 255.

uniform float cell = 3.115;         // metres per voxel
uniform float y_offset = 0.0;       // metres the world node is shifted down (sea level at y = 0)
// Per material id: 0 plain, 1 wall with windows, 2 water, 3 foliage, 4 glass, 5 roof, 6 road
uniform sampler2D flags_tex : filter_nearest, repeat_disable;
uniform float light_bands = 5.0;

varying float mat_id;

float hash13(vec3 p) {
	p = fract(p * 0.1031);
	p += dot(p, p.zyx + 31.32);
	return fract((p.x + p.y) * p.z);
}

void vertex() {
	mat_id = COLOR.a * 255.0;
}

void fragment() {
	vec3 wp = (INV_VIEW_MATRIX * vec4(VERTEX, 1.0)).xyz;
	vec3 wn = normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);
	vec3 vp = (wp + vec3(0.0, y_offset, 0.0)) / cell;
	vec3 voxel = floor(vp - wn * 0.5);
	float n = hash13(voxel);
	int flag = int(texelFetch(flags_tex, ivec2(int(mat_id + 0.5), 0), 0).r * 255.0 + 0.5);
	vec3 col = COLOR.rgb;
	bool side = abs(wn.y) < 0.5;
	vec2 f = fract(vec2(abs(wn.x) > 0.5 ? vp.z : vp.x, vp.y));

	if (flag == 2) {                                   // water
		float wave = hash13(voxel + floor(TIME * 1.5) * 13.0);
		col *= 0.95 + 0.05 * n;
		if (wave > 0.992) {
			col = mix(col, vec3(0.9, 0.95, 1.0), 0.5);
		}
	} else if (flag == 3) {                            // foliage
		col *= 0.7 + 0.5 * n;
	} else if (flag == 1 && side) {                    // walls: one window per voxel face
		col *= 0.92 + 0.12 * n;
		if (f.x > 0.28 && f.x < 0.72 && f.y > 0.3 && f.y < 0.75) {
			col = hash13(voxel + 7.0) > 0.94 ? vec3(0.9, 0.7, 0.3) : vec3(0.05, 0.08, 0.12);
		}
	} else if (flag == 4 && side) {                    // glazing bars
		if (f.x < 0.06 || f.y < 0.06 || abs(f.x - 0.5) < 0.03) {
			col *= 0.45;
		}
	} else if (flag == 5) {                            // roofs: tile courses
		col *= (fract(vp.z * 2.0) < 0.15 || fract(vp.x * 2.0) < 0.08) ? 0.8 : 0.95 + 0.1 * n;
	} else if (flag == 6) {                            // roads stay flat
		col *= 0.96 + 0.06 * n;
	} else {
		col *= 0.88 + 0.22 * n;
	}
	ALBEDO = col;
}

void light() {
	float ndl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
	ndl = floor(ndl * light_bands + 0.5) / light_bands;
	DIFFUSE_LIGHT += ndl * ATTENUATION * LIGHT_COLOR / PI;
}
