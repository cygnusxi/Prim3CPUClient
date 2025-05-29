from flask import Flask, render_template, request, redirect, url_for, jsonify
import logging
import os
import json
import time
from datetime import datetime
import multiprocessing
import requests
import traceback
from mersenne_client_CPU import MersenneCPUClient

# Configure logging with both file and console handlers
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s')

# Create file handler for web interface specific logs
file_handler = logging.FileHandler("mersenne_web_interface.log")
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)

# Create console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler, console_handler]
)

# Create separate logger for network operations
network_logger = logging.getLogger('network')
network_handler = logging.FileHandler("mersenne_web_network.log")
network_handler.setFormatter(log_formatter)
network_logger.addHandler(network_handler)
network_logger.setLevel(logging.DEBUG)

# Suppress Flask request logging but keep errors
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Create Flask app
app = Flask(__name__, 
    template_folder='mersenne_templates',
    static_folder='mersenne_static'
)

# App version
VERSION = "1.2.1"

# Create necessary directories
os.makedirs('mersenne_templates', exist_ok=True)
os.makedirs('mersenne_static', exist_ok=True)

# Global configuration
CONFIG_FILE = "mersenne_config.json"
CLIENT_CONFIG = {
    'username': None,
    'is_running': False,
    'tasks_completed': 0,
    'current_task': None,
    'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'cores_to_use': multiprocessing.cpu_count(),
    'client': None,
    'server_url': "http://workserverm1.curecoin.net:5005",
    'connection_status': 'disconnected',
    'last_error': None,
    'error_count': 0
}

def test_server_connection():
    """Test connection to the server and log results"""
    try:
        network_logger.info(f"Testing connection to server: {CLIENT_CONFIG['server_url']}")
        response = requests.get(f"{CLIENT_CONFIG['server_url']}/public_stats", timeout=10)
        
        if response.status_code == 200:
            CLIENT_CONFIG['connection_status'] = 'connected'
            CLIENT_CONFIG['last_error'] = None
            CLIENT_CONFIG['error_count'] = 0
            network_logger.info("Server connection test successful")
            return True
        else:
            error_msg = f"Server returned status code: {response.status_code}"
            CLIENT_CONFIG['connection_status'] = 'error'
            CLIENT_CONFIG['last_error'] = error_msg
            CLIENT_CONFIG['error_count'] += 1
            network_logger.error(error_msg)
            return False
            
    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection error: {str(e)}"
        CLIENT_CONFIG['connection_status'] = 'disconnected'
        CLIENT_CONFIG['last_error'] = error_msg
        CLIENT_CONFIG['error_count'] += 1
        network_logger.error(error_msg)
        return False
    except requests.exceptions.Timeout as e:
        error_msg = f"Connection timeout: {str(e)}"
        CLIENT_CONFIG['connection_status'] = 'timeout'
        CLIENT_CONFIG['last_error'] = error_msg
        CLIENT_CONFIG['error_count'] += 1
        network_logger.error(error_msg)
        return False
    except Exception as e:
        error_msg = f"Unexpected error testing server connection: {str(e)}"
        CLIENT_CONFIG['connection_status'] = 'error'
        CLIENT_CONFIG['last_error'] = error_msg
        CLIENT_CONFIG['error_count'] += 1
        network_logger.error(error_msg)
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return False

