"""
Unit tests for Video Wall Application
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
from video_wall import VideoWallDisplay
from stream_handler import RTSPStreamHandler


class TestStreamHandler(unittest.TestCase):
    """Test RTSPStreamHandler"""
    
    def setUp(self):
        self.handler = RTSPStreamHandler('rtsp://test', 0)
    
    def test_initialization(self):
        """Test stream handler initialization"""
        self.assertEqual(self.handler.stream_id, 0)
        self.assertEqual(self.handler.rtsp_url, 'rtsp://test')
        self.assertFalse(self.handler.is_running)
    
    def test_placeholder_creation(self):
        """Test placeholder frame creation"""
        wall = VideoWallDisplay(['rtsp://test'], 1, 1, 640, 480)
        placeholder = wall._create_placeholder(640, 480, 'Test')
        
        self.assertEqual(placeholder.shape, (480, 640, 3))
        self.assertEqual(placeholder.dtype, np.uint8)
    
    def test_frame_resizing(self):
        """Test frame resizing with aspect ratio"""
        wall = VideoWallDisplay(['rtsp://test'], 1, 1, 640, 480)
        
        # Create test frame
        test_frame = np.ones((1080, 1920, 3), dtype=np.uint8)
        
        # Resize to cell
        resized = wall._resize_frame(test_frame, 640, 480, 0)
        
        self.assertEqual(resized.shape, (480, 640, 3))
    
    def test_wall_initialization(self):
        """Test VideoWallDisplay initialization"""
        streams = ['rtsp://cam1', 'rtsp://cam2', 'rtsp://cam3', 'rtsp://cam4']
        wall = VideoWallDisplay(streams, 2, 2, 1920, 1080)
        
        self.assertEqual(wall.cols, 2)
        self.assertEqual(wall.rows, 2)
        self.assertEqual(wall.output_width, 1920)
        self.assertEqual(wall.output_height, 1080)
        self.assertEqual(wall.cell_width, 960)
        self.assertEqual(wall.cell_height, 540)


class TestVideoWallDisplay(unittest.TestCase):
    """Test VideoWallDisplay"""
    
    def test_dimensions(self):
        """Test output dimensions"""
        wall = VideoWallDisplay(['rtsp://test'], 1, 1, 1280, 720)
        width, height = wall.get_output_dimensions()
        self.assertEqual(width, 1280)
        self.assertEqual(height, 720)
    
    def test_cell_dimensions(self):
        """Test cell dimensions for grid"""
        wall = VideoWallDisplay(['rtsp://test'], 2, 2, 1920, 1080)
        width, height = wall.get_cell_dimensions()
        self.assertEqual(width, 960)
        self.assertEqual(height, 540)
    
    def test_stream_padding(self):
        """Test that stream list is padded to grid size"""
        wall = VideoWallDisplay(['rtsp://cam1', 'rtsp://cam2'], 2, 2, 1920, 1080)
        self.assertEqual(len(wall.streams), 4)


if __name__ == '__main__':
    unittest.main()
