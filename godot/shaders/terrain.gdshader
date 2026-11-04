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

// Global H3 hexes: local hex index per cell (RG8 = low/high byte).
uniform sampler2D hex_tex : filter_nearest, repeat_disable;
uniform bool show_hex = true;
uniform int hover_hex = -1;
// Per-hex state for this player, texel (idx % 256, idx / 256):
// 0 unknown, 1 frontier (scoutable), 2 scouted, 3 claimed, 4 home.
uniform sampler2D hex_state_tex : filter_nearest, repeat_disable;
uniform bool fog_of_war = true;
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

int hex_at(ivec2 c) {
	c = clamp(c, ivec2(0), ivec2(grid_size) - 1);
	vec2 v = texelFetch(hex_tex, c, 0).rg;
	return int(v.r * 255.0 + 0.5) + 256 * int(v.g * 255.0 + 0.5);
}

// Distance in cells from point (cell + f) to the nearest border with another
// hex, looking up to two cells away in each axis direction (capped at 2).
float hex_edge(ivec2 cell, vec2 f, int id) {
	float e = 2.0;
	for (int k = 1; k <= 2; k++) {
		float base = float(k - 1);
		if (hex_at(cell - ivec2(k, 0)) != id) { e = min(e, base + f.x); }
		if (hex_at(cell + ivec2(k, 0)) != id) { e = min(e, base + 1.0 - f.x); }
		if (hex_at(cell - ivec2(0, k)) != id) { e = min(e, base + f.y); }
		if (hex_at(cell + ivec2(0, k)) != id) { e = min(e, base + 1.0 - f.y); }
	}
	return e;
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

	// Hex grid (global H3 hexes; borders follow the pixel grid).
	int hid = hex_at(cell);
	float to_edge = hex_edge(cell, fract(cf), hid);
	int state = int(texelFetch(hex_state_tex, ivec2(hid % 256, hid / 256), 0).r * 255.0 + 0.5);
	if (fog_of_war && state < 2) {
		// Unscouted: the land is visible, but faded and cold.
		float luma = dot(col, vec3(0.3, 0.55, 0.15));
		vec3 fogged = mix(vec3(luma), vec3(0.42, 0.5, 0.56), 0.35);
		col = state == 1 ? mix(col, fogged, 0.5) * 0.9 : mix(col, fogged, 0.75) * 0.7;
	}
	if (state == 4) {
		col = mix(col, home_colour, to_edge < 1.6 ? 0.9 : 0.16);
	} else if (state == 3) {
		col = mix(col, claim_colour, to_edge < 1.6 ? 0.85 : 0.14);
	} else if (show_hex && to_edge < 0.4) {
		col *= (cls == SEA) ? 0.92 : 0.8;
	}
	if (hid == hover_hex) {
		col = mix(col, vec3(1.0), to_edge < 1.2 ? 0.7 : 0.1);
	}

	ALBEDO = col;
}

void light() {
	// Banded lambert for a pixel-art look.
	float ndl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
	ndl = floor(ndl * light_bands + 0.5) / light_bands;
	DIFFUSE_LIGHT += ndl * ATTENUATION * LIGHT_COLOR / PI;
}
