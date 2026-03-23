"""
Video Wall Display - Displays multiple RTSP streams in a grid layout
"""
import cv2
import numpy as np
from typing import List, Dict, Optional
import logging
import traceback
from stream_handler import RTSPStreamHandler

logger = logging.getLogger(__name__)


class VideoWallDisplay:
    """Manages the video wall display with multiple streams"""
    
    def __init__(self, streams: List[str], cols: int = 2, rows: int = 2, 
                 output_width: int = 1920, output_height: int = 1080):
        """
        Initialize video wall display
        
        Args:
            streams: List of RTSP URLs
            cols: Number of columns in the grid
            rows: Number of rows in the grid
            output_width: Output video width
            output_height: Output video height
        """
        self.streams = streams
        self.cols = cols
        self.rows = rows
        self.output_width = output_width
        self.output_height = output_height
        self.total_cells = cols * rows
        
        # Pad streams list if needed
        while len(self.streams) < self.total_cells:
            self.streams.append(None)
        
        # Trim if too many streams
        self.streams = self.streams[:self.total_cells]
        
        # Calculate cell dimensions
        self.cell_width = output_width // cols
        self.cell_height = output_height // rows
        
        # Initialize stream handlers
        self.handlers: Dict[int, Optional[RTSPStreamHandler]] = {}
        for i, stream_url in enumerate(self.streams):
            if stream_url:
                self.handlers[i] = RTSPStreamHandler(stream_url, i)
            else:
                self.handlers[i] = None
        
        logger.info(f"VideoWall initialized: {cols}x{rows} grid, "
                   f"{output_width}x{output_height} output, {len([s for s in streams if s])} streams")
    
    def start(self):
        """Start all stream handlers"""
        try:
            logger.info(f"Starting {len(self.handlers)} stream handlers")
            started_count = 0
            for i, handler in self.handlers.items():
                if handler:
                    logger.info(f"Starting handler {i} for stream: {self.streams[i]}")
                    handler.start()
                    started_count += 1
                    logger.info(f"Handler {i} started successfully")
                else:
                    logger.debug(f"Handler {i} is None (empty cell)")
            logger.info(f"All {started_count} streams started successfully")
        except Exception as e:
            logger.error(f"Error starting streams: {str(e)}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            raise
    
    def stop(self):
        """Stop all stream handlers"""
        for handler in self.handlers.values():
            if handler:
                handler.stop()
        logger.info("All streams stopped")
    
    def _create_placeholder(self, width: int, height: int, text: str) -> np.ndarray:
        """Create a placeholder image for empty or missing streams"""
        placeholder = np.zeros((height, width, 3), dtype=np.uint8)
        placeholder[:] = (50, 50, 50)  # Dark gray background
        
        # Add text
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.0
        thickness = 2
        color = (200, 200, 200)
        
        # Get text size to center it
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        text_x = (width - text_size[0]) // 2
        text_y = (height + text_size[1]) // 2
        
        cv2.putText(placeholder, text, (text_x, text_y), font, 
                   font_scale, color, thickness)
        
        return placeholder
    
    def _resize_frame(self, frame: Optional[np.ndarray], width: int, 
                     height: int, cell_index: int) -> np.ndarray:
        """Resize frame to fit cell while maintaining aspect ratio"""
        if frame is None:
            return self._create_placeholder(width, height, f"No Signal - Cell {cell_index}")
        
        try:
            # Calculate aspect ratio
            frame_height, frame_width = frame.shape[:2]
            frame_aspect = frame_width / frame_height
            cell_aspect = width / height
            
            # Resize to fit
            if frame_aspect > cell_aspect:
                # Frame is wider
                new_width = width
                new_height = int(width / frame_aspect)
            else:
                # Frame is taller
                new_height = height
                new_width = int(height * frame_aspect)
            
            resized = cv2.resize(frame, (new_width, new_height))
            
            # Create output frame with padding
            output = np.zeros((height, width, 3), dtype=np.uint8)
            y_offset = (height - new_height) // 2
            x_offset = (width - new_width) // 2
            output[y_offset:y_offset + new_height, x_offset:x_offset + new_width] = resized
            
            return output
        except Exception as e:
            logger.error(f"Error resizing frame for cell {cell_index}: {str(e)}")
            return self._create_placeholder(width, height, f"Error - Cell {cell_index}")
    
    def get_wall_frame(self) -> np.ndarray:
        """Generate the composite video wall frame"""
        wall = np.zeros((self.output_height, self.output_width, 3), dtype=np.uint8)
        
        for idx in range(self.total_cells):
            row = idx // self.cols
            col = idx % self.cols
            
            y_start = row * self.cell_height
            x_start = col * self.cell_width
            
            # Get frame from handler
            handler = self.handlers.get(idx)
            if handler:
                frame = handler.get_frame()
            else:
                frame = None
            
            # Resize and place frame
            cell_frame = self._resize_frame(frame, self.cell_width, 
                                           self.cell_height, idx)
            wall[y_start:y_start + self.cell_height, 
                 x_start:x_start + self.cell_width] = cell_frame
            
            # Add grid lines
            cv2.rectangle(wall, (x_start, y_start), 
                         (x_start + self.cell_width, y_start + self.cell_height),
                         (200, 200, 200), 2)
        
        return wall
    
    def get_cell_dimensions(self) -> tuple:
        """Get (cell_width, cell_height)"""
        return (self.cell_width, self.cell_height)
    
    def get_output_dimensions(self) -> tuple:
        """Get (output_width, output_height)"""
        return (self.output_width, self.output_height)
