import os
import json
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify
import psutil
import socket
from functools import wraps

app = Flask(__name__)

# Paths for the directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
LOG_FILE_PATH = os.path.join(LOG_DIR, 'app.log')
CONFIG_FILE_PATH = os.path.join(CONFIG_DIR, 'config.json')

# Make sure the 'logs' and 'config' directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[RotatingFileHandler(LOG_FILE_PATH, maxBytes=10000, backupCount=3)]
)
logger = app.logger

# Configuration caching
_config = None

def load_config():
    global _config
    if _config is None:
        try:
            with open(CONFIG_FILE_PATH, 'r') as config_file:
                _config = json.load(config_file)
                logger.info("Successfully loaded configuration file.")
        except Exception as e:
            logger.error(f"Failed to load configuration file: {e}")
            _config = {}
    return _config

# Exception handling decorator
def handle_exceptions(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            return jsonify({"error": "An internal error occurred"}), 500
    return wrapped

# HEALTH CHECK ENDPOINTS #
@app.route('/api/health/system_status', methods=['GET'])
@handle_exceptions
def health_check():
    cpu_usage = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return jsonify({
        "status": "Online",
        "cpu_usage": f"{cpu_usage}%",
        "memory_usage": f"{memory.percent}%",
        "disk_usage": f"{disk.percent}%"
    })

@app.route('/api/health/network_status', methods=['GET'])
@handle_exceptions
def network_info():
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    return jsonify({
        "status": "Online",
        "hostname": hostname,
        "ip_address": ip_address
    })

@app.route('/api/health/config_status', methods=['GET'])
@handle_exceptions
def get_config():
    config_data = load_config()
    return jsonify(config_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
