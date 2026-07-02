"""
Video Wall Path Manager - Keeps mediamtx's RTSP->HLS relay paths in sync with
the configured camera list. Does not decode, composite, or serve any video
itself - the browser plays HLS directly from mediamtx, and this class just
tells mediamtx which upstream URL each path should pull from.
"""
import re
from typing import List, Dict
import logging
from mediamtx_client import MediamtxClient

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r'[^a-zA-Z0-9_]')


def _sanitize(value: str) -> str:
    """mediamtx path names must be safe URL segments"""
    return _SAFE_NAME_RE.sub('', str(value)) or 'x'


class VideoWallDisplay:
    """Maps camera identities to mediamtx path names and keeps mediamtx's
    path configuration in sync via its REST API"""

    def __init__(self, client: MediamtxClient, rtsp_port: int = 8554):
        self.client = client
        self.rtsp_port = rtsp_port
        self._known_paths: Dict[str, dict] = {}  # path_name -> last-pushed config

    @staticmethod
    def path_name(source_id: str, variant: str) -> str:
        """variant: 'src' or 'bbox', e.g. cam223_src / cam223_bbox"""
        return f"cam{_sanitize(source_id)}_{variant}"

    @staticmethod
    def dev_path_name(index: int) -> str:
        return f"dev{index}"

    def sync_cameras(self, streams_info: List[dict]) -> List[dict]:
        """
        streams_info: output of parse_deepstream_uris() (or the manual-URL
        fallback list built from config.yaml's `streams`), each entry shaped
        like {'source': uri, 'source_id': str, 'bbox': uri (optional)}.

        Ensures a mediamtx path exists for each source (and bbox, if present).
        Returns the per-cell info the frontend needs to build its video grid.
        """
        cells = []
        for i, info in enumerate(streams_info):
            source_id = str(info.get('source_id', i))

            path_src = self.path_name(source_id, 'src')
            self._ensure_path(path_src, {
                'source': info['source'],
                'sourceOnDemand': True,
                'sourceOnDemandCloseAfter': '30s',
            })

            path_bbox = None
            if info.get('bbox'):
                path_bbox = self.path_name(source_id, 'bbox')
                self._ensure_path(path_bbox, {
                    'runOnDemand': self._bbox_remux_cmd(info['bbox']),
                    'runOnDemandRestart': True,
                    'runOnDemandCloseAfter': '120s',
                    # The extra ffmpeg hop needs time to connect to the
                    # upstream RTSP source and probe it before it starts
                    # publishing back into mediamtx - mediamtx's 10s default
                    # was killing it before it got that far.
                    'runOnDemandStartTimeout': '100s',
                })

            cells.append({
                'index': i,
                'source_id': source_id,
                'path_source': path_src,
                'path_bbox': path_bbox,
                'has_bbox': path_bbox is not None,
            })
        return cells

    def _bbox_remux_cmd(self, upstream_url: str) -> str:
        """DeepStream's bbox/OSD RTSP sink doesn't reliably send SPS/PPS
        (H264 parameter sets) to a freshly-connecting client - confirmed via
        ffprobe against the sink directly ("non-existing PPS 0 referenced",
        "decode_slice_header error", "no frame!" repeated before it finally
        gets a usable frame). Until that's fixed upstream (DeepStream
        encoder's insert-sps-pps setting), give ffmpeg a wide analyze/probe
        window so it's likely to eventually land on a valid keyframe+PPS
        instead of giving up early - this is a stopgap, not a fix for the
        source. Also re-stamp packets from wall-clock arrival time instead
        of trusting the source's own (sometimes invalid, DTS > PTS)
        timestamps. -c copy keeps this a repacketize, not a re-encode."""
        return (
            f'ffmpeg -fflags +genpts -use_wallclock_as_timestamps 1 '
            f'-analyzeduration 10000000 -probesize 5000000 '
            f'-rtsp_transport tcp -i "{upstream_url}" '
            f'-c copy -avoid_negative_ts make_zero '
            f'-f rtsp rtsp://127.0.0.1:{self.rtsp_port}/$MTX_PATH'
        )

    def sync_dev_videos(self, test_vids: List[str]) -> List[dict]:
        """
        dev_mode: mediamtx can't pull a raw local file the way it pulls RTSP,
        so each dev path runs an ffmpeg loop (via the mediamtx -ffmpeg image)
        that re-publishes the local file as RTSP back into mediamtx itself.
        """
        cells = []
        for i, file_path in enumerate(test_vids):
            name = self.dev_path_name(i)
            cmd = (
                f'ffmpeg -re -stream_loop -1 -i "{file_path}" '
                f'-c copy -f rtsp rtsp://127.0.0.1:{self.rtsp_port}/$MTX_PATH'
            )
            self._ensure_path(name, {
                'runOnDemand': cmd,
                'runOnDemandRestart': True,
                'runOnDemandCloseAfter': '30s',
            })
            cells.append({
                'index': i,
                'source_id': str(i),
                'path_source': name,
                'path_bbox': None,
                'has_bbox': False,
            })
        return cells

    def _ensure_path(self, name: str, desired: dict):
        """Only calls mediamtx's API if this path's config actually changed
        since the last sync, to avoid redundant round-trips on every poll"""
        if self._known_paths.get(name) == desired:
            return
        try:
            self.client.upsert_path(name, desired)
            self._known_paths[name] = desired
        except Exception as e:
            logger.error(f"mediamtx: failed to provision path '{name}': {e}")
