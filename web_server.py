"""
Web Server for Video Wall Application
Control plane for the video wall: provisions mediamtx RTSP->HLS relay paths
and drives recording. The browser plays HLS directly from mediamtx - this
process no longer decodes or serves any video pixels itself.
"""
import threading
import time
from flask import Flask, render_template, jsonify, request, send_file
from video_wall import VideoWallDisplay
from video_recorder import VideoWallRecorder
from mediamtx_client import MediamtxClient
import logging
import yaml
import os
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Global state
recorder = None
config_file = 'config.yaml'
bbox_on_mode = False  # Global toggle for BBOX_ON mode
session_bbox_toggles = {} # In-memory storage for per-stream toggles

# Heartbeat / inactivity watchdog
HEARTBEAT_TIMEOUT_SECONDS = 1800  # Stop wall if no heartbeat for this long
last_heartbeat_time = 0.0  # epoch timestamp of last frontend heartbeat
watchdog_thread = None


def check_shared_volume():
    """Check and log shared volume contents"""
    shared_volume_path = '/app/shared_volume'
    if os.path.exists(shared_volume_path):
        try:
            files = os.listdir(shared_volume_path)
            file_count = len(files)
            logger.info(f"✓ Shared volume accessible at {shared_volume_path}")

            # Try to parse config.yaml from shared volume
            config_path = os.path.join(shared_volume_path, 'config.yaml')
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        shared_config = yaml.safe_load(f)

                    if shared_config and 'DEPLOYMENT' in shared_config:
                        deployment = shared_config['DEPLOYMENT']
                        num_gpus = deployment.get('NUM_GPUS', 0)
                        num_cameras = deployment.get('NUM_CAMERAS_PER_GPU', 0)
                        bbox_on = deployment.get('BBOX_ON', False)
                        total_cameras = num_gpus * num_cameras

                        logger.info(f"✓ Total cameras: {total_cameras}")
                        logger.info(f"✓ BBOX_ON mode: {'ENABLED' if bbox_on else 'DISABLED'}")

                        if bbox_on:
                            logger.info(f"✓ Using localhost ports 7000-700{total_cameras-1}")
                        else:
                            logger.info(f"✓ Parsing deepstream configs for {num_gpus} GPU(s)")

                            # Parse deepstream config files for each GPU
                            for gpu_id in range(num_gpus):
                                config_file = os.path.join(
                                    shared_volume_path,
                                    'configs',
                                    str(gpu_id),
                                    f'deepstream_app_config_gpu{gpu_id}.txt'
                                )

                                if os.path.exists(config_file):
                                    logger.info(f"  GPU {gpu_id} config:")
                                    try:
                                        with open(config_file, 'r') as f:
                                            for line in f:
                                                line = line.strip()
                                                if line.startswith('uri = '):
                                                    logger.info(f"    {line}")
                                    except Exception as e:
                                        logger.warning(f"    Could not read config: {str(e)}")
                                else:
                                    logger.warning(f"  GPU {gpu_id} config not found: {config_file}")
                    else:
                        logger.warning("config.yaml found but no DEPLOYMENT section")
                except Exception as e:
                    logger.warning(f"Could not parse config.yaml: {str(e)}")

            return file_count
        except Exception as e:
            logger.warning(f"Could not read shared volume: {str(e)}")
    else:
        logger.warning(f"✗ Shared volume not mounted at {shared_volume_path}")
    return 0


def load_config():
    """Load configuration from file"""
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Could not load config: {str(e)}")
    return {}


# mediamtx integration - RTSP->HLS relay. web_server.py never decodes/serves
# video itself; it just keeps mediamtx's path config in sync with the camera
# list and hands the browser mediamtx's HLS URLs.
_mediamtx_cfg = load_config().get('mediamtx', {})
MEDIAMTX_API_URL = _mediamtx_cfg.get('api_url', 'http://127.0.0.1:9997')
MEDIAMTX_RTSP_PORT = _mediamtx_cfg.get('rtsp_port', 8554)
MEDIAMTX_HLS_PORT = _mediamtx_cfg.get('hls_port', 8888)

