"""
CLI Utility for Video Wall Application
Provides command-line interface for headless operation using FFmpeg
"""
import argparse
import yaml
import sys
import logging
from typing import List
from video_wall import VideoWallDisplay
import subprocess
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_config(config_file: str) -> dict:
    """Load configuration from YAML file"""
    try:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error(f"Config file not found: {config_file}")
        sys.exit(1)


def run_headless(streams: List[str], cols: int, rows: int, 
                 width: int, height: int, output_file: str = None):
    """Run video wall in headless mode with optional file output"""
    logger.info(f"Starting headless video wall: {cols}x{rows} grid, {width}x{height}")
    
    # Initialize video wall
    wall = VideoWallDisplay(
        streams=streams,
        cols=cols,
        rows=rows,
        output_width=width,
        output_height=height
    )
    
    wall.start()
    
    if output_file:
        logger.info(f"Output to: {output_file}")
        # Start FFmpeg process to encode frames piped to stdin
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output file
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{width}x{height}',
            '-r', '30',  # Input frame rate
            '-i', 'pipe:0',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            output_file
        ]
        
        try:
            ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"FFmpeg process started (PID: {ffmpeg_process.pid})")
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {str(e)}")
            ffmpeg_process = None
    else:
        ffmpeg_process = None
    
    try:
        frame_count = 0
        start_time = time.time()
        
        while True:
            frame = wall.get_wall_frame()
            if frame is not None:
                if ffmpeg_process:
                    try:
                        ffmpeg_process.stdin.write(frame.tobytes())
                    except (BrokenPipeError, OSError):
                        logger.error("FFmpeg process pipe broken, stopping output")
                        ffmpeg_process = None
                
                frame_count += 1
                
                if frame_count % 300 == 0:  # Log every 10 seconds at 30fps
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    logger.info(f"Frames processed: {frame_count}, FPS: {fps:.1f}")
            
            time.sleep(0.033)  # ~30 FPS
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        wall.stop()
        if ffmpeg_process:
            try:
                ffmpeg_process.stdin.close()
                ffmpeg_process.wait(timeout=5)
                logger.info(f"Video saved to {output_file}")
            except Exception as e:
                logger.error(f"Error closing FFmpeg: {str(e)}")


def main():
    parser = argparse.ArgumentParser(
        description='Video Wall CLI - Display RTSP streams in a grid'
    )
    
    # Config file
    parser.add_argument('--config', default='config.yaml',
                       help='Configuration file (default: config.yaml)')
    
    # Grid layout
    parser.add_argument('--cols', type=int, default=2,
                       help='Number of columns (default: 2)')
    parser.add_argument('--rows', type=int, default=2,
                       help='Number of rows (default: 2)')
    
    # Resolution
    parser.add_argument('--width', type=int, default=1920,
                       help='Output width (default: 1920)')
    parser.add_argument('--height', type=int, default=1080,
                       help='Output height (default: 1080)')
    
    # Streams
    parser.add_argument('--streams', nargs='+',
                       help='RTSP stream URLs')
    
    # Output
    parser.add_argument('--output', 
                       help='Output video file (MP4 format)')
    
    # Mode
    parser.add_argument('--headless', action='store_true',
                       help='Run in headless mode (no GUI)')
    
    args = parser.parse_args()
    
    # Load configuration if config file exists
    config = load_config(args.config) if args.config else {}
    
    # Override with command-line arguments
    cols = args.cols or config.get('cols', 2)
    rows = args.rows or config.get('rows', 2)
    width = args.width or config.get('width', 1920)
    height = args.height or config.get('height', 1080)
    streams = args.streams or config.get('streams', [])
    
    if not streams:
        logger.error("No streams specified. Use --streams or config file.")
        sys.exit(1)
    
    if args.headless:
        run_headless(streams, cols, rows, width, height, args.output)
    else:
        # Use GUI
        from app import main as gui_main
        gui_main()


if __name__ == '__main__':
    main()
