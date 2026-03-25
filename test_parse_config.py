import configparser
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_parse_deepstream_urls(file_path):
    config = configparser.ConfigParser(strict=False)
    config.read(file_path)
    
    # We need to find pairs of [sourceX] and [sinkY]
    # Based on the user's description, they are associated by their order or source-id.
    # Let's collect all sources and sinks.
    sources = []
    for section in config.sections():
        if section.startswith('source'):
            sources.append({
                'name': section,
                'uri': config.get(section, 'uri', fallback=None)
            })
    
    sinks = []
    for section in config.sections():
        if section.startswith('sink'):
            # Clear everything after #
            port_val = config.get(section, 'rtsp-port', fallback=None)
            if port_val:
                port_val = port_val.split('#')[0].strip()
            
            sinks.append({
                'name': section,
                'port': port_val,
                'source_id': config.get(section, 'source-id', fallback=None)
            })
    
    logger.info("--- URL Mapping Preview ---")
    # Assuming sources and sinks are paired by index/order as per the user's example
    for i in range(len(sources)):
        source_uri = sources[i]['uri']
        # Try to find sink by source-id or just use the same index if specified
        sink_port = sinks[i]['port'] if i < len(sinks) else "UNKNOWN"
        
        bbox_url = f"rtsp://localhost:{sink_port}/ds-test"
        
        logger.info(f"Source: {source_uri}")
        logger.info(f"BBOX Mode URL: {bbox_url}")
        logger.info("-" * 30)

if __name__ == "__main__":
    test_parse_deepstream_urls('sample_deepstream_config.txt')
