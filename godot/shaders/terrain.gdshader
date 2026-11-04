shader_type spatial;
render_mode cull_back, diffuse_lambert, specular_disabled;

// Land-cover class ids (must match CLASSES in tools/mapgen/generate.py).
const int SEA = 0;
const int BEACH = 1;
const int WATER = 2;
const int URBAN = 3;
const int PARK = 6;
const int GRASS = 7;
const int FARMLAND = 8;
const int WOOD = 9;
const int SCRUB = 10;
const int GOLF = 13;
const int BUILDING = 20;

uniform sampler2D height_tex : filter_linear, repeat_disable;
uniform sampler2D cover_tex : filter_nearest, repeat_disable;
uniform sampler2D palette_tex : source_color, filter_nearest, repeat_disable;
uniform vec2 grid_size;
uniform float cell_size = 10.0;
uniform float height_scale = 1.5;
uniform float light_bands = 5.0;
uniform vec3 shade_dir = vec3(-0.45, 0.6, 0.65);  // pixel hillshade, from the south-west
uniform float shade_strength = 2.2;

uniform float hex_size = 250.0;
uniform bool show_hex = true;
uniform vec2 hover_hex = vec2(100000.0);
uniform vec2 home_hex = vec2(100000.0);
uniform int claimed_count = 0;
uniform vec2 claimed[64];
uniform vec3 home_colour : source_color = vec3(1.0, 0.78, 0.25);
uniform vec3 claim_colour : source_color = vec3(0.35, 0.85, 1.0);

varying vec3 world_pos;
varying vec3 world_normal;

float hash12(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

// Height at a cell-corner coordinate (bilinear between cell centres).
float corner_height(vec2 c) {
	return textureLod(height_tex, clamp(c, vec2(0.0), grid_size) / grid_size, 0.0).r;
}

vec2 hex_round(vec2 h) {
	vec3 c = vec3(h.x, h.y, -h.x - h.y);
	vec3 rc = floor(c + 0.5);
	vec3 d = abs(rc - c);
	if (d.x > d.y && d.x > d.z) {
		rc.x = -rc.y - rc.z;
	} else if (d.y > d.z) {
		rc.y = -rc.x - rc.z;
	}
	return rc.xy;
}

void vertex() {
	vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	vec2 c = wp.xz / cell_size;
	float h = corner_height(c);
	VERTEX.y = h * height_scale;
	float e = 2.0;
	float hl = corner_height(c - vec2(e, 0.0));
	float hr = corner_height(c + vec2(e, 0.0));
	float hn = corner_height(c - vec2(0.0, e));
	float hs = corner_height(c + vec2(0.0, e));
	NORMAL = normalize(vec3((hl - hr) * height_scale, 2.0 * e * cell_size, (hn - hs) * height_scale));
	world_pos = vec3(wp.x, VERTEX.y, wp.z);
	world_normal = NORMAL;
}

void fragment() {
	vec2 cf = world_pos.xz / cell_size;
	if (cf.x < 0.0 || cf.y < 0.0 || cf.x >= grid_size.x || cf.y >= grid_size.y) {
		discard;
	}
	ivec2 cell = ivec2(floor(cf));
	int cls = int(texelFetch(cover_tex, cell, 0).r * 255.0 + 0.5);
	vec3 col = texelFetch(palette_tex, ivec2(cls, 0), 0).rgb;
	float n = hash12(vec2(cell));

	// Per-cell pixel-art texture.
	if (cls == WOOD) {
		col *= 0.72 + 0.4 * n;
	} else if (cls == FARMLAND) {
		col *= ((cell.x + cell.y) % 3 == 0) ? 0.9 : 1.0;
		col *= 0.97 + 0.06 * n;
	} else if (cls == GRASS || cls == PARK || cls == GOLF || cls == SCRUB) {
		col *= 0.94 + 0.12 * n;
	} else if (cls == URBAN || cls == BUILDING) {
		col *= 0.9 + 0.14 * n;
	} else if (cls == BEACH) {
		col *= 0.95 + 0.1 * n;
	} else if (cls == SEA || cls == WATER) {
		float wave = hash12(vec2(cell) + floor(TIME * 1.5) * 17.0);
		if (wave > 0.994) {
			col = mix(col, vec3(0.9, 0.95, 1.0), 0.6);
		}
		col *= 0.97 + 0.04 * n;
	}

	// Quantized hillshade so slopes read clearly at any sun angle.
	if (cls != SEA) {
		vec3 wn = normalize(world_normal);
		float slope_light = dot(wn, normalize(shade_dir)) - normalize(shade_dir).y;
		float shade = clamp(1.0 + slope_light * shade_strength, 0.65, 1.22);
		col *= floor(shade * 10.0 + 0.5) / 10.0;
	}

	// Hex claim grid.
	float q = (0.57735027 * world_pos.x - world_pos.z / 3.0) / hex_size;
	float r = (0.66666667 * world_pos.z) / hex_size;
	vec2 ax = hex_round(vec2(q, r));
	vec2 centre = vec2(hex_size * 1.7320508 * (ax.x + ax.y * 0.5), hex_size * 1.5 * ax.y);
	vec2 d = abs(world_pos.xz - centre);
	float to_edge = hex_size * 0.8660254 - max(d.x, 0.5 * d.x + 0.8660254 * d.y);
	float line_w = cell_size * 0.8;

	bool claim = false;
	for (int i = 0; i < 64; i++) {
		if (i >= claimed_count) {
			break;
		}
		if (all(equal(ax, claimed[i]))) {
			claim = true;
		}
	}
	if (all(equal(ax, home_hex))) {
		col = mix(col, home_colour, to_edge < line_w * 2.0 ? 0.9 : 0.16);
	} else if (claim) {
		col = mix(col, claim_colour, to_edge < line_w * 2.0 ? 0.85 : 0.14);
	} else if (show_hex && to_edge < line_w) {
		col *= (cls == SEA) ? 0.92 : 0.8;
	}
	if (all(equal(ax, hover_hex))) {
		col = mix(col, vec3(1.0), to_edge < line_w * 1.5 ? 0.7 : 0.1);
	}

	ALBEDO = col;
}

void light() {
	// Banded lambert for a pixel-art look.
	float ndl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
	ndl = floor(ndl * light_bands + 0.5) / light_bands;
	DIFFUSE_LIGHT += ndl * ATTENUATION * LIGHT_COLOR / PI;
}
