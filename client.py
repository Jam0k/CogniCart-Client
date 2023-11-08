from flask import Flask, jsonify, send_file
import psutil
import socket
import subprocess
import logging
import json
import os
from datetime import datetime
from io import BytesIO

app = Flask(__name__)

# Ensure the config and logs directories exist
config_dir = 'config'
logs_dir = 'logs'
config_file_path = os.path.join(config_dir, 'config.json')

if not os.path.exists(config_dir):
    os.makedirs(config_dir)

if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Default configuration
default_config = {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": True,
    "log_file": os.path.join(logs_dir, "app.log")
}

# Check if config.json exists, if not, create it with default values
if not os.path.isfile(config_file_path):
    with open(config_file_path, 'w') as config_file:
        json.dump(default_config, config_file, indent=4)

# Load configuration from config.json
with open(config_file_path) as config_file:
    config = json.load(config_file)

# Set up logging to file and console
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(message)s',
                    handlers=[
                        logging.FileHandler(config.get('log_file', default_config['log_file'])),
                        logging.StreamHandler()
                    ])

def fetch_data_from_system(command, error_message="N/A"):
    try:
        return subprocess.check_output(command).strip().decode()
    except Exception as e:
        logging.exception(f"Error executing system command: {e}")
        return error_message

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        disk_info = psutil.disk_usage('/')
        
        health_data = {
            "status": "Online",
            "cpu_usage": f"{cpu_usage}%",
            "memory_usage": f"{memory_info.percent}%",
            "disk_usage": f"{disk_info.percent}%"
        }
        
        logging.info("Health check data fetched successfully.")
        return jsonify(health_data)
    except Exception as e:
        logging.exception("Error fetching health data.")
        return jsonify({"status": "Error fetching health data"})

@app.route('/api/network_settings', methods=['GET'])
def network_settings():
    try:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        mac_address = fetch_data_from_system(["cat", "/sys/class/net/eth0/address"])
        wifi_ssid = fetch_data_from_system(["iwgetid", "-r"])

        network_data = {
            "status": "Online",
            "hostname": hostname,
            "ip_address": ip_address,
            "mac_address": mac_address,
            "wifi_ssid": wifi_ssid
        }
        
        logging.info("Network settings fetched successfully.")
        return jsonify(network_data)
    except Exception as e:
        logging.exception("Error fetching network settings.")
        return jsonify({"status": f"Error fetching network data: {str(e)}"})

@app.route('/api/ntp_check', methods=['GET'])
def ntp_check_client():
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logging.info("NTP check successful.")
        return jsonify({"status": "Online", "current_ntp_time": current_time})
    except Exception as e:
        logging.exception("Error fetching NTP data.")
        return jsonify({"status": "Error fetching system time", "error": str(e)})

@app.route('/api/camera_check', methods=['GET'])
def camera_check():
    try:
        camera_status = subprocess.check_output(["vcgencmd", "get_camera"]).strip().decode()
        logging.info("Camera check successful.")
        return jsonify({"status": "Online", "camera_status": camera_status})
    except Exception as e:
        logging.exception("Error fetching camera data.")
        return jsonify({"status": f"Error fetching camera data: {str(e)}"})

@app.route('/api/take_photo', methods=['GET'])
def take_photo():
    try:
        image_stream = BytesIO()
        process = subprocess.Popen(["libcamera-still", "-o", "-"], stdout=subprocess.PIPE)
        out, err = process.communicate()
        image_stream.write(out)
        image_stream.seek(0)
        logging.info("Photo taken successfully.")
        return send_file(image_stream, mimetype='image/jpeg', as_attachment=True, download_name='photo.jpg')
    except Exception as e:
        logging.exception("Error capturing photo.")
        return jsonify({"status": f"Error capturing photo: {str(e)}"})

if __name__ == '__main__':
    # Use the host and port from the configuration
    app.run(host=config.get('host', default_config['host']),
            port=config.get('port', default_config['port']),
            debug=config.get('debug', default_config['debug']))
