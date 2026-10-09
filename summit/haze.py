# SPDX-License-Identifier: GPL-3.0-or-later
"""Aerial perspective shared by every Summit material.

Distant land fades into the colour of the air, more so low down where the
air is thick. Terrains, horizons, forests and water all read the same
scene settings (custom properties on the scene, through the shader
Attribute node's View Layer mode), so a forest 5 km away fades exactly
like the ground under it. A volume would do this physically but slowly,
and a world volume would also swallow the sky.
"""

DENSITY = "sm_haze_density"     # per kilometre at sea level
HEIGHT = "sm_haze_height"       # metres; the haze halves every this much higher
COLOR = "sm_haze_color"
DEFAULTS = {DENSITY: 0.08, HEIGHT: 1500.0, COLOR: (0.68, 0.76, 0.86)}


def ensure(scene, density=None):
    """Give the scene haze settings if it has none; returns True if it added them."""
    if DENSITY in scene:
        return False
    scene[DENSITY] = float(DEFAULTS[DENSITY] if density is None else density)
    scene[HEIGHT] = DEFAULTS[HEIGHT]
    scene[COLOR] = DEFAULTS[COLOR]
    ui = scene.id_properties_ui(DENSITY)
    ui.update(min=0.0, soft_max=2.0, description="Aerial haze per kilometre, at sea level")
    scene.id_properties_ui(HEIGHT).update(min=1.0, subtype="DISTANCE",
                                          description="The haze halves every this much higher")
    scene.id_properties_ui(COLOR).update(subtype="COLOR", min=0.0, max=1.0,
                                         description="Colour of the air in the distance")
    return True


def mix(b, shader, amount=1.0):
    """Fade a shader into the scene's haze colour with distance. b: a nodekit NB; returns the shader socket."""
    def attr(name, key="Fac"):
        return b.out(b.node("ShaderNodeAttribute", attribute_name=name, attribute_type="VIEW_LAYER"), key)

    geo = b.node("ShaderNodeNewGeometry")
    dist = b.out(b.node("ShaderNodeCameraData"), "View Distance")
    _wx, _wy, wz = b.sep(b.out(geo, "Position"))
    _ix, _iy, iz = b.sep(b.out(geo, "Incoming"))
    # density at the ray's mean altitude: thick in the valleys, thin around the summits
    mean_z = b.math("MAXIMUM", b.add(wz, b.mul(b.mul(iz, dist), 0.5)), 0.0)
    height = b.math("MAXIMUM", attr(HEIGHT), 1.0)
    thin = b.math("EXPONENT", b.mul(b.math("DIVIDE", mean_z, height), -0.693))
    density = b.mul(b.mul(attr(DENSITY), amount), thin)
    fac = b.inv(b.math("EXPONENT", b.mul(b.mul(dist, density), -0.001)))
    emit = b.node("ShaderNodeEmission", {"Color": attr(COLOR, "Color"), "Strength": 1.0})
    m = b.node("ShaderNodeMixShader", {0: fac, 1: shader, 2: b.out(emit)})
    return b.out(m)
