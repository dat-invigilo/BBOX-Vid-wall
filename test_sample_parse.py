
import yaml
import os
import traceback
import sys

def parse_deepstream_uris_logic(config_file_path):
    """Extracted parsing logic from web_server.py for testing"""
    streams_info = []
    
    if not os.path.exists(config_file_path):
        print(f"Error: {config_file_path} not found")
        return []
    
    try:
        sources = {}  # appearance_index -> uri
        sinks = {}    # source_id -> rtsp_port (only for type 4)
        
        current_section = None
        current_uri = None
        current_type = None
        current_rtsp_port = None
        current_sink_source_id = None

        def flush_section():
            nonlocal current_section, current_uri, current_type, current_rtsp_port, current_sink_source_id
            if not current_section:
                return
                
            if current_section.startswith('source'):
                source_idx = len(sources)
                if current_uri:
                    sources[source_idx] = current_uri
            elif current_section.startswith('sink'):
                if current_type == '4' and current_rtsp_port and current_sink_source_id is not None:
                    try:
                        sinks[int(current_sink_source_id)] = current_rtsp_port
                    except ValueError:
                        pass
            
            # Reset for next section
            current_type = None
            current_rtsp_port = None
            current_sink_source_id = None
            current_uri = None

        with open(config_file_path, 'r') as f:
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
        
        for i in sorted(sources.keys()):
            stream_info = {'source': sources[i]}
            if i in sinks:
                stream_info['bbox'] = f'rtsp://localhost:{sinks[i]}/ds-test'
            streams_info.append(stream_info)
            
    except Exception as e:
        print(f"Error parsing: {str(e)}")
        traceback.print_exc()
    
    return streams_info

if __name__ == "__main__":
    target_file = "/home/invigilo/BBOX-Vid-wall/sample_deepstream_config.txt"
    print(f"Parsing {target_file}...")
    results = parse_deepstream_uris_logic(target_file)
    
    if not results:
        print("No streams found.")
    else:
        for i, res in enumerate(results):
            print(f"Stream {i}:")
            print(f"  Source: {res.get('source')}")
            print(f"  BBOX:   {res.get('bbox', 'None')}")
