"""
Web Server for Video Wall Application
Serves video wall display via HTTP streaming using FFmpeg
"""
import numpy as np
import threading
import time
from flask import Flask, render_template, Response, jsonify, request, send_file
from video_wall import VideoWallDisplay
from video_recorder import VideoWallRecorder
import logging
import yaml
import os
from io import BytesIO
import traceback
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Global state
video_wall = None
wall_thread = None
is_running = False
recorder = None
config_file = 'config.yaml'
bbox_on_mode = False  # Global toggle for BBOX_ON mode
session_bbox_toggles = {} # In-memory storage for per-stream toggles


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
                        # Use ConfigParser but handle multiple source/sink sections
                        # configparser doesn't support multiple identical keys, so we parse manually
                        current_source_uri = None
                        current_rtsp_port = None
                        with open(config_file, 'r') as f:
                            for line in f:
                                line = line.strip()
                                # Clear comments
                                if '#' in line:
                                    line = line.split('#')[0].strip()
                                
                                if line.startswith('uri = '):
                                    # If we have a previous stream, save it (even without BBOX)
                                    if current_source_uri:
                                        stream_info = {'source': current_source_uri}
                                        if current_rtsp_port:
                                            stream_info['bbox'] = f'rtsp://localhost:{current_rtsp_port}/ds-test'
                                        streams_info.append(stream_info)
                                    
                                    # Start new stream
                                    current_source_uri = line.replace('uri = ', '').strip()
                                    current_rtsp_port = None
                                elif line.startswith('rtsp-port = '):
                                    current_rtsp_port = line.replace('rtsp-port = ', '').strip()
                        
                        # Don't forget the last stream
                        if current_source_uri:
                            stream_info = {'source': current_source_uri}
                            if current_rtsp_port:
                                stream_info['bbox'] = f'rtsp://localhost:{current_rtsp_port}/ds-test'
                            streams_info.append(stream_info)
                    except Exception as e:
                        logger.warning(f"Could not read config for GPU {gpu_id}: {str(e)}")
    except Exception as e:
        logger.warning(f"Could not parse deepstream configs: {str(e)}")
    
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


class VideoWallStreamer:
    """Handles video wall streaming"""
    
    def __init__(self):
        self.wall = None
        self.is_running = False
        self.thread = None
        self.lock = threading.Lock()
        
    def start(self, streams, cols, rows, width, height):
        """Start the video wall"""
        with self.lock:
            if self.is_running:
                logger.warning("Video wall is already running. Stop it first before starting again.")
                return False
            
            try:
                logger.info(f"Starting video wall with parameters: cols={cols}, rows={rows}, width={width}, height={height}")
                logger.info(f"Streams to load: {len(streams)} total - {streams}")
                
                self.wall = VideoWallDisplay(
                    streams=streams,
                    cols=cols,
                    rows=rows,
                    output_width=width,
                    output_height=height
                )
                logger.info("VideoWallDisplay instance created successfully")
                
                self.wall.start()
                logger.info("VideoWallDisplay.start() completed")
                
                self.is_running = True
                logger.info(f"Video wall started: {len(streams)} streams in {cols}x{rows} grid")
                return True
            except Exception as e:
                logger.error(f"Error starting video wall: {str(e)}")
                logger.error(f"Traceback:\n{traceback.format_exc()}")
                self.is_running = False
                return False
    
    def stop(self):
        """Stop the video wall"""
        with self.lock:
            if self.wall:
                self.wall.stop()
            self.is_running = False
            logger.info("Video wall stopped")
    
    def update_stream(self, index, url):
        """Update a specific stream in the running wall"""
        with self.lock:
            if self.wall and self.is_running:
                return self.wall.update_stream(index, url)
        return False
    
    def get_frame(self):
        """Get current frame"""
        with self.lock:
            if self.wall and self.is_running:
                return self.wall.get_wall_frame()
        return None
    
    def get_status(self):
        """Get current status"""
        with self.lock:
            if self.wall and self.is_running:
                return {
                    'running': True,
                    'cols': self.wall.cols,
                    'rows': self.wall.rows,
                    'width': self.wall.output_width,
                    'height': self.wall.output_height,
                    'streams': len([s for s in self.wall.streams if s])
                }
        return {'running': False}


