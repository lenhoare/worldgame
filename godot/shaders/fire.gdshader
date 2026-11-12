shader_type spatial;
render_mode unshaded, cull_disabled, blend_add;

varying vec3 lp;

void vertex() {
	lp = VERTEX;
	VERTEX.y += 0.15 * sin(TIME * 9.0 + float(INSTANCE_ID));
}

void fragment() {
	float f = 0.6 + 0.4 * sin(TIME * 14.0 + lp.x * 9.0 + lp.z * 7.0 + lp.y * 5.0);
	ALBEDO = mix(vec3(1.0, 0.25, 0.02), vec3(1.0, 0.8, 0.2), f) * (0.5 + 0.5 * f);
	ALPHA = 0.55;
}
