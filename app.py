"""
Video Wall Application - Main application entry point
Displays multiple RTSP streams in a grid with PyQt5 GUI using FFmpeg
"""
import sys
import logging
from typing import List
from PyQt5.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                              QHBoxLayout, QWidget, QPushButton, QLineEdit, 
                              QComboBox, QSpinBox, QFileDialog, QTextEdit, QMessageBox)
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from video_wall import VideoWallDisplay
import yaml
import os
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VideoWallThread(QThread):
    """Separate thread for video wall processing"""
    frame_ready = pyqtSignal(QImage)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, video_wall: VideoWallDisplay):
        super().__init__()
        self.video_wall = video_wall
        self.is_running = True
    
    def run(self):
        """Main thread loop"""
        try:
            self.video_wall.start()
            while self.is_running:
                # Get composite frame
                wall_frame = self.video_wall.get_wall_frame()
                
                # Convert BGR to RGB for display (reverse channel order)
                rgb_frame = wall_frame[:, :, ::-1].copy()
                
                # Convert to QImage
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                
                self.frame_ready.emit(qt_image)
                
                # Control frame rate
                self.msleep(33)  # ~30 FPS
        except Exception as e:
            logger.error(f"Error in video wall thread: {str(e)}")
            self.error_occurred.emit(f"Error: {str(e)}")
    
    def stop(self):
        """Stop the thread gracefully"""
        self.is_running = False
        self.video_wall.stop()
        self.wait()


class VideoWallApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.video_wall = None
        self.wall_thread = None
        self.config_file = 'config.yaml'
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle('Video Wall Application')
        self.setGeometry(100, 100, 1400, 1000)
        
        # Main layout
        main_layout = QHBoxLayout()
        
        # Left panel - Controls
        control_panel = QVBoxLayout()
        control_panel.setSpacing(10)
        
        # Title
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title = QLabel('Video Wall Configuration')
        title.setFont(title_font)
        control_panel.addWidget(title)
        
        # Development Mode Toggle
        control_panel.addWidget(QLabel('Mode:'))
        mode_layout = QHBoxLayout()
        from PyQt5.QtWidgets import QCheckBox
        self.dev_mode_check = QCheckBox('Development Mode')
        self.dev_mode_check.stateChanged.connect(self.on_dev_mode_changed)
        mode_layout.addWidget(self.dev_mode_check)
        mode_layout.addStretch()
        control_panel.addLayout(mode_layout)
        
        # Grid settings
        control_panel.addWidget(QLabel('Grid Layout:'))
        grid_layout = QHBoxLayout()
        grid_layout.addWidget(QLabel('Columns:'))
        self.cols_spin = QSpinBox()
        self.cols_spin.setValue(2)
        self.cols_spin.setRange(1, 4)
        grid_layout.addWidget(self.cols_spin)
        
        grid_layout.addWidget(QLabel('Rows:'))
        self.rows_spin = QSpinBox()
        self.rows_spin.setValue(2)
        self.rows_spin.setRange(1, 4)
        grid_layout.addWidget(self.rows_spin)
        
        control_panel.addLayout(grid_layout)
        
        # Output resolution
        control_panel.addWidget(QLabel('Output Resolution:'))
        resolution_layout = QHBoxLayout()
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(['1920x1080', '1280x720', '2560x1440', 'Custom'])
        resolution_layout.addWidget(self.resolution_combo)
        control_panel.addLayout(resolution_layout)
        
        # Stream URLs
        control_panel.addWidget(QLabel('RTSP Streams (one per line):'))
        self.streams_text = QTextEdit()
        self.streams_text.setPlaceholderText('rtsp://camera1.local/stream\nrtsp://camera2.local/stream\n...')
        self.streams_text.setMaximumHeight(150)
        control_panel.addWidget(self.streams_text)
        
        # Test Videos
        control_panel.addWidget(QLabel('Test Videos (one per line):'))
        self.test_vids_text = QTextEdit()
        self.test_vids_text.setPlaceholderText('./test_videos/sample1.mp4\n./test_videos/sample2.mp4\n...')
        self.test_vids_text.setMaximumHeight(150)
        self.test_vids_text.setEnabled(False)
        control_panel.addWidget(self.test_vids_text)
        
        # File operations
        file_layout = QHBoxLayout()
        load_btn = QPushButton('Load Config')
        load_btn.clicked.connect(self.load_config_dialog)
        file_layout.addWidget(load_btn)
        
        save_btn = QPushButton('Save Config')
        save_btn.clicked.connect(self.save_config_dialog)
        file_layout.addWidget(save_btn)
        
        control_panel.addLayout(file_layout)
        
        # Start/Stop buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton('Start Wall')
        self.start_btn.clicked.connect(self.start_wall)
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton('Stop Wall')
        self.stop_btn.clicked.connect(self.stop_wall)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        button_layout.addWidget(self.stop_btn)
        
        control_panel.addLayout(button_layout)
        
        # Status
        control_panel.addWidget(QLabel('Status:'))
        self.status_label = QLabel('Ready')
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        control_panel.addWidget(self.status_label)
        
        control_panel.addStretch()
        
        # Right panel - Video display
        display_layout = QVBoxLayout()
        
        self.video_label = QLabel()
        self.video_label.setMinimumSize(960, 540)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        display_layout.addWidget(self.video_label)
        
        # Create main widget
        main_widget = QWidget()
        main_layout.addLayout(control_panel, 1)
        main_layout.addLayout(display_layout, 2)
        main_widget.setLayout(main_layout)
        
        self.setCentralWidget(main_widget)
    
    def get_resolution(self) -> tuple:
        """Get output resolution"""
        res_map = {
            '1920x1080': (1920, 1080),
            '1280x720': (1280, 720),
            '2560x1440': (2560, 1440),
        }
        resolution = self.resolution_combo.currentText()
        if resolution in res_map:
            return res_map[resolution]
        return (1920, 1080)
    
    def get_streams(self) -> List[str]:
        """Get list of stream URLs from text field"""
        if self.dev_mode_check.isChecked():
            # Use test videos in dev mode
            vids_text = self.test_vids_text.toPlainText().strip()
            streams = [s.strip() for s in vids_text.split('\n') if s.strip()]
        else:
            # Use RTSP streams in normal mode
            streams_text = self.streams_text.toPlainText().strip()
            streams = [s.strip() for s in streams_text.split('\n') if s.strip()]
        return streams
    
    def start_wall(self):
        """Start the video wall"""
        try:
            streams = self.get_streams()
            if not streams:
                mode = "test videos" if self.dev_mode_check.isChecked() else "RTSP streams"
                QMessageBox.warning(self, 'Error', f'Please enter at least one {mode}')
                return
            
            cols = self.cols_spin.value()
            rows = self.rows_spin.value()
            width, height = self.get_resolution()
            
            # Create video wall
            self.video_wall = VideoWallDisplay(
                streams=streams,
                cols=cols,
                rows=rows,
                output_width=width,
                output_height=height
            )
            
            # Create and start thread
            self.wall_thread = VideoWallThread(self.video_wall)
            self.wall_thread.frame_ready.connect(self.update_display)
            self.wall_thread.error_occurred.connect(self.handle_error)
            self.wall_thread.start()
            
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.dev_mode_check.setEnabled(False)
            self.streams_text.setReadOnly(True)
            self.test_vids_text.setReadOnly(True)
            
            mode_text = "DEV MODE (Test Videos)" if self.dev_mode_check.isChecked() else "RTSP Mode"
            self.status_label.setText(f'Running - {cols}x{rows} grid, {width}x{height} - {mode_text}')
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            logger.info(f"Video wall started: {len(streams)} streams in {cols}x{rows} grid ({mode_text})")
            
        except Exception as e:
            logger.error(f"Error starting video wall: {str(e)}")
            QMessageBox.critical(self, 'Error', f'Failed to start video wall: {str(e)}')
    
    def stop_wall(self):
        """Stop the video wall"""
        try:
            if self.wall_thread:
                self.wall_thread.stop()
                self.wall_thread = None
            
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.dev_mode_check.setEnabled(True)
            self.streams_text.setReadOnly(False)
            self.test_vids_text.setReadOnly(False)
            self.status_label.setText('Stopped')
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.video_label.setPixmap(QPixmap())
            logger.info("Video wall stopped")
            
        except Exception as e:
            logger.error(f"Error stopping video wall: {str(e)}")
    
    def update_display(self, qt_image: QImage):
        """Update video display"""
        pixmap = QPixmap.fromImage(qt_image)
        scaled_pixmap = pixmap.scaledToWidth(960, Qt.SmoothTransformation)
        self.video_label.setPixmap(scaled_pixmap)
    
    def handle_error(self, error_msg: str):
        """Handle errors from video wall thread"""
        logger.error(error_msg)
        self.status_label.setText(error_msg)
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
    
    def on_dev_mode_changed(self, state):
        """Handle development mode toggle"""
        is_dev_mode = self.dev_mode_check.isChecked()
        self.streams_text.setEnabled(not is_dev_mode)
        self.test_vids_text.setEnabled(is_dev_mode)
        
        if is_dev_mode:
            self.status_label.setText('Development Mode: Using test videos')
            logger.info("Switched to Development Mode")
        else:
            self.status_label.setText('Normal Mode: Using RTSP streams')
            logger.info("Switched to Normal Mode")
    
    def load_config(self):
        """Load configuration from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f)
                
                if config:
                    self.cols_spin.setValue(config.get('cols', 2))
                    self.rows_spin.setValue(config.get('rows', 2))
                    
                    res = config.get('resolution', '1920x1080')
                    index = self.resolution_combo.findText(res)
                    if index >= 0:
                        self.resolution_combo.setCurrentIndex(index)
                    
                    # Dev mode
                    dev_mode = config.get('dev_mode', False)
                    self.dev_mode_check.setChecked(dev_mode)
                    
                    # Test videos
                    test_vids = config.get('test_vids', [])
                    self.test_vids_text.setText('\n'.join(test_vids))
                    
                    # RTSP streams
                    streams = config.get('streams', [])
                    self.streams_text.setText('\n'.join(streams))
                    
                    logger.info(f"Configuration loaded from {self.config_file}")
            except Exception as e:
                logger.warning(f"Could not load config file: {str(e)}")
    
    def load_config_dialog(self):
        """Open file dialog to load config"""
        file_path, _ = QFileDialog.getOpenFileName(self, 'Load Configuration', '', 'YAML Files (*.yaml);;All Files (*)')
        if file_path:
            self.config_file = file_path
            self.load_config()
    
    def save_config_dialog(self):
        """Open file dialog to save config"""
        file_path, _ = QFileDialog.getSaveFileName(self, 'Save Configuration', '', 'YAML Files (*.yaml)')
        if file_path:
            self.save_config(file_path)
    
    def save_config(self, file_path: str = None):
        """Save current configuration to file"""
        try:
            config = {
                'dev_mode': self.dev_mode_check.isChecked(),
                'test_vids': [v.strip() for v in self.test_vids_text.toPlainText().split('\n') if v.strip()],
                'cols': self.cols_spin.value(),
                'rows': self.rows_spin.value(),
                'resolution': self.resolution_combo.currentText(),
                'streams': self.get_streams()
            }
            
            save_path = file_path or self.config_file
            with open(save_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            
            logger.info(f"Configuration saved to {save_path}")
            self.status_label.setText(f'Config saved to {os.path.basename(save_path)}')
            self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        except Exception as e:
            logger.error(f"Error saving config: {str(e)}")
            QMessageBox.critical(self, 'Error', f'Failed to save configuration: {str(e)}')
    
    def closeEvent(self, event):
        """Handle application close"""
        if self.wall_thread:
            self.stop_wall()
        event.accept()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    window = VideoWallApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