streamer = VideoWallStreamer()


def generate_placeholder_frame(width=1280, height=720, text="Waiting for video stream..."):
    """Generate a placeholder/waiting frame using PIL"""
    # Create a numpy array (BGR format for consistency)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (40, 40, 80)  # Dark blue background
    
    # Convert to PIL Image (RGB)
    pil_image = Image.fromarray(frame[:, :, ::-1])  # BGR to RGB
    draw = ImageDraw.Draw(pil_image)
    
    # Add text using PIL
    try:
        # Try to use a nice font if available
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    except:
        # Fallback to default font
        font = ImageFont.load_default()
    
    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2
    
    # Draw text (white color)
    draw.text((text_x, text_y), text, font=font, fill=(200, 200, 200))
    
    # Convert back to numpy array (BGR)
    frame_array = np.array(pil_image)[:, :, ::-1]  # RGB to BGR
    return frame_array


def encode_frame_to_jpeg(frame):
    """Encode a numpy array frame to JPEG bytes"""
    # Convert BGR to RGB for PIL
    rgb_frame = frame[:, :, ::-1]
    pil_image = Image.fromarray(rgb_frame)
    
    # Encode to JPEG
    buf = BytesIO()
    pil_image.save(buf, format='JPEG', quality=90)
    return buf.getvalue()

def generate_frames():
    """Generate video stream frames"""
    stream_id = int(time.time())
    logger.info(f"generate_frames({stream_id}): Starting - waiting for streamer to be ready")
    
    # Wait for streamer to start (with timeout to avoid infinite wait)
    timeout = 10  # Reduced timeout for switching
    elapsed = 0
    wait_interval = 0.5
    frame_count = 0
    
    # Send placeholder frames while waiting for streamer
    while not streamer.is_running and elapsed < timeout:
        logger.debug(f"generate_frames({stream_id}): Streamer not running yet, sending placeholder... ({elapsed:.1f}s / {timeout}s)")
        
        # Generate placeholder frame to keep connection alive
        placeholder = generate_placeholder_frame()
        try:
            frame_bytes = encode_frame_to_jpeg(placeholder)
            frame_count += 1
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                   frame_bytes + b'\r\n')
        except Exception as e:
            logger.error(f"generate_frames({stream_id}): Error creating placeholder: {str(e)}")
            break
        
        time.sleep(wait_interval)
        elapsed += wait_interval
    
    if not streamer.is_running:
        logger.warning(f"generate_frames({stream_id}): Timeout waiting for streamer to start, terminating generator")
        return
    
    logger.info(f"generate_frames({stream_id}): Streamer is running, starting frame generation")
    
    while streamer.is_running:
        frame = streamer.get_frame()
        if frame is None:
            time.sleep(0.01)  # Small delay if no frame available
            continue
        
        try:
            # Encode frame to JPEG
            frame_bytes = encode_frame_to_jpeg(frame)
            
            frame_count += 1
            if frame_count % 300 == 0:  # Log every 10 seconds approx
                logger.debug(f"generate_frames({stream_id}): Sent {frame_count} total frames")
            
            # Yield frame in MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                   frame_bytes + b'\r\n')
        except Exception as e:
            logger.error(f"generate_frames({stream_id}): Error encoding frame: {str(e)}")
            break
    
    logger.info(f"generate_frames({stream_id}): Stream ended after {frame_count} total frames")


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    """Video stream endpoint"""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


