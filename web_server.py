"""
Web Server for Video Wall Application
Serves video wall display via HTTP streaming
"""
import cv2
import threading
from flask import Flask, render_template, Response, jsonify, request
from video_wall import VideoWallDisplay
import logging
import yaml
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Global state
video_wall = None
wall_thread = None
is_running = False
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
                return False
            
            try:
                self.wall = VideoWallDisplay(
                    streams=streams,
                    cols=cols,
                    rows=rows,
                    output_width=width,
                    output_height=height
                )
                self.wall.start()
                self.is_running = True
                logger.info(f"Video wall started: {len(streams)} streams")
                return True
            except Exception as e:
                logger.error(f"Error starting video wall: {str(e)}")
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


def generate_frames():
    """Generate video stream frames"""
    while streamer.is_running:
        frame = streamer.get_frame()
        if frame is None:
            continue
        
        # Encode frame to JPEG
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        
        # Yield frame in MJPEG format
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n'
               b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
               frame_bytes + b'\r\n')


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
        data = request.get_json() or {}
        streams = data.get('streams') or []
        cols = data.get('cols', 2)
        rows = data.get('rows', 2)
        width = data.get('width', 1920)
        height = data.get('height', 1080)
        
        if not streams:
            return jsonify({'error': 'No streams provided'}), 400
        
        success = streamer.start(streams, cols, rows, width, height)
        if success:
            return jsonify({'status': 'started'})
        else:
            return jsonify({'error': 'Failed to start video wall'}), 500
    except Exception as e:
        logger.error(f"Error in api_start: {str(e)}")
        return jsonify({'error': str(e)}), 500


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
            })
        }
        
        with open(config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        return jsonify({'status': 'saved'})
    except Exception as e:
        logger.error(f"Error in api_set_config: {str(e)}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
