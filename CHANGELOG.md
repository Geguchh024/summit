# Changelog

## 0.2.0

A realism pass, worked against real mountain photographs
(see [docs/reference-notes.md](docs/reference-notes.md)).

- Scenes, not tiles. Every terrain now comes with **surroundings**: low hills
  and forest out to twice its width, joined to its mesh, so a camera inside
  the landscape never sees an edge. **Distant Mountains** adds a matching
  horizon ring in the same biome.
- **Frame Shot** puts the scene camera on a well-composed view. It tries many
  spots and headings, and scores what each would see: land filling about two
  thirds of the frame, layered depth, a varied skyline, water, side light,
  and no wall in front of the lens. Each click tries the next best angle.
- **Scene haze**: one aerial perspective setting for the whole scene, read by
  terrains, horizons, forests and water alike, denser in the valleys.
- **Trees relit**: the Verdant cards are re-baked as albedo plus the leaves'
  own normals and crown occlusion, so the scene's sun and sky light them.
  No more black forests or light seams between crossed cards.
- **Terrain detail**: branching gullies below the simulation scale, a baked
  ambient-occlusion map, and broad buttress and fluting relief on big walls,
  visible from kilometres away.
- **Alpine Peak** rebuilt around arêtes, side spurs and cirques, with a
  concave profile: steep summit, grassy lower slopes.
- **Shader**: fresh snow on ledges and in couloirs below the snowline,
  boulders in the grass, broad grass patches, sunlit-crown canopy tones,
  paler scree, muted talus between vivid cliff bands, and meadows and
  clearings in the forests.
- Biome colours retuned: brighter rock, paler limestone and orange Dolomite
  walls, saturated alpine grass.
- The render tools use the GPU (OptiX, CUDA, HIP, oneAPI or Metal).

## 0.1.0

First release.

- 17 eroded landforms in four categories: mountains, hills, desert and
  landscapes.
- Hydraulic (droplet) and thermal erosion, with flow, sediment and cavity
  maps baked for the shader.
- 14 biomes on one shared terrain shader with rock, strata, scree, ground
  cover, forest floor, snow, beaches and distance-faded close-up detail.
- Forests of image cards baked from Verdant's trees, in five species, with
  tree lines, slope limits and natural clumping.
- A seamless horizon ring of distant mountains, in four styles.
- Water planes that drive the shoreline.
- Four quality levels, and regeneration that keeps the material and forests.