def load_config():
    """Load configuration from file"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                CLIENT_CONFIG.update(saved_config)
                logging.info(f"Configuration loaded successfully from {CONFIG_FILE}")
        else:
            logging.info(f"No configuration file found at {CONFIG_FILE}, using defaults")
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in config file {CONFIG_FILE}: {e}")
    except Exception as e:
        logging.error(f"Error loading config from {CONFIG_FILE}: {e}")

def save_config():
    """Save configuration to file"""
    try:
        config_to_save = {
            'username': CLIENT_CONFIG['username'],
            'tasks_completed': CLIENT_CONFIG['tasks_completed'],
            'cores_to_use': CLIENT_CONFIG['cores_to_use'],
            'server_url': CLIENT_CONFIG['server_url']
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_to_save, f, indent=2)
        logging.info(f"Configuration saved successfully to {CONFIG_FILE}")
    except Exception as e:
        logging.error(f"Error saving config to {CONFIG_FILE}: {e}")

def validate_username(username):
    """Validate username format"""
    if not username:
        return False, "Username cannot be empty"
    if len(username) < 3:
        return False, "Username must be at least 3 characters long"
    if len(username) > 20:
        return False, "Username must be no more than 20 characters long"
    if not username.replace('_', '').isalnum():
        return False, "Username can only contain letters, numbers, and underscores"
    return True, "Valid username"

@app.route('/', methods=['GET', 'POST'])
def login():
    """Login page with enhanced validation and logging"""
    if CLIENT_CONFIG.get('username') is not None:
        logging.info(f"User {CLIENT_CONFIG['username']} already logged in, redirecting to dashboard")
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        logging.info(f"Login attempt with username: '{username}'")
        
        is_valid, message = validate_username(username)
        if is_valid:
            CLIENT_CONFIG['username'] = username
            save_config()
            
            # Test server connection after login
            connection_ok = test_server_connection()
            if connection_ok:
                logging.info(f"User {username} logged in successfully with server connection verified")
            else:
                logging.warning(f"User {username} logged in but server connection failed")
            
            return redirect(url_for('dashboard'))
        else:
            logging.warning(f"Invalid username format for '{username}': {message}")
            return render_template('login.html', error=message)
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    """Dashboard page with connection status"""
    if not CLIENT_CONFIG.get('username'):
        logging.warning("Unauthorized dashboard access attempt")
        return redirect(url_for('login'))
    
    # Test connection status
    test_server_connection()
    
    logging.debug(f"Dashboard accessed by user {CLIENT_CONFIG['username']}")
    return render_template('dashboard.html',
                         username=CLIENT_CONFIG['username'],
                         max_cores=multiprocessing.cpu_count(),
                         cores_to_use=CLIENT_CONFIG['cores_to_use'],
                         connection_status=CLIENT_CONFIG['connection_status'],
                         last_error=CLIENT_CONFIG['last_error'])

@app.route('/stats')
def stats():
    """Return current stats with enhanced error handling"""
    try:
        logging.debug("Stats endpoint accessed")
        
        # Get current tasks from client if it exists
        current_tasks = []
        processing_speed = 0
        running_time = "0h 0m 0s"
        
        if CLIENT_CONFIG['client'] and hasattr(CLIENT_CONFIG['client'], 'shared_state'):
            try:
                current_tasks = [
                    f"M{task['exponent']}" if task else None 
                    for task in CLIENT_CONFIG['client'].shared_state['current_tasks'].values()
                ]
                current_tasks = [task for task in current_tasks if task is not None]
                
                # Calculate processing speed and running time
                elapsed_time = time.time() - CLIENT_CONFIG['client'].start_time
                tasks_completed = CLIENT_CONFIG['client'].shared_state['tasks_completed']
                processing_speed = (tasks_completed / elapsed_time) * 3600 if elapsed_time > 0 else 0
                
                # Format running time
                hours = int(elapsed_time // 3600)
                minutes = int((elapsed_time % 3600) // 60)
                seconds = int(elapsed_time % 60)
                running_time = f"{hours}h {minutes}m {seconds}s"
                
                logging.debug(f"Client stats: {tasks_completed} tasks, {processing_speed:.2f} tasks/hour")
            except Exception as e:
                logging.error(f"Error accessing client shared state: {e}")
        
        stats_data = {
            'username': CLIENT_CONFIG['username'],
            'is_running': CLIENT_CONFIG['is_running'],
            'tasks_completed': CLIENT_CONFIG['tasks_completed'],
            'current_tasks': current_tasks,
            'processing_speed': round(processing_speed, 2),
            'running_time': running_time,
            'cores_to_use': CLIENT_CONFIG['cores_to_use'],
            'connection_status': CLIENT_CONFIG['connection_status'],
            'last_error': CLIENT_CONFIG['last_error'],
            'error_count': CLIENT_CONFIG['error_count']
        }
        
        logging.debug(f"Returning stats: {stats_data}")
        return jsonify(stats_data)
        
    except Exception as e:
        logging.error(f"Error in stats endpoint: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/toggle_processing', methods=['POST'])
def toggle_processing():
    """Toggle the processing state with enhanced error handling"""
    try:
        logging.info(f"Processing toggle requested. Current state: {CLIENT_CONFIG['is_running']}")
        
        # Test server connection before starting
        if not CLIENT_CONFIG['is_running']:
            connection_ok = test_server_connection()
            if not connection_ok:
                error_msg = f"Cannot start processing: Server connection failed. {CLIENT_CONFIG['last_error']}"
                logging.error(error_msg)
                return jsonify({"error": error_msg}), 503
        
        CLIENT_CONFIG['is_running'] = not CLIENT_CONFIG['is_running']
        
        if CLIENT_CONFIG['is_running']:
            try:
                # Initialize client if not exists
                if not CLIENT_CONFIG['client']:
                    logging.info("Initializing new MersenneCPUClient")
                    CLIENT_CONFIG['client'] = MersenneCPUClient(
                        server_url=CLIENT_CONFIG['server_url'],
                        user_id=CLIENT_CONFIG['username'],
                        num_cores=CLIENT_CONFIG['cores_to_use']
                    )
                
                # Start processing
                logging.info("Starting Mersenne processing")
                CLIENT_CONFIG['client'].run()
                logging.info("Processing started successfully")
                return jsonify({"status": "started"})
                
            except Exception as e:
                CLIENT_CONFIG['is_running'] = False
                error_msg = f"Failed to start processing: {str(e)}"
                logging.error(error_msg)
                logging.error(f"Full traceback: {traceback.format_exc()}")
                return jsonify({"error": error_msg}), 500
        else:
            try:
                # Stop processing
                if CLIENT_CONFIG['client']:
                    logging.info("Stopping Mersenne processing")
                    CLIENT_CONFIG['client'].shared_state['running'] = False
                logging.info("Processing stopped successfully")
                return jsonify({"status": "stopped"})
                
            except Exception as e:
                error_msg = f"Error stopping processing: {str(e)}"
                logging.error(error_msg)
                return jsonify({"error": error_msg}), 500
            
    except Exception as e:
        logging.error(f"Error toggling processing: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_cores', methods=['POST'])
def set_cores():
    """Set the number of CPU cores to use with validation"""
    try:
        cores = int(request.json.get('cores', 1))
        max_cores = multiprocessing.cpu_count()
        
        logging.info(f"Core count change requested: {cores} (max available: {max_cores})")
        
        if 1 <= cores <= max_cores:
            CLIENT_CONFIG['cores_to_use'] = cores
            save_config()
            logging.info(f"Core count updated to {cores}")
            return jsonify({"status": "success", "cores": cores})
        else:
            error_msg = f"Invalid core count: {cores}. Must be between 1 and {max_cores}"
            logging.warning(error_msg)
            return jsonify({"error": error_msg}), 400
            
    except ValueError as e:
        error_msg = f"Invalid core count format: {request.json.get('cores')}"
        logging.error(error_msg)
        return jsonify({"error": error_msg}), 400
    except Exception as e:
        logging.error(f"Error setting cores: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/test_connection', methods=['POST'])
def test_connection():
    """Test server connection endpoint"""
    try:
        logging.info("Manual connection test requested")
        connection_ok = test_server_connection()
        
        if connection_ok:
            return jsonify({
                "status": "success", 
                "message": "Server connection successful",
                "connection_status": CLIENT_CONFIG['connection_status']
            })
        else:
            return jsonify({
                "status": "error", 
                "message": CLIENT_CONFIG['last_error'],
                "connection_status": CLIENT_CONFIG['connection_status']
            }), 503
            
    except Exception as e:
        logging.error(f"Error in test_connection endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/logs')
def view_logs():
    """View recent log entries"""
    try:
        log_files = [
            ("Web Interface", "mersenne_web_interface.log"),
            ("Network", "mersenne_web_network.log")
        ]
        
        logs = {}
        for log_name, log_file in log_files:
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r') as f:
                        lines = f.readlines()
                        # Get last 50 lines
                        logs[log_name] = ''.join(lines[-50:])
                except Exception as e:
                    logs[log_name] = f"Error reading log file: {e}"
            else:
                logs[log_name] = "Log file not found"
        
        return jsonify(logs)
        
    except Exception as e:
        logging.error(f"Error viewing logs: {e}")
        return jsonify({"error": str(e)}), 500

def main():
    """Main function to run the web interface"""
    try:
        # Load saved configuration
        load_config()
        
        # Test initial server connection
        logging.info("Testing initial server connection...")
        test_server_connection()
        
        # Print startup message
        print("\n=== Mersenne Prime Search Client ===")
        print(f"Version: {VERSION}")
        print(f"Server: {CLIENT_CONFIG['server_url']}")
        print(f"Connection Status: {CLIENT_CONFIG['connection_status']}")
        if CLIENT_CONFIG['last_error']:
            print(f"Last Error: {CLIENT_CONFIG['last_error']}")
        print("\nAccess the web interface at:")
        print("http://127.0.0.1:5002")
        print("\nPress Ctrl+C to stop the server")
        print("================================\n")
        
        logging.info(f"Starting Flask web server on port 5002")
        logging.info(f"Server URL configured as: {CLIENT_CONFIG['server_url']}")
        logging.info(f"Initial connection status: {CLIENT_CONFIG['connection_status']}")
        
        # Start the Flask app
        app.run(host='127.0.0.1', port=5002, debug=False)
        
    except Exception as e:
        logging.error(f"Error running web interface: {e}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise

# Set the start method for multiprocessing
if __name__ == '__main__':
    multiprocessing.freeze_support()  # Add support for frozen executables
    multiprocessing.set_start_method('spawn')  # Use spawn method for Windows

if __name__ == "__main__":
    main() 