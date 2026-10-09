# Contributing

Thanks for helping. Below is everything you need to work on the add-on.

## Project layout

```
summit/                    the add-on (this folder is what gets zipped)
  __init__.py              registration
  blender_manifest.toml    extension manifest (id, version, license)
  noise.py                 vectorised Perlin, fBm, ridged multifractal, Voronoi (numpy, no bpy)
  field.py                 filters, resampling, hydraulic and thermal erosion, maps (no bpy)
  recipes.py               landform recipes (no bpy)
  generate.py              recipe -> erosion -> detail -> maps pipeline, quality levels (no bpy)
  presets.py               the landform library and horizon styles (no bpy)
  biomes.py                biome definitions: shader values and forest layers (no bpy)
  nodekit.py               node-tree building helpers and auto layout
  surface.py               the SM Terrain Surface shader group, terrain and water materials
  haze.py                  scene-wide aerial haze, read by every Summit material
  trees.py                 image-card impostor trees, library collections
  forest.py                the SM Forest geometry-node group and layer helpers
  terrain.py               terrain, surroundings, horizon and water objects; regenerate, biome,
                           water, Distant Mountains and Frame Shot
  props.py / ops.py / ui.py   properties, operators, sidebar panels
  thumbs.py, thumbs/       preview thumbnails
  cards/                   tree card atlases (rendered from Verdant) and cards.json
tools/preview_shapes.py    hillshaded contact sheet of the landforms, no Blender needed
tools/bake_tree_cards.py   renders Verdant's trees into cards/
tools/render_thumbnails.py renders the preview thumbnails
tools/render_showcase.py   renders the README images and the website's landform strip
tools/render_gpu.py        turns on the GPU for the render tools
tests/run_tests.py         headless test suite
docs/images/               images used in the README
```

## Running from source

Point Blender at the repo instead of installing the zip. Add the repo root to
*Preferences → File Paths → Script Directories*, or symlink `summit` into your
user extensions folder. Then enable the add-on.

## Tests

```
blender -b --factory-startup --python tests/run_tests.py
```

The script exits with a non-zero status if any test fails. Please run it before
opening a pull request.

## Building the zip

Run this from the repo root:

```
blender --command extension build --source-dir summit --output-dir dist
```

## Adding a landform

1. Write a recipe `fn(ctx)` in `recipes.py` that returns a height array in
   roughly 0..1.
   - Use the `ctx` helpers (`fbm`, `ridged`, `voronoi`, `warp`, `line`). They
     are seeded, and they tile automatically for the horizon ring.
   - Coordinates run 0..1 across the terrain (`ctx.X`, `ctx.Y`).
2. Add a `Shape` to `recipes.SHAPES`. It sets the erosion strength, the talus
   angle and thermal iterations, the fine detail and an optional post step.
3. Add a `Preset` to `presets.PRESETS` with its size, height, default biome,
   edge falloff and water level.
4. Tune it quickly without Blender:
   `<blender python> tools/preview_shapes.py YOUR_ID`.
5. Render its thumbnail:
   `blender -b --factory-startup --python tools/render_thumbnails.py -- YOUR_ID`.

## Adding a biome

Add a `Biome` to `biomes.BIOMES`. Its `surface` values override `biomes.BASE`,
keyed by `SM Terrain Surface` input name. Give angles in degrees. Altitudes
are fractions of the terrain height. Each `Forest` becomes one forest layer.

## Tree cards

The cards are renders of Verdant's trees. With the Verdant repository next to
this one, run:

```
blender -b --factory-startup --python tools/bake_tree_cards.py
```

To add a card, add it to `CARDS` in the script, then list it in
`trees.SPECIES`. Each tree is rendered from the front, the side and above,
and its diffuse colour and normal passes become two atlases: `<NAME>.png`
(albedo and alpha) and `<NAME>_N.png` (normals in the card's frame, and the
crown's self-occlusion in alpha). The cards hold no lighting, so the scene
lights them. Keep `HEIGHT` at 512 or so: forests are seen from afar, and the
zip stays small.

## Changing a node group

`SM Terrain Surface` and `SM Forest` are built once per file and reused.
When you change a group, bump its `GROUP_VERSION`. It is stored on the group.

- `SM Terrain Surface`: when a file holds an older version, it is renamed
  (`SM Terrain Surface v1`) and kept for the materials that use it, and new
  terrains get a fresh group. So inputs may change between versions.
- `SM Forest` has no such step yet: only add inputs at the end, and never
  rename or reorder existing ones, because users' layers store values by
  input.
