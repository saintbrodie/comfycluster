# ComfyCluster media library

ComfyCluster's Outputs surface is a private, metadata-rich media library backed by the controller asset vault. It is not a view over a shared ComfyUI output directory.

## Authorization first

Every asset inherits the user, private group, and visibility of the job that produced it. Search, facets, thumbnails, poster frames, preview proxies, metadata, and full downloads all use the same authorization boundary as the underlying asset.

A user cannot discover another private group's models, LoRAs, prompts, tags, codecs, face clusters, filenames, or other gallery metadata by using search or facet endpoints.

Platform/infrastructure administrators continue to receive only storage/queue summaries unless they separately hold content-auditor permission.

## Archived metadata

When an output is archived, the controller extracts stable provenance from the submitted Comfy API workflow and stores it with the asset:

- workflow name and caller-supplied tags
- Comfy node types
- referenced model/checkpoint files
- LoRAs
- VAEs and CLIP resources
- sampler and scheduler
- seed values
- steps and CFG
- prompt/text metadata
- image/video width and height
- host, worker, and GPU
- job runtime
- media type and file size
- anonymous face-cluster IDs when face grouping is enabled

For images, the controller verifies the actual archived image dimensions with Pillow rather than relying only on workflow hints.

For videos, the controller can optionally use `ffprobe` to enrich the record with:

- duration
- frame count when the container exposes it
- frame rate
- video codec
- audio codec
- container format
- bit rate

If `ffprobe` is unavailable, video archival still succeeds; those enrichment fields simply remain empty.

## Search and facets

`GET /api/v1/assets` supports tenant-scoped filtering by:

- free text (`q`) across filename, workflow, tags, models, LoRAs, prompts, and media codec/container metadata
- model
- LoRA
- sampler
- scheduler
- media family (`image`, `video`, etc.)
- video codec
- audio codec
- container format
- private group
- owner
- tag
- anonymous face cluster
- minimum width and height
- minimum/maximum duration

`GET /api/v1/assets/facets` returns only facet values visible to the authenticated principal, including available video/audio codecs and container formats.

The desktop gallery currently promotes models, LoRAs, samplers, media family, video codec, group, and anonymous face group into visible filters, plus free-text search.

## Thumbnails and poster frames

The authorized thumbnail endpoint is:

```text
GET /api/v1/assets/{asset_id}/thumbnail?size=320
```

For images, the controller creates a JPEG thumbnail with Pillow.

For videos, the controller can use `ffmpeg` to create a cached poster JPEG from an early frame. The full original is never downloaded just to populate the gallery grid.

If `ffmpeg` is unavailable, video cards remain usable as metadata placeholders and the original can still be opened.

## Lightweight video previews

Videos expose a separate authorized proxy endpoint:

```text
GET /api/v1/assets/{asset_id}/preview
```

The controller uses `ffmpeg` to create a cached short H.264 MP4 proxy. The default target is an 8-second, maximum-720px, muted preview encoded with `libx264` and `+faststart`.

The desktop **Preview** button downloads/opens this small proxy instead of the full archived original. **Open** still retrieves the full asset.

Controller settings:

```text
COMFYCLUSTER_FFPROBE_PATH=ffprobe
COMFYCLUSTER_FFMPEG_PATH=ffmpeg
COMFYCLUSTER_VIDEO_PREVIEW_SECONDS=8
COMFYCLUSTER_VIDEO_PREVIEW_MAX_SIZE=720
```

The path settings may point to absolute executables or command names discoverable on `PATH`.

Poster frames and proxy files live under controller-owned derivative caches (`.thumbnails` and `.previews`) and are deleted when their source asset is deleted or removed by retention cleanup.

## Anonymous face grouping

Face grouping is deliberately different from face identification.

ComfyCluster core supports anonymous group-local cluster IDs such as:

```text
face_0123456789abcdef
```

It does **not** store a person's name in a face cluster, provide a "who is this?" API, or merge face clusters across private groups.

Face grouping is disabled by default:

```json
{
  "policy": {
    "face_grouping_enabled": false
  }
}
```

A private group must explicitly opt in before an agent/analyzer may attach face-cluster metadata to its assets. The controller rejects face grouping updates for groups that have not opted in.

### Analyzer boundary

The core controller does not currently bundle a face detector/embedding model. This is intentional:

- face embeddings are sensitive biometric-derived data
- enterprises may have different approved models and retention requirements
- some environments may prohibit biometric processing entirely
- a large inference dependency does not belong in the controller process

The intended architecture is:

```text
Authorized private asset
        |
        v
Opt-in face analyzer
(detector + embedding model)
        |
        v
Group-scoped clustering
        |
        v
opaque face_... cluster IDs
        |
        v
ComfyCluster asset metadata
```

The analyzer should run only for groups with `face_grouping_enabled=true`, should never send raw face data outside the approved environment, and should avoid persisting embeddings unless an organization explicitly configures and protects such storage.

## Scaling notes

The current prototype returns rich `AssetView` records including prompt metadata. For very large libraries, the next storage/API iteration should add:

- paginated `AssetSummaryView` for gallery grids
- detail-on-demand for large prompt/provenance payloads
- server-side pagination/sort
- database indexes for frequently used facets
- async background media analysis rather than enrichment in the upload request
- bounded derivative-cache eviction

Those changes do not require changing the privacy or provenance model described above.