mediamtx_client = MediamtxClient(base_url=MEDIAMTX_API_URL)
video_wall_display = VideoWallDisplay(mediamtx_client, rtsp_port=MEDIAMTX_RTSP_PORT)


def parse_deepstream_uris():
    """Parse URI streams and BBOX ports from deepstream config files"""
    shared_volume_path = '/app/shared_volume'
    streams_info = []

    config_path = os.path.join(shared_volume_path, 'config.yaml')
    if not os.path.exists(config_path):
        return streams_info

    try:
        with open(config_path, 'r') as f:
            shared_config = yaml.safe_load(f)

        if shared_config and 'DEPLOYMENT' in shared_config:
            deployment = shared_config['DEPLOYMENT']
            num_gpus = deployment.get('NUM_GPUS', 0)

            # Parse deepstream config files for each GPU
            for gpu_id in range(num_gpus):
                config_file = os.path.join(
                    shared_volume_path,
                    'configs',
                    str(gpu_id),
                    f'deepstream_app_config_gpu{gpu_id}.txt'
                )

                if os.path.exists(config_file):
                    try:
                        sources = {}  # source_id -> uri
                        sinks = {}    # source_id -> rtsp_port (only for type 4)

                        current_section = None
                        current_source_id = None
                        current_uri = None
                        current_type = None
                        current_rtsp_port = None
                        current_sink_source_id = None

                        def flush_section():
                            nonlocal current_section, current_source_id, current_uri, current_type, current_rtsp_port, current_sink_source_id
                            if not current_section:
                                return

                            if current_section.startswith('source'):
                                # Extract numeric ID from section name, e.g. [source223] -> 223
                                section_num = current_section.replace('source', '', 1)
                                source_idx = len(sources)
                                if current_uri:
                                    sources[source_idx] = {'uri': current_uri, 'section_id': section_num}

                            elif current_section.startswith('sink'):
                                if current_type == '4' and current_rtsp_port and current_sink_source_id is not None:
                                    sinks[int(current_sink_source_id)] = current_rtsp_port

                            # Reset for next section
                            current_type = None
                            current_rtsp_port = None
                            current_sink_source_id = None
                            current_uri = None

                        with open(config_file, 'r') as f:
                            for line in f:
                                line = line.strip()
                                if not line or line.startswith('#'):
                                    continue
                                if '#' in line:
                                    line = line.split('#')[0].strip()

                                if line.startswith('[') and line.endswith(']'):
                                    flush_section()
                                    current_section = line[1:-1]
                                    continue

                                if '=' in line:
                                    key, val = [part.strip() for part in line.split('=', 1)]
                                    if key == 'uri':
                                        current_uri = val
                                    elif key == 'type':
                                        current_type = val
                                    elif key == 'rtsp-port':
                                        current_rtsp_port = val
                                    elif key == 'source-id':
                                        current_sink_source_id = val

                        flush_section()

                        # Map sources to their corresponding type-4 sinks
                        for i in sorted(sources.keys()):
                            src = sources[i]
                            stream_info = {
                                'source': src['uri'],
                                'source_id': src['section_id'],
                            }
                            if i in sinks:
                                stream_info['bbox'] = f'rtsp://localhost:{sinks[i]}/ds-test'
                            streams_info.append(stream_info)

                    except Exception as e:
                        logger.warning(f"Could not read config for GPU {gpu_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Could not parse deepstream configs: {str(e)}")
        logger.error(traceback.format_exc())

    return streams_info


def get_streams_from_config():
    """Get streams with their BBOX toggle status"""
    config = load_config()
    dev_mode = config.get('dev_mode', False)

    # Use in-memory session toggles instead of reading from config.yaml
    # Format: {index: true/false}
    bbox_toggles = session_bbox_toggles

    if dev_mode:
        raw_streams = config.get('test_vids', [])
        # For dev mode, we don't really have BBOX counterparts usually,
        # but we'll return them as-is.
        streams = raw_streams
    else:
        streams_info = parse_deepstream_uris()
        if not streams_info:
            # Fallback to simple list if parsing fails
            streams = config.get('streams', [])
        else:
            # Map streams based on their individual toggle
            streams = []
            for i, info in enumerate(streams_info):
                # Check if this specific stream has BBOX enabled
                # We use string keys for the dict because JSON/YAML keys can be tricky
                is_bbox = bbox_toggles.get(str(i), False)
                # Only use BBOX if it's available in the config
                if is_bbox and 'bbox' in info:
                    streams.append(info['bbox'])
                else:
                    # Use source URL if BBOX not available or not toggled
                    streams.append(info['source'])

    return streams, dev_mode


