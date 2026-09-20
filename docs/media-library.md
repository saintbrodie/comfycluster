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

For videos, the controller can optionally use `ffprobe` to enrich the record with duration, frame count, frame rate, video/audio codec, container format, and bit rate. If `ffprobe` is unavailable, archival still succeeds and those enrichment fields remain empty.

## Large-library API

Gallery grids use a lightweight paginated summary API rather than returning the full rich metadata for every item:

```text
GET /api/v1/assets/search?offset=0&limit=60&sort_by=created_at&sort_order=desc
```

The response contains:

- lightweight `AssetSummaryView` items
- total authorized match count
- offset and page size
- `has_more`
- active sort field/order

Summary records include the fields needed to draw/filter cards (models, LoRAs, sampler, dimensions, duration, codecs, seeds, tags, face groups) but deliberately omit heavy/sensitive prompt text and other full provenance.

Prompt text remains searchable because the controller's private search index includes it. A user can therefore search for an old generation by prompt without the entire prompt corpus being delivered to the desktop gallery.

Full provenance is fetched only for one authorized item at a time:

```text
GET /api/v1/assets/{asset_id}
```

This is what the desktop **Details** action uses.

### SQLite search index

SQLite-backed controllers maintain a companion `asset_index` table beside the canonical JSON asset records. It stores authorization/sort/filter scalars and normalized searchable text, with indexes for:

- creation time
- private group + creation time
- owner + creation time
- media type + creation time
- video codec
- duration
- dimensions

Existing databases are backfilled idempotently when the repository opens. The canonical asset JSON remains authoritative, so this migration does not throw away full provenance.

The in-memory repository keeps a functionally equivalent fallback for development/tests.

## Search and facets

The paginated `/api/v1/assets/search` endpoint supports tenant-scoped filtering by:

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

Supported server-side sort fields include created time, filename, size, duration, width, and height.

`GET /api/v1/assets` remains as a compatibility endpoint for smaller integrations that still need rich records, but new gallery clients should use `/api/v1/assets/search` plus per-item detail requests.

`GET /api/v1/assets/facets` returns only facet values visible to the authenticated principal, including available video/audio codecs and container formats.

The desktop gallery promotes models, LoRAs, samplers, media family, video codec, group, and anonymous face group into visible filters, plus free-text search. Filtering and pagination are server-driven rather than applying to a giant locally downloaded library.

## Thumbnails and poster frames

The authorized thumbnail endpoint is:

```text
GET /api/v1/assets/{asset_id}/thumbnail?size=320
```

For images, the controller creates a JPEG thumbnail with Pillow. For videos, the controller can use `ffmpeg` to create a cached poster JPEG from an early frame. The full original is never downloaded just to populate the gallery grid.

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

## Remaining scaling work

The paginated summary/index pass removes the largest desktop/API bottleneck for 100k-class archives. The next storage-scale steps are:

- stop eagerly hydrating every canonical asset JSON record into controller memory at startup
- cache or precompute high-cardinality facet sets/counts
- cursor pagination for very deep result sets where large SQL offsets become expensive
- async background media analysis rather than enrichment in the upload request
- bounded/LRU derivative-cache eviction
- optional PostgreSQL/object-storage backend for multi-controller deployments

These changes do not require changing the tenant/privacy or provenance model described above.
