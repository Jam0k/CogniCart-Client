from picamera2 import Picamera2
from flask import Flask, jsonify
import threading
import requests
import cv2
import numpy as np
import base64
import logging
import time
import json
import os
from datetime import datetime


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

# Initialize global variables
motion_detected = False
stop_threads = False
central_server_url = "http://192.168.0.21:5000"  # Replace with your central server URL

# Initialize picamera2
picam2 = Picamera2()
picam2_config = picam2.create_preview_configuration()
picam2.configure(picam2_config)
picam2.start()

def motion_detection_thread():
    global motion_detected, stop_threads, picam2
    avg_frame = None
    last_motion_time = None
    motion_cooldown = 5  # Cooldown period in seconds after detecting motion
    frame_update_time = 2  # Time in seconds to update the average frame

    while not stop_threads:
        frame = picam2.capture_array()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if avg_frame is None:
            avg_frame = gray.copy().astype("float")
            last_motion_time = time.time()
            continue

        cv2.accumulateWeighted(gray, avg_frame, 0.5)
        frame_delta = cv2.absdiff(gray, cv2.convertScaleAbs(avg_frame))

        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion_detected = False
        for c in contours:
            if cv2.contourArea(c) < 1000:  # Adjust as needed for sensitivity
                continue
            motion_detected = True
            last_motion_time = time.time()
            logging.info("Motion detected!")
            break  # Once motion is detected, no need to check further contours

        if not motion_detected and last_motion_time and time.time() - last_motion_time >= motion_cooldown:
            # Reset the background frame after the cooldown period if no motion is detected
            first_frame = gray
            logging.info("Resetting background model.")

        time.sleep(0.1)



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

if __name__ == '__main__':
    # Start the motion detection thread
    motion_thread = threading.Thread(target=motion_detection_thread)
    motion_thread.daemon = True
    motion_thread.start()

    # Run Flask application
    app.run(host=config.get('host', '0.0.0.0'),
            port=config.get('port', 5000),
            debug=config.get('debug', True),
            use_reloader=False)  # Disable the reloader