def get_streams_info_for_provisioning(dev_mode_override=None):
    """
    Returns (streams_info, dev_mode) describing what mediamtx paths should
    exist right now.

    - dev_mode=True: streams_info is the list of local test_vids file paths.
    - dev_mode=False: streams_info is a list of {'source', 'source_id', 'bbox'?}
      dicts, from parse_deepstream_uris(), falling back to config.yaml's
      manual `streams` list (wrapped into the same shape) if DeepStream
      parsing is unavailable.

    dev_mode_override lets callers honor a UI toggle that hasn't been saved
    to config.yaml yet (see /api/save-mode/config).
    """
    config = load_config()
    dev_mode = dev_mode_override if dev_mode_override is not None else config.get('dev_mode', False)

    if dev_mode:
        return config.get('test_vids', []), True

    streams_info = parse_deepstream_uris()
    if not streams_info:
        streams_info = [
            {'source': url, 'source_id': str(i)}
            for i, url in enumerate(config.get('streams', []))
        ]
    return streams_info, False


def ensure_mediamtx_paths(dev_mode_override=None):
    """
    Idempotent: provisions mediamtx paths for the current camera list and
    returns (cells, dev_mode). Safe to call from any route that needs the
    current camera->mediamtx-path mapping; never raises.
    """
    streams_info, dev_mode = get_streams_info_for_provisioning(dev_mode_override)
    try:
        if dev_mode:
            return video_wall_display.sync_dev_videos(streams_info), dev_mode
        return video_wall_display.sync_cameras(streams_info), dev_mode
    except Exception as e:
        logger.error(f"ensure_mediamtx_paths failed: {e}")
        return [], dev_mode


class VideoWallStreamer:
    """Tracks whether the wall is 'running' and its grid dimensions. Does not
    own any stream handlers - mediamtx path provisioning is handled
    separately via ensure_mediamtx_paths(), independent of this running flag,
    so save-mode recording works even if the wall was never started."""

    def __init__(self):
        self.is_running = False
        self.cols = 2
        self.rows = 2
        self.width = 1920
        self.height = 1080
        self.lock = threading.Lock()

    def start(self, cols, rows, width, height):
        with self.lock:
            self.cols = cols
            self.rows = rows
            self.width = width
            self.height = height
            self.is_running = True
            logger.info(f"Video wall marked running: {cols}x{rows} grid, {width}x{height}")
            return True

    def stop(self):
        with self.lock:
            self.is_running = False
            logger.info("Video wall stopped")

    def get_status(self):
        with self.lock:
            if not self.is_running:
                return {'running': False}
            return {
                'running': True,
                'cols': self.cols,
                'rows': self.rows,
                'width': self.width,
                'height': self.height,
            }


streamer = VideoWallStreamer()


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    """Get wall status"""
    status = streamer.get_status()
    config = load_config()
    status['dev_mode'] = config.get('dev_mode', False)
    status['hls_port'] = MEDIAMTX_HLS_PORT
    if status.get('running'):
        try:
            streams_info, _ = get_streams_info_for_provisioning()
            status['streams'] = len(streams_info)
        except Exception:
            status['streams'] = 0
    return jsonify(status)