def generate_single_stream_frames(stream_index):
    """Generate frames from a single stream for fullscreen view"""
    stream_id = f"stream_{stream_index}_{int(time.time())}"
    logger.info(f"generate_single_stream_frames({stream_id}): Starting fullscreen for stream {stream_index}")
    
    frame_count = 0
    
    # Wait for video wall to be running
    timeout = 10
    elapsed = 0
    wait_interval = 0.5
    
    while not streamer.is_running and elapsed < timeout:
        logger.debug(f"generate_single_stream_frames({stream_id}): Waiting for streamer... ({elapsed:.1f}s)")
        placeholder = generate_placeholder_frame()
        try:
            frame_bytes = encode_frame_to_jpeg(placeholder)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                   frame_bytes + b'\r\n')
        except Exception as e:
            logger.error(f"generate_single_stream_frames({stream_id}): Error creating placeholder: {str(e)}")
            break
        
        time.sleep(wait_interval)
        elapsed += wait_interval
    
    if not streamer.is_running:
        logger.warning(f"generate_single_stream_frames({stream_id}): Timeout waiting for streamer")
        return
    
    # Check if stream index is valid
    with streamer.lock:
        if stream_index not in streamer.wall.handlers or not streamer.wall.handlers[stream_index]:
            logger.error(f"generate_single_stream_frames({stream_id}): Invalid stream index {stream_index}")
            error_frame = generate_placeholder_frame(text=f"Invalid Stream {stream_index}")
            try:
                frame_bytes = encode_frame_to_jpeg(error_frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n'
                       b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                       frame_bytes + b'\r\n')
            except:
                pass
            return
    
    logger.info(f"generate_single_stream_frames({stream_id}): Starting frame stream for index {stream_index}")
    
    while streamer.is_running:
        with streamer.lock:
            handler = streamer.wall.handlers.get(stream_index)
            if handler:
                frame = handler.get_frame()
            else:
                frame = None
        
        if frame is None:
            time.sleep(0.01)
            continue
        
        try:
            frame_bytes = encode_frame_to_jpeg(frame)
            frame_count += 1
            
            if frame_count % 300 == 0:
                logger.debug(f"generate_single_stream_frames({stream_id}): Sent {frame_count} frames")
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                   frame_bytes + b'\r\n')
        except Exception as e:
            logger.error(f"generate_single_stream_frames({stream_id}): Error encoding frame: {str(e)}")
            break
    
    logger.info(f"generate_single_stream_frames({stream_id}): Stream ended after {frame_count} frames")


