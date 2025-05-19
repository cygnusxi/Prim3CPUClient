from flask import Flask, render_template, request, redirect, url_for, jsonify
import logging
import os
import json
import time
from datetime import datetime
import multiprocessing
from mersenne_client_CPU import MersenneCPUClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mersenne_web.log"),
        logging.StreamHandler()
    ]
)

# Suppress Flask request logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Create Flask app
app = Flask(__name__, 
    template_folder='mersenne_templates',
    static_folder='mersenne_static'
)

# App version
VERSION = "1.0.0"

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
    'client': None
}

def load_config():
    """Load configuration from file"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                CLIENT_CONFIG.update(saved_config)
        except Exception as e:
            logging.warning(f"Could not load config: {e}")

def save_config():
    """Save configuration to file"""
    with open(CONFIG_FILE, 'w') as f:
        config_to_save = {
            'username': CLIENT_CONFIG['username'],
            'tasks_completed': CLIENT_CONFIG['tasks_completed'],
            'cores_to_use': CLIENT_CONFIG['cores_to_use']
        }
        json.dump(config_to_save, f)

@app.route('/', methods=['GET', 'POST'])
def login():
    """Login page"""
    if CLIENT_CONFIG.get('username') is not None:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        if username and len(username) >= 3 and len(username) <= 20 and username.replace('_', '').isalnum():
            CLIENT_CONFIG['username'] = username
            save_config()
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid username format')
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    """Dashboard page"""
    return render_template('dashboard.html',
                         username=CLIENT_CONFIG['username'],
                         max_cores=multiprocessing.cpu_count(),
                         cores_to_use=CLIENT_CONFIG['cores_to_use'])

@app.route('/stats')
def stats():
    """Return current stats"""
    try:
        # Get current tasks from client if it exists
        current_tasks = []
        processing_speed = 0
        running_time = "0h 0m 0s"
        
        if CLIENT_CONFIG['client'] and hasattr(CLIENT_CONFIG['client'], 'shared_state'):
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
        
        stats_data = {
            'username': CLIENT_CONFIG['username'],
            'is_running': CLIENT_CONFIG['is_running'],
            'tasks_completed': CLIENT_CONFIG['tasks_completed'],
            'current_tasks': current_tasks,
            'processing_speed': round(processing_speed, 2),
            'running_time': running_time,
            'cores_to_use': CLIENT_CONFIG['cores_to_use']
        }
        return jsonify(stats_data)
    except Exception as e:
        logging.error(f"Error in stats endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/toggle_processing', methods=['POST'])
def toggle_processing():
    """Toggle the processing state"""
    try:
        CLIENT_CONFIG['is_running'] = not CLIENT_CONFIG['is_running']
        
        if CLIENT_CONFIG['is_running']:
            # Initialize client if not exists
            if not CLIENT_CONFIG['client']:
                CLIENT_CONFIG['client'] = MersenneCPUClient(
                    server_url="http://workserverm1.curecoin.net:5005",
                    user_id=CLIENT_CONFIG['username'],
                    num_cores=CLIENT_CONFIG['cores_to_use']
                )
            
            # Start processing
            CLIENT_CONFIG['client'].run()
            logging.info("Processing started")
            return jsonify({"status": "started"})
        else:
            # Stop processing
            if CLIENT_CONFIG['client']:
                CLIENT_CONFIG['client'].shared_state['running'] = False
            logging.info("Processing stopped")
            return jsonify({"status": "stopped"})
            
    except Exception as e:
        logging.error(f"Error toggling processing: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/set_cores', methods=['POST'])
def set_cores():
    """Set the number of CPU cores to use"""
    try:
        cores = int(request.json.get('cores', 1))
        if 1 <= cores <= multiprocessing.cpu_count():
            CLIENT_CONFIG['cores_to_use'] = cores
            save_config()
            return jsonify({"status": "success", "cores": cores})
        else:
            return jsonify({"error": "Invalid core count"}), 400
    except Exception as e:
        logging.error(f"Error setting cores: {e}")
        return jsonify({"error": str(e)}), 500

def main():
    """Main function to run the web interface"""
    try:
        # Load saved configuration
        load_config()
        
        # Print startup message
        print("\n=== Mersenne Prime Search Client ===")
        print(f"Version: {VERSION}")
        print("\nAccess the web interface at:")
        print("http://127.0.0.1:5002")
        print("\nPress Ctrl+C to stop the server")
        print("================================\n")
        
        # Start the Flask app
        app.run(host='127.0.0.1', port=5002, debug=False)
        
    except Exception as e:
        logging.error(f"Error running web interface: {e}")
        raise

if __name__ == "__main__":
    main() 