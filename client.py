import socket
import subprocess
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
import psutil

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
central_server_url = "http://87.242.203.182:5000"  # Replace with your central server URL

# Initialize picamera2 with high-resolution configuration
picam2 = Picamera2()
high_res_config = picam2.create_still_configuration()
high_res_config['main']['size'] = (4608, 2592)
picam2.configure(high_res_config)
picam2.start()

def send_heartbeat():
    try:
        # Include client_id in the heartbeat message
        heartbeat_data = {'client_id': config.get('client_id', 'default_client_id')}
        requests.post(f"{central_server_url}/heartbeat", json=heartbeat_data)
    except requests.RequestException as e:
        print(f"Error sending heartbeat: {e}")

def start_heartbeat_timer():
    threading.Timer(30, start_heartbeat_timer).start()
    send_heartbeat()

# Start the heartbeat timer
start_heartbeat_timer()

def motion_detection_thread():
    global motion_detected, stop_threads, picam2
    avg_frame = None
    last_motion_time = None
    motion_cooldown = 1  # Cooldown period in seconds, adjust as needed

    while not stop_threads:
        frame = picam2.capture_array()
        original_frame = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if avg_frame is None:
            avg_frame = gray.copy().astype("float")
            continue

        cv2.accumulateWeighted(gray, avg_frame, 0.5)
        frame_delta = cv2.absdiff(gray, cv2.convertScaleAbs(avg_frame))

        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion_in_this_frame = False
        for c in contours:
            if cv2.contourArea(c) < 1000:  # Adjust as needed for sensitivity
                continue
            motion_in_this_frame = True

            # Get the bounding box coordinates and draw a rectangle
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(original_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        if motion_in_this_frame:
            if last_motion_time is None or time.time() - last_motion_time >= motion_cooldown:
                last_motion_time = time.time()
                motion_detected = True

                # Encode the modified frame with rectangles
                _, buffer = cv2.imencode('.jpg', original_frame)
                photo_data = base64.b64encode(buffer).decode()

                # Send a POST request to the central server's motion_detected endpoint
                try:
                    response = requests.post(f"{central_server_url}/api/receive_image", 
                                             json={"image": photo_data, "client_id": config['client_id']})
                    if response.status_code == 200:
                        logging.info(f"Motion detected and alert sent to central server.")
                    else:
                        logging.error(f"Alert to central server failed with status code: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    logging.exception(f"Error sending alert to central server: {str(e)}")
        else:
            motion_detected = False

        time.sleep(0.1)  # Adjust the sleep time as needed

@app.route('/api/start_capture', methods=['POST'])
def start_capture():
    global capture_active
    capture_active = True
    return jsonify({"status": "Capture started"}), 200

@app.route('/api/stop_capture', methods=['POST'])
def stop_capture():
    global capture_active
    capture_active = False
    return jsonify({"status": "Capture stopped"}), 200

def take_and_send_frame():
    frame = picam2.capture_array()
    _, buffer = cv2.imencode('.jpg', frame)
    photo_data = base64.b64encode(buffer).decode()

    try:
        response = requests.post(
            f"{central_server_url}/api/receive_image", 
            json={"image": photo_data, "client_id": config['client_id']}
        )
        if response.status_code == 200:
            logging.info("Frame sent to server successfully.")
        else:
            logging.error("Failed to send frame to server.")
    except requests.exceptions.RequestException as e:
        logging.exception(f"Error sending frame to server: {str(e)}")



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
    frame = picam2.capture_array()
    # Convert the color space from BGR to RGB
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    _, buffer = cv2.imencode('.jpg', frame)
    photo_data = base64.b64encode(buffer).decode()

    try:
        response = requests.post(
            f"{central_server_url}/api/receive_image",
            json={"image": photo_data, "client_id": config['client_id']}
        )
        if response.status_code == 200:
            return jsonify({"status": "success", "image": photo_data})
        else:
            return jsonify({"status": "error", "message": "Failed to send image to server"})
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/manual_capture', methods=['GET'])
def manual_capture():
    try:
        # Capture and send frame from this client
        take_and_send_frame()
        logging.info("Manual capture triggered and frame sent to server.")

        # Notify the server to trigger motion detection process
        response = requests.post(f"{central_server_url}/api/motion_detected", json={"client_id": config['client_id']})
        if response.status_code == 200:
            logging.info("Server notified for manual motion detection.")
            return jsonify({"status": "success", "message": "Manual capture triggered and server notified"})
        else:
            logging.error("Failed to notify server for manual motion detection.")
            return jsonify({"status": "error", "message": "Failed to notify server"})

    except Exception as e:
        logging.exception(f"Error during manual capture: {str(e)}")
        return jsonify({"status": "error", "message": str(e)})


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