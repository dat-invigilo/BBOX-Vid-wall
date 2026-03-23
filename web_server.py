"""
Web Server for Video Wall Application
Serves video wall display via HTTP streaming
"""
import cv2
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


def load_config():
    """Load configuration from file"""
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Could not load config: {str(e)}")
    return {}


def get_streams_from_config():
    """Get streams based on dev_mode setting"""
    config = load_config()
    dev_mode = config.get('dev_mode', False)
    
    if dev_mode:
        streams = config.get('test_vids', [])
    else:
        streams = config.get('streams', [])
    
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


def generate_placeholder_frame(width=1280, height=720):
    """Generate a placeholder/waiting frame"""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Create a dark blue background
    frame[:] = (40, 40, 80)
    
    # Add text
    font = cv2.FONT_HERSHEY_SIMPLEX
    text = "Waiting for video stream..."
    font_scale = 1.0
    thickness = 2
    color = (200, 200, 200)
    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    text_x = (width - text_size[0]) // 2
    text_y = (height - text_size[1]) // 2
    cv2.putText(frame, text, (text_x, text_y), font, font_scale, color, thickness)
    
    return frame

def generate_frames():
    """Generate video stream frames"""
    logger.info("generate_frames(): Starting - waiting for streamer to be ready")
    
    # Wait for streamer to start (with timeout to avoid infinite wait)
    timeout = 30  # 30 seconds
    elapsed = 0
    wait_interval = 0.5
    frame_count = 0
    
    # Send placeholder frames while waiting for streamer
    while not streamer.is_running and elapsed < timeout:
        logger.debug(f"generate_frames(): Streamer not running yet, waiting... ({elapsed:.1f}s / {timeout}s)")
        
        # Generate placeholder frame to keep connection alive
        placeholder = generate_placeholder_frame()
        try:
            ret, buffer = cv2.imencode('.jpg', placeholder)
            frame_bytes = buffer.tobytes()
            frame_count += 1
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                   frame_bytes + b'\r\n')
        except Exception as e:
            logger.error(f"generate_frames(): Error creating placeholder: {str(e)}")
        
        time.sleep(wait_interval)
        elapsed += wait_interval
    
    if not streamer.is_running:
        logger.warning("generate_frames(): Timeout waiting for streamer to start")
        return
    
    logger.info(f"generate_frames(): Streamer is running, starting frame generation (sent {frame_count} placeholder frames during wait)")
    
    while streamer.is_running:
        frame = streamer.get_frame()
        if frame is None:
            time.sleep(0.01)  # Small delay if no frame available
            continue
        
        try:
            # Encode frame to JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            frame_count += 1
            if frame_count % 30 == 0:  # Log every 30 frames (~1 second at 30fps)
                logger.debug(f"generate_frames(): Sent {frame_count} total frames")
            
            # Yield frame in MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
                   frame_bytes + b'\r\n')
        except Exception as e:
            logger.error(f"generate_frames(): Error encoding frame: {str(e)}")
            continue
    
    logger.info(f"generate_frames(): Stream ended after {frame_count} total frames")


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
    """Update configuration"""
    try:
        data = request.get_json() or {}
        config = {
            'dev_mode': data.get('dev_mode', False),
            'test_vids': data.get('test_vids', []),
            'cols': data.get('cols', 2),
            'rows': data.get('rows', 2),
            'resolution': data.get('resolution', '1920x1080'),
            'streams': data.get('streams', []),
            'performance': data.get('performance', {
                'buffer_size': 2,
                'max_fps': 30,
                'reconnect_delay': 2
            }),
            'save_mode': data.get('save_mode', {
                'enabled': False,
                'output_directory': './recordings',
                'fps': 30,
                'recording_width': 1920,
                'recording_height': 1080,
                'chunk_duration_minutes': 60,
                'total_rotation_minutes': 1440,
                'cleanup_incomplete': True,
                'disk_space_alert_gb': 10
            })
        }
        
        with open(config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        return jsonify({'status': 'saved'})
    except Exception as e:
        logger.error(f"Error in api_set_config: {str(e)}")
        return jsonify({'error': str(e)}), 500


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
    if dev_mode:
        streams = config.get('test_vids', [])
        logger.debug(f"api_savemode_config: Returning {len(streams)} test videos")
    else:
        streams = config.get('streams', [])
        logger.debug(f"api_savemode_config: Returning {len(streams)} RTSP streams")
    
    return jsonify({
        'dev_mode': dev_mode,
        'available_streams': streams,
        'save_mode_config': config.get('save_mode', {})
    })


@app.route('/api/save-mode/start', methods=['POST'])
def api_savemode_start():
    """Start recording selected streams"""
    global recorder
    
    try:
        data = request.get_json() or {}
        selected_indices = data.get('stream_indices', [])
        dev_mode = data.get('dev_mode', False)  # Get dev_mode from request
        
        logger.info(f"api_savemode_start: dev_mode={dev_mode}, selected_indices={selected_indices}")
        
        config = load_config()
        
        # Use dev_mode from request parameter (current UI state), not from config
        if dev_mode:
            streams = config.get('test_vids', [])
            logger.info(f"api_savemode_start: Using {len(streams)} test videos")
        else:
            streams = config.get('streams', [])
            logger.info(f"api_savemode_start: Using {len(streams)} RTSP streams")
        
        if not selected_indices:
            return jsonify({'error': 'No streams selected'}), 400
        
        # Build streams dict from selected indices
        streams_dict = {}
        for idx in selected_indices:
            if 0 <= idx < len(streams):
                streams_dict[idx] = streams[idx]
                logger.debug(f"api_savemode_start: Added stream {idx}: {streams[idx]}")
        
        if not streams_dict:
            logger.error(f"api_savemode_start: No valid streams found for indices: {selected_indices}")
            return jsonify({'error': 'Invalid stream indices'}), 400
        
        # Get save mode config
        save_config = config.get('save_mode', {})
        output_dir = save_config.get('output_directory', './recordings')
        chunk_minutes = save_config.get('chunk_duration_minutes', 60)
        rotation_minutes = save_config.get('total_rotation_minutes', 1440)
        fps = save_config.get('fps', 30)
        width = save_config.get('recording_width', 1920)
        height = save_config.get('recording_height', 1080)
        
        logger.info(f"api_savemode_start: Starting recorder with {len(streams_dict)} streams")
        
        # Create and start recorder
        recorder = VideoWallRecorder(
            output_dir=output_dir,
            chunk_duration_minutes=chunk_minutes,
            total_rotation_minutes=rotation_minutes,
            fps=fps,
            width=width,
            height=height
        )
        
        success = recorder.start_recording(streams_dict)
        
        if success:
            logger.info(f"api_savemode_start: Recording started successfully")
            return jsonify({
                'status': 'recording',
                'streams': list(streams_dict.keys()),
                'chunk_duration_min': chunk_minutes,
                'rotation_hours': rotation_minutes // 60
            })
        else:
            logger.error("api_savemode_start: Failed to start recording")
            return jsonify({'error': 'Failed to start recording'}), 500
            
    except Exception as e:
        logger.error(f"Error in api_savemode_start: {str(e)}")
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
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