@app.route('/api/start', methods=['POST'])
def api_start():
    """Start the video wall: provision mediamtx paths for the current camera
    list and mark the wall as running with the given grid layout."""
    try:
        logger.info("POST /api/start request received")
        data = request.get_json() or {}
        logger.debug(f"Request data: {data}")

        streams = data.get('streams') or []
        cols = data.get('cols', 2)
        rows = data.get('rows', 2)
        width = data.get('width', 1920)
        height = data.get('height', 1080)

        logger.info(f"Parsed parameters - streams: {len(streams)}, grid: {cols}x{rows}, resolution: {width}x{height}")

        if not streams:
            logger.warning("No streams provided in request")
            return jsonify({'error': 'No streams provided'}), 400

        cells, dev_mode = ensure_mediamtx_paths()
        logger.info(f"Provisioned {len(cells)} mediamtx path(s) (dev_mode={dev_mode})")

        success = streamer.start(cols, rows, width, height)

        if success:
            logger.info("Video wall started successfully")
            return jsonify({'status': 'started'})
        else:
            logger.error("streamer.start() returned False")
            return jsonify({'error': 'Failed to start video wall'}), 500
    except Exception as e:
        logger.error(f"Exception in api_start: {str(e)}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop the video wall (mediamtx paths are left registered - on-demand
    sourcing means an unwatched path costs nothing)"""
    streamer.stop()
    return jsonify({'status': 'stopped'})


@app.route('/api/heartbeat', methods=['POST'])
def api_heartbeat():
    """Frontend heartbeat — keeps the wall alive while a browser tab is open"""
    global last_heartbeat_time
    last_heartbeat_time = time.time()
    return jsonify({'status': 'ok'})


@app.route('/api/config', methods=['GET'])
def api_get_config():
    """Get current configuration"""
    config = load_config()
    return jsonify(config)


@app.route('/api/config', methods=['POST'])
def api_set_config():
    """Update configuration (in-memory for toggles to avoid Permission Denied).

    BBOX toggle no longer drives any backend media action: mediamtx already
    relays both the source and bbox path for every camera simultaneously, so
    toggling which one is displayed is purely a frontend URL swap. This just
    persists the toggle so other clients/reloads see the last-set default.
    """
    try:
        data = request.get_json() or {}
        global session_bbox_toggles
        session_bbox_toggles = data.get('bbox_toggles', {})
        return jsonify({'status': 'saved_in_memory'})
    except Exception as e:
        logger.error(f"Error in api_set_config: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/bbox-mode', methods=['GET'])
def api_get_bbox_mode():
    """Get current BBOX_ON mode state"""
    global bbox_on_mode
    return jsonify({'bbox_on': bbox_on_mode})


@app.route('/api/bbox-mode', methods=['POST'])
def api_set_bbox_mode():
    """Set BBOX_ON mode state"""
    global bbox_on_mode
    try:
        data = request.get_json() or {}
        bbox_on_mode = data.get('bbox_on', False)
        logger.info(f"BBOX_ON mode set to: {bbox_on_mode}")
        return jsonify({'status': 'updated', 'bbox_on': bbox_on_mode})
    except Exception as e:
        logger.error(f"Error setting BBOX mode: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/streams', methods=['GET'])
def api_get_streams():
    """Get list of available streams, plus per-cell mediamtx path info the
    frontend needs to build its HLS video grid"""
    try:
        # This function handles the per-stream toggle logic based on the loaded config
        streams, dev_mode = get_streams_from_config()

        # Also get source IDs from deepstream parsing
        source_ids = []
        if not dev_mode:
            streams_info = parse_deepstream_uris()
            source_ids = [info.get('source_id', str(i)) for i, info in enumerate(streams_info)]

        cells, _ = ensure_mediamtx_paths()

        return jsonify({
            'streams': streams,
            'dev_mode': dev_mode,
            'bbox_toggles': session_bbox_toggles,
            'source_ids': source_ids,
            'hls_port': MEDIAMTX_HLS_PORT,
            'cells': cells,
        })
    except Exception as e:
        logger.error(f"Error getting streams: {str(e)}")
        return jsonify({'error': str(e), 'streams': []}), 500


@app.route('/api/reparse-configs', methods=['POST'])
def api_reparse_configs():
    """Force re-parse of deepstream config files and sync mediamtx paths"""
    try:
        logger.info("Force re-parsing deepstream configs (POST /api/reparse-configs)")
        cells, dev_mode = ensure_mediamtx_paths()

        return jsonify({
            'status': 'success',
            'total_streams': len(cells),
        })
    except Exception as e:
        logger.error(f"Error in re-parsing configs: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ============================================================================
# Save Mode - Recording Endpoints
# ============================================================================

@app.route('/api/save-mode/config', methods=['GET'])
def api_savemode_config():
    """Get available streams for recording, as mediamtx-relayed RTSP URLs so
    the recorder shares mediamtx's single upstream pull per camera instead of
    opening a second independent connection to it."""
    config = load_config()

    # Check if client is passing dev_mode state (to handle UI toggle before saving config)
    dev_mode_param = request.args.get('dev_mode', '').lower()
    dev_mode_override = None
    if dev_mode_param in ['true', 'false']:
        dev_mode_override = dev_mode_param == 'true'
        logger.info(f"api_savemode_config: Using dev_mode from request: {dev_mode_override}")

    cells, dev_mode = ensure_mediamtx_paths(dev_mode_override)

    available_streams = []
    if dev_mode:
        for cell in cells:
            available_streams.append({
                'id': cell['index'],
                'name': f"Test Video {cell['index'] + 1}",
                'url': f"rtsp://127.0.0.1:{MEDIAMTX_RTSP_PORT}/{cell['path_source']}",
                'type': 'source'
            })
        logger.debug(f"api_savemode_config: Returning {len(available_streams)} test videos")
    else:
        for cell in cells:
            available_streams.append({
                'id': cell['index'],
                'name': f"Camera {cell['index'] + 1} (Source)",
                'url': f"rtsp://127.0.0.1:{MEDIAMTX_RTSP_PORT}/{cell['path_source']}",
                'type': 'source'
            })
            if cell['has_bbox']:
                available_streams.append({
                    'id': cell['index'],
                    'name': f"Camera {cell['index'] + 1} (BBOX)",
                    'url': f"rtsp://127.0.0.1:{MEDIAMTX_RTSP_PORT}/{cell['path_bbox']}",
                    'type': 'bbox'
                })
        logger.info(f"api_savemode_config: Returning {len(available_streams)} parsed streams")

    return jsonify({
        'dev_mode': dev_mode,
        'available_streams': available_streams,
        'save_mode_config': config.get('save_mode', {})
    })


@app.route('/api/save-mode/start', methods=['POST'])
def api_savemode_start():
    """Start recording selected streams (allows starting individual streams)"""
    global recorder

    try:
        data = request.get_json() or {}
        # selected_streams format: list of objects {id, url, type, name}
        selected_streams = data.get('selected_streams', [])
        dev_mode = data.get('dev_mode', False)

        logger.info(f"api_savemode_start: dev_mode={dev_mode}, selected_count={len(selected_streams)}")

        if not selected_streams:
            return jsonify({'error': 'No streams selected'}), 400

        # Build streams dict for recorder: { "stream_id_type": url }
        streams_dict = {}
        for item in selected_streams:
            stream_id = item.get('id')
            stream_type = item.get('type', 'source')
            stream_url = item.get('url')

            if stream_id is not None and stream_url:
                unique_key = f"{stream_id}_{stream_type}"
                streams_dict[unique_key] = stream_url
                logger.debug(f"api_savemode_start: Added {stream_type} stream {stream_id}: {stream_url}")

        if not streams_dict:
            return jsonify({'error': 'No valid streams provided'}), 400

        config = load_config()
        save_config = config.get('save_mode', {})

        # Initialize recorder if needed
        if not recorder:
            output_dir = save_config.get('output_directory', './recordings')
            chunk_minutes = save_config.get('chunk_duration_minutes', 60)
            rotation_minutes = save_config.get('total_rotation_minutes', 1440)
            fps = save_config.get('fps', 30)
            width = save_config.get('recording_width', 1920)
            height = save_config.get('recording_height', 1080)

            recorder = VideoWallRecorder(
                output_dir=output_dir,
                chunk_duration_minutes=chunk_minutes,
                total_rotation_minutes=rotation_minutes,
                fps=fps,
                width=width,
                height=height
            )

        success = recorder.start_recording_extended(streams_dict)

        if success:
            logger.info(f"api_savemode_start: Recording update successful")
            return jsonify({
                'status': 'recording',
                'streams': list(recorder.recording_threads.keys())
            })
        else:
            return jsonify({'error': 'Failed to update recording'}), 500

    except Exception as e:
        logger.error(f"Error in api_savemode_start: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-mode/stop-stream', methods=['POST'])
def api_savemode_stop_stream():
    """Stop a specific stream recording"""
    global recorder
    try:
        data = request.get_json() or {}
        stream_key = data.get('stream_key') # e.g. "0_source" or "1_bbox"

        if not recorder or not stream_key:
            return jsonify({'error': 'No active recorder or stream key'}), 400

        success = recorder.stop_stream_recording(stream_key)
        return jsonify({'status': 'stopped' if success else 'not_found', 'key': stream_key})
    except Exception as e:
        logger.error(f"Error in api_savemode_stop_stream: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-mode/stop', methods=['POST'])
def api_savemode_stop():
    """Stop recording"""
    global recorder

    try:
        if not recorder or not recorder.is_recording:
            return jsonify({'error': 'No recording in progress'}), 400

        recorder.stop_recording()
        recordings = recorder.list_recordings()

        return jsonify({
            'status': 'stopped',
            'total_files': sum(len(files) for files in recordings.values()),
            'recordings': recordings
        })

    except Exception as e:
        logger.error(f"Error in api_savemode_stop: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-mode/status', methods=['GET'])
def api_savemode_status():
    """Get recording status"""
    global recorder

    try:
        if not recorder:
            return jsonify({'recording': False})

        status = recorder.get_status()
        status['disk_usage_gb'] = recorder.get_disk_usage()
        status['recordings'] = recorder.list_recordings()

        return jsonify(status)

    except Exception as e:
        logger.error(f"Error in api_savemode_status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-mode/files', methods=['GET'])
def api_savemode_files():
    """List all recorded files"""
    global recorder

    try:
        if not recorder:
            return jsonify({'recordings': {}})

        recordings = recorder.list_recordings()
        disk_usage = recorder.get_disk_usage()

        return jsonify({
            'recordings': recordings,
            'disk_usage_gb': disk_usage,
            'total_files': sum(len(files) for files in recordings.values())
        })

    except Exception as e:
        logger.error(f"Error in api_savemode_files: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/save-mode/download', methods=['GET'])
def api_savemode_download():
    """Download a recorded file"""
    try:
        file_path = request.args.get('file_path')

        if not file_path or not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404

        # Verify file is within recordings directory
        recordings_dir = os.path.abspath('./recordings')
        file_abs = os.path.abspath(file_path)

        if not file_abs.startswith(recordings_dir):
            return jsonify({'error': 'Invalid file path'}), 403

        filename = os.path.basename(file_path)
        return send_file(file_path, as_attachment=True, download_name=filename)

    except Exception as e:
        logger.error(f"Error in api_savemode_download: {str(e)}")
        return jsonify({'error': str(e)}), 500


def _inactivity_watchdog():
    """Background thread that auto-stops the wall if the frontend goes away.

    Runs every 15 seconds.  If the wall is running and no heartbeat has been
    received for HEARTBEAT_TIMEOUT_SECONDS, it stops both the video wall and
    any active recording to free resources.
    """
    global last_heartbeat_time, recorder
    logger.info(f"Inactivity watchdog started (timeout={HEARTBEAT_TIMEOUT_SECONDS}s)")
    while True:
        time.sleep(15)
        if not streamer.is_running:
            continue
        if last_heartbeat_time == 0:
            # No heartbeat ever received — wall was started before the first
            # heartbeat arrived; give it a grace period.
            continue
        elapsed = time.time() - last_heartbeat_time
        if elapsed > HEARTBEAT_TIMEOUT_SECONDS:
            logger.warning(
                f"No frontend heartbeat for {elapsed:.0f}s — auto-stopping video wall to save resources"
            )
            streamer.stop()
            # Also stop recordings if any
            if recorder and recorder.is_recording:
                try:
                    recorder.stop_recording()
                    logger.info("Auto-stopped active recording due to inactivity")
                except Exception as e:
                    logger.error(f"Error auto-stopping recorder: {e}")
            last_heartbeat_time = 0.0


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Video Wall Web Server Starting")
    logger.info("=" * 60)

    # Check shared volume
    file_count = check_shared_volume()

    # Start inactivity watchdog
    watchdog_thread = threading.Thread(target=_inactivity_watchdog, daemon=True)
    watchdog_thread.start()

    logger.info("=" * 60)
    app.run(host='0.0.0.0', port=5002, debug=False, threaded=True)
