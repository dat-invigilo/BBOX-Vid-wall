# Migrating the Video Wall to mediamtx - Design Notes

## Problem

The current wall (`video_wall.py` + `web_server.py`) decodes every RTSP stream
in Python: `FFmpegStreamHandler` spawns one `ffmpeg` subprocess per stream and
reads raw BGR24 frames, `VideoWallDisplay.get_wall_frame()` composites all
cells with PIL/numpy, and `web_server.py` re-encodes the composite to JPEG for
an MJPEG multipart response - all repeated at ~30fps for every stream, in a
single process capped at 2 CPUs / 2GB (`docker-compose.yml`).

On top of that, each consumer of a camera opens its **own** upstream RTSP
connection and does its own decode: the wall's `FFmpegStreamHandler` and
`ffmpeg_recorder.py`'s `FFmpegStreamRecorder` each independently connect to
the same source/bbox URL. With N cameras x 2 variants (source/bbox) x 2
consumers (display + recording), the number of concurrent decodes can be much
larger than the number of cameras.

## Approach

Replace server-side decode+composite+re-encode with
[mediamtx](https://github.com/bluenviron/mediamtx) as a relay/remux layer, and
move compositing into the browser.

- mediamtx does **not** decode or draw a grid - it just pulls each RTSP
  source once and re-serves it (RTSP/HLS/WebRTC) to any number of readers
  without re-encoding.
- The grid becomes a CSS grid of `<video>` elements in the frontend, each
  pointed at a mediamtx path. The browser's hardware video decoder does the
  per-cell decode instead of one Python process doing it in software.
- All consumers of a given camera (wall display, fullscreen view, recorder)
  read from mediamtx instead of opening independent connections to the
  camera - one upstream pull per camera path, fanned out cheaply.

## Protocol: HLS

Decided against WebRTC: WebRTC pass-through requires the camera's H264
stream to be WebRTC-compatible, and DeepStream RTSP sinks may not emit a
compatible profile - if not, mediamtx has to transcode, which reintroduces
per-stream CPU cost server-side (the exact problem we're trying to remove).

HLS/LL-HLS remuxes the existing H264/AAC into segments with no re-encode,
regardless of source profile, and plays natively via `<video>` + hls.js.
Latency is a few seconds, which is acceptable for this wall (confirmed:
a couple seconds of delay from real-time is fine).

## Plan

### 1. mediamtx service

Add mediamtx as a sidecar container in `docker-compose.yml`, on host network
(matching the existing `video-wall` service) so it can reach the same RTSP
sources/sinks.

### 2. Path provisioning - dynamic, not static config

Camera list comes from `parse_deepstream_uris()` and can change at runtime
(BBOX toggle swaps source <-> bbox per stream, `api_reparse_configs` picks up
config changes). Static `mediamtx.yml` path definitions don't fit this -
use mediamtx's REST API to create/update paths on demand, driven from the
same places `web_server.py` currently spawns `FFmpegStreamHandler`s:
`api_start`, `api_set_config` (bbox toggle), `update_stream`.

### 3. Backend changes

- `video_wall.py`: `VideoWallDisplay` no longer holds `FFmpegStreamHandler`s
  or composites frames. It becomes responsible for mapping grid cell index ->
  mediamtx path name, and pushing path create/update calls to mediamtx's API
  when streams start or the BBOX toggle changes.
- `web_server.py`: drop `generate_frames` / `generate_single_stream_frames` /
  `encode_frame_to_jpeg` / the `/video_feed` and `/stream/<id>` MJPEG routes.
  Add an endpoint (or just static config) that tells the frontend which
  mediamtx HLS URL corresponds to which grid cell.
- Recording: keep `ffmpeg_recorder.py` as-is, but point
  `FFmpegStreamRecorder.stream_source` at the camera's mediamtx-served RTSP
  URL instead of the original camera URL, so recording shares the single
  upstream pull instead of opening a second connection to the camera.
  (Considered switching to mediamtx's built-in per-path recording instead -
  rejected for now since it would mean re-implementing the existing
  chunk-duration/total-rotation/disk-space logic via mediamtx's recording
  config; repointing the source URL is a smaller change.)

### 4. Frontend changes (largest chunk of the work)

- Replace the single MJPEG `<img>`/stream view with a CSS grid of `<video>`
  elements (hls.js sources), one per cell.
- BBOX toggle: instead of the backend swapping which stream is decoded,
  the frontend swaps which mediamtx HLS URL a cell's `<video>` points at.
- Fullscreen view: same player component, just one cell, pointed at that
  camera's HLS URL directly - no separate backend route needed.

### 5. What stays the same

- `web_server.py`'s control-plane API surface (start/stop, bbox toggle,
  save-mode endpoints, heartbeat/inactivity watchdog) stays conceptually the
  same - it just calls mediamtx's API to manage paths instead of spawning
  `FFmpegStreamHandler` objects directly.
- `parse_deepstream_uris()` / config parsing logic is unchanged.

## Open items / things to verify before implementing

- Confirm actual H264 profile emitted by camera sources and the `ds-test`
  bbox sinks (affects whether WebRTC could ever be revisited later, though
  HLS is the current decision regardless).
- Decide exact mediamtx path-naming scheme (e.g. `cam0_source`,
  `cam0_bbox`).
- Confirm mediamtx's on-demand source pulling (stop pulling upstream when no
  readers) is enabled, to avoid holding open connections to cameras nobody
  is currently viewing.