@app.route('/stream/<int:stream_index>')
def stream_fullscreen(stream_index):
    """Fullscreen stream endpoint for individual camera"""
    logger.debug(f"Fullscreen request for stream {stream_index}")
    return Response(
        generate_single_stream_frames(stream_index),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/status')
def api_status():
    """Get wall status"""
    status = streamer.get_status()
    config = load_config()
    status['dev_mode'] = config.get('dev_mode', False)
    return jsonify(status)


@app.route('/api/start', methods=['POST'])
def api_start():
    """Start the video wall"""
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
        
        logger.info(f"Calling streamer.start() with {len(streams)} streams")
        success = streamer.start(streams, cols, rows, width, height)
        
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
    """Stop the video wall"""
    streamer.stop()
    return jsonify({'status': 'stopped'})


@app.route('/api/config', methods=['GET'])
def api_get_config():
    """Get current configuration"""
    config = load_config()
    return jsonify(config)


@app.route('/api/config', methods=['POST'])
def api_set_config():
    """Update configuration (in-memory for toggles to avoid Permission Denied)"""
    try:
        data = request.get_json() or {}
        global session_bbox_toggles
        
        # New bbox toggles from the request - store in memory ONLY
        new_bbox_toggles = data.get('bbox_toggles', {})
        old_bbox_toggles = session_bbox_toggles.copy()
        session_bbox_toggles = new_bbox_toggles
        
        # If the wall is running, detect which streams changed their BBOX toggle
        if streamer.is_running:
            streams_info = parse_deepstream_uris()
            if streams_info:
                for i, info in enumerate(streams_info):
                    idx_str = str(i)
                    new_val = session_bbox_toggles.get(idx_str, False)
                    old_val = old_bbox_toggles.get(idx_str, False)
                    
                    if new_val != old_val:
                        target_url = info['bbox'] if new_val else info['source']
                        logger.info(f"Dynamic BBOX update: Stream {i} toggle changed to {new_val}. URL: {target_url}")
                        streamer.update_stream(i, target_url)
        
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
    """Get list of available streams based on per-stream BBOX mode toggles"""
    try:
        config = load_config()
        
        # This function handles the per-stream toggle logic based on the loaded config
        streams, dev_mode = get_streams_from_config()
        
        return jsonify({
            'streams': streams,
            'dev_mode': dev_mode,
            'bbox_toggles': session_bbox_toggles
        })
    except Exception as e:
        logger.error(f"Error getting streams: {str(e)}")
        return jsonify({'error': str(e), 'streams': []}), 500


@app.route('/api/reparse-configs', methods=['POST'])
def api_reparse_configs():
    """Force re-parse of deepstream config files and sync live wall"""
    try:
        logger.info("Force re-parsing deepstream configs (POST /api/reparse-configs)")
        streams_info = parse_deepstream_uris()
        
        updates_applied = 0
        if streamer.is_running and streamer.wall:
            for i, info in enumerate(streams_info):
                # Don't try to update more streams than the wall has cells
                if i >= streamer.wall.total_cells:
                    break
                    
                # Determine what the current URL should be for this cell
                is_bbox = session_bbox_toggles.get(str(i), False)
                if is_bbox and 'bbox' in info:
                    target_url = info['bbox']
                else:
                    target_url = info['source']
                
                # Check if the URL changed for this live slot
                current_url = streamer.wall.streams[i]
                if target_url != current_url:
                    logger.info(f"Sync: Stream {i} changed from {current_url} to {target_url}")
                    streamer.update_stream(i, target_url)
                    updates_applied += 1
        
        return jsonify({
            'status': 'success', 
            'total_streams': len(streams_info),
            'updates': updates_applied
        })
    except Exception as e:
        logger.error(f"Error in re-parsing configs: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ============================================================================
# Save Mode - Recording Endpoints
# ============================================================================

@app.route('/api/save-mode/config', methods=['GET'])
def api_savemode_config():
    """Get available streams for recording"""
    config = load_config()
    
    # Check if client is passing dev_mode state (to handle UI toggle before saving config)
    dev_mode_param = request.args.get('dev_mode', '').lower()
    
    if dev_mode_param in ['true', 'false']:
        # Use the dev_mode from the request (current UI state)
        dev_mode = dev_mode_param == 'true'
        logger.info(f"api_savemode_config: Using dev_mode from request: {dev_mode}")
    else:
        # Fall back to config file
        _, dev_mode = get_streams_from_config()
        logger.info(f"api_savemode_config: Using dev_mode from config file: {dev_mode}")
    
    # Get streams based on dev_mode
    available_streams = []
    if dev_mode:
        test_vids = config.get('test_vids', [])
        for i, url in enumerate(test_vids):
            available_streams.append({
                'id': i,
                'name': f"Test Video {i+1}",
                'source': url,
                'type': 'source'
            })
        logger.debug(f"api_savemode_config: Returning {len(available_streams)} test videos")
    else:
        # Instead of just reading from config.yaml, use the parsed DeepStream URIs
        streams_info = parse_deepstream_uris()
        if streams_info:
            for i, info in enumerate(streams_info):
                # Add Source stream
                available_streams.append({
                    'id': i,
                    'name': f"Camera {i+1} (Source)",
                    'url': info['source'],
                    'type': 'source'
                })
                # Add BBOX stream if available
                if 'bbox' in info and info['bbox']:
                    available_streams.append({
                        'id': i,
                        'name': f"Camera {i+1} (BBOX)",
                        'url': info['bbox'],
                        'type': 'bbox'
                    })
            logger.info(f"api_savemode_config: Returning {len(available_streams)} parsed streams")
        else:
            streams = config.get('streams', [])
            for i, url in enumerate(streams):
                available_streams.append({
                    'id': i,
                    'name': f"Camera {i+1}",
                    'url': url,
                    'type': 'source'
                })
            logger.debug(f"api_savemode_config: Returning {len(available_streams)} RTSP streams from config.yaml")
    
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


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Video Wall Web Server Starting")
    logger.info("=" * 60)
    
    # Check shared volume
    file_count = check_shared_volume()
    
    logger.info("=" * 60)
    app.run(host='0.0.0.0', port=5002, debug=False, threaded=True)
