# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the tool scripts on the GPU.

With --factory-startup Cycles has no compute backend enabled, so
``scene.cycles.device = "GPU"`` alone silently renders on the CPU. This
picks the best backend present (OptiX, then CUDA, HIP, oneAPI, Metal) and
enables its GPU devices only.
"""

import bpy

BACKENDS = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")


def enable(scene):
    """Enable the best GPU backend for Cycles; returns its name, or None (CPU)."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in BACKENDS:
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == backend]
        if not gpus:
            continue
        for d in prefs.devices:
            d.use = d in gpus
        scene.cycles.device = "GPU"
        if backend == "OPTIX":
            scene.cycles.denoiser = "OPTIX"
        if hasattr(scene.cycles, "denoising_use_gpu"):
            scene.cycles.denoising_use_gpu = True
        print("GPU:", backend, ", ".join(d.name for d in gpus))
        return backend
    scene.cycles.device = "CPU"
    print("GPU: none found, rendering on the CPU")
    return None
