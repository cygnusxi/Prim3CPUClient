import numpy as np
import time
import os
import math
import gmpy2  # For verification
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Create a session with retry strategy
def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def process_chunk(chunk_id, p, num_cores, shared_dict):
    """Process a chunk of the Lucas-Lehmer test using RNS principles"""
    mersenne = gmpy2.mpz(2)**p - 1
    chunk_size = (p - 1) // num_cores
    
    start = chunk_id * chunk_size + 1
    end = start + chunk_size if chunk_id < num_cores - 1 else p
    
    # Get initial value from previous chunk or 4 if first chunk
    s = gmpy2.mpz(4) if chunk_id == 0 else shared_dict.get(f'result_{chunk_id-1}', 4)
    
    # Process chunk with early exit check
    for i in range(start, end):
        s = (s * s) % mersenne
        s = (s - 2) % mersenne
        if s == 0:
            shared_dict['found_prime'] = True
            return True
            
    # Store result for next chunk
    shared_dict[f'result_{chunk_id}'] = s
    return False

def parallel_lucas_lehmer_test(p, num_cores):
    """Parallel implementation of the Lucas-Lehmer test using RNS principles"""
    if not is_prime(p):
        return False
        
    # Create a manager for shared data
    manager = Manager()
    shared_dict = manager.dict()
    shared_dict['found_prime'] = False
    
    # Create process pool
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        futures = [
            executor.submit(process_chunk, i, p, num_cores, shared_dict)
            for i in range(num_cores)
        ]
        
        # Check results
        for future in futures:
            if future.result() or shared_dict['found_prime']:
                return True
                
    # Check final result
    return shared_dict.get(f'result_{num_cores-1}', 0) == 0

def is_prime(n):
    """
    Check if a number is prime using CPU with optimized trial division.
    """
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    if n % 3 == 0:
        return n == 3
        
    # Check numbers of form 6k ± 1 up to sqrt(n)
    sqrt_n = int(n ** 0.5)
    for i in range(5, sqrt_n + 1, 6):
        if n % i == 0 or n % (i + 2) == 0:
            return False
    return True

def worker_process(core_id, server_url, user_id, shared_state):
    """Worker process function that runs independently"""
    session = create_session()
    error_count = 0
    max_errors = 5
    backoff_time = 10
    
    while shared_state['running']:
        try:
            # Fetch task
            response = session.get(
                f"{server_url}/get_mersenne_task",
                params={"user_id": user_id, "gpu_available": True},
                timeout=30
            )
            response.raise_for_status()
            task = response.json()
            
            if task:
                # Update task status before processing
                shared_state['current_tasks'][core_id] = task.copy()
                
                exponent = task["exponent"]
                task_id = task["task_id"]
                
                # Use CPU-only Lucas-Lehmer test
                is_prime = parallel_lucas_lehmer_test(exponent, shared_state['num_cores'])
                
                # Submit result
                if is_prime:
                    value = gmpy2.mpz(2)**exponent - 1
                    chunks = [str(value)[i:i+1000] for i in range(0, len(str(value)), 1000)]
                    
                    result = {
                        "task_id": task_id,
                        "exponent": exponent,
                        "is_prime": True,
                        "num_digits": value.num_digits(),
                        "value_chunks": chunks,
                        "verification_method": "CPU",
                        "discovered_by": user_id,
                        "verification_status": "VERIFIED",
                        "value_hash": str(hash(str(value)))
                    }
                else:
                    result = {
                        "task_id": task_id,
                        "exponent": exponent,
                        "is_prime": False,
                        "discovered_by": user_id,
                        "verification_status": "NOT_PRIME"
                    }
                
                response = session.post(
                    f"{server_url}/submit_mersenne_result",
                    json=result,
                    timeout=30
                )
                response.raise_for_status()
                
                # Reset error count on successful task
                error_count = 0
                
                # Update completion status
                shared_state['tasks_completed'] += 1
                shared_state['current_tasks'][core_id] = None
                
        except requests.exceptions.RequestException as e:
            error_count += 1
            logging.error(f"Network error in core {core_id}: {e}")
            if error_count >= max_errors:
                logging.error(f"Too many errors in core {core_id}, stopping worker")
                break
            time.sleep(backoff_time * error_count)  # Exponential backoff
        except Exception as e:
            error_count += 1
            logging.error(f"Error in core {core_id}: {e}")
            if error_count >= max_errors:
                logging.error(f"Too many errors in core {core_id}, stopping worker")
                break
            time.sleep(backoff_time * error_count)  # Exponential backoff

class MersenneCPUClient:
    def __init__(self, server_url, user_id, num_cores):
        self.server_url = server_url
        self.user_id = user_id
        self.num_cores = num_cores
        self.start_time = time.time()
        
        # Use multiprocessing manager for shared state
        self.manager = Manager()
        self.shared_state = self.manager.dict()
        self.shared_state['tasks_completed'] = 0
        self.shared_state['current_tasks'] = self.manager.dict({i: None for i in range(num_cores)})
        self.shared_state['running'] = True
        self.shared_state['errors'] = self.manager.dict({i: 0 for i in range(num_cores)})
        self.shared_state['last_update'] = time.time()
        self.shared_state['num_cores'] = num_cores
        
        # Create process pool with context manager
        self.process_pool = ProcessPoolExecutor(max_workers=num_cores)
        
    def display_progress(self):
        """Display progress information with enhanced statistics"""
        os.system('cls' if os.name == 'nt' else 'clear')
        print("Mersenne Prime Search (Multi-Core CPU Mode)")
        print("=========================================")
        print(f"User ID: {self.user_id}")
        print(f"CPU Cores: {self.num_cores}")
        print(f"Tasks Completed: {self.shared_state['tasks_completed']}")
        
        # Calculate processing speed and statistics
        elapsed_time = time.time() - self.start_time
        tasks_per_hour = (self.shared_state['tasks_completed'] / elapsed_time) * 3600 if elapsed_time > 0 else 0
        print(f"Processing Speed: {tasks_per_hour:.2f} tasks/hour")
        print(f"Running Time: {int(elapsed_time // 3600)}h {int((elapsed_time % 3600) // 60)}m {int(elapsed_time % 60)}s")
        
        # Display core status
        print("\nCore Status:")
        current_tasks = dict(self.shared_state['current_tasks'])
        errors = dict(self.shared_state['errors'])
        for core_id in range(self.num_cores):
            task = current_tasks.get(core_id)
            error_count = errors.get(core_id, 0)
            status = "Idle" if task is None else f"Testing M{task['exponent']}"
            print(f"Core {core_id}: {status} (Errors: {error_count})")
        
        print("\nPress Ctrl+C to stop")
                
    def run(self):
        """Main processing loop with enhanced error handling"""
        try:
            # Start a process for each core
            futures = []
            for core_id in range(self.num_cores):
                future = self.process_pool.submit(
                    worker_process,
                    core_id,
                    self.server_url,
                    self.user_id,
                    self.shared_state
                )
                futures.append(future)
            
            # Display progress while processes are running
            update_interval = 2  # seconds
            while self.shared_state['running']:
                current_time = time.time()
                if current_time - self.shared_state['last_update'] >= update_interval:
                    self.display_progress()
                    self.shared_state['last_update'] = current_time
                time.sleep(0.1)  # Reduce CPU usage
                
        except KeyboardInterrupt:
            print("\nStopping client...")
            self.shared_state['running'] = False
            self.process_pool.shutdown(wait=True)
            print(f"Completed {self.shared_state['tasks_completed']} tasks")
        except Exception as e:
            logging.error(f"Error in main process: {e}")
            self.shared_state['running'] = False
            self.process_pool.shutdown(wait=True)
        finally:
            # Ensure proper cleanup
            self.process_pool.shutdown(wait=True)

    def run_parallel_single_task(self):
        """Run in parallel single task mode where all cores work on one task"""
        try:
            session = create_session()
            error_count = 0
            max_errors = 5
            backoff_time = 10
            
            while self.shared_state['running']:
                try:
                    # Fetch single task
                    response = session.get(
                        f"{self.server_url}/get_mersenne_task",
                        params={"user_id": self.user_id, "gpu_available": True},
                        timeout=30
                    )
                    response.raise_for_status()
                    task = response.json()
                    
                    if task:
                        # Update task status
                        for core_id in range(self.num_cores):
                            self.shared_state['current_tasks'][core_id] = task.copy()
                        
                        exponent = task["exponent"]
                        task_id = task["task_id"]
                        
                        # Use parallel Lucas-Lehmer test with all cores
                        is_prime = parallel_lucas_lehmer_test(exponent, self.num_cores)
                        
                        # Submit result
                        if is_prime:
                            value = gmpy2.mpz(2)**exponent - 1
                            chunks = [str(value)[i:i+1000] for i in range(0, len(str(value)), 1000)]
                            
                            result = {
                                "task_id": task_id,
                                "exponent": exponent,
                                "is_prime": True,
                                "num_digits": value.num_digits(),
                                "value_chunks": chunks,
                                "verification_method": "CPU",
                                "discovered_by": self.user_id,
                                "verification_status": "VERIFIED",
                                "value_hash": str(hash(str(value)))
                            }
                        else:
                            result = {
                                "task_id": task_id,
                                "exponent": exponent,
                                "is_prime": False,
                                "discovered_by": self.user_id,
                                "verification_status": "NOT_PRIME"
                            }
                        
                        response = session.post(
                            f"{self.server_url}/submit_mersenne_result",
                            json=result,
                            timeout=30
                        )
                        response.raise_for_status()
                        
                        # Reset error count on successful task
                        error_count = 0
                        
                        # Update completion status
                        self.shared_state['tasks_completed'] += 1
                        for core_id in range(self.num_cores):
                            self.shared_state['current_tasks'][core_id] = None
                        
                except requests.exceptions.RequestException as e:
                    error_count += 1
                    logging.error(f"Network error: {e}")
                    if error_count >= max_errors:
                        logging.error("Too many errors, stopping client")
                        break
                    time.sleep(backoff_time * error_count)
                except Exception as e:
                    error_count += 1
                    logging.error(f"Error: {e}")
                    if error_count >= max_errors:
                        logging.error("Too many errors, stopping client")
                        break
                    time.sleep(backoff_time * error_count)
                
                # Display progress
                self.display_progress()
                
        except KeyboardInterrupt:
            print("\nStopping client...")
            self.shared_state['running'] = False
        except Exception as e:
            logging.error(f"Error in main process: {e}")
            self.shared_state['running'] = False
        finally:
            self.process_pool.shutdown(wait=True)

if __name__ == "__main__":
    print("Mersenne Prime Search")
    print("=====================")
    
    # Load configuration
    try:
        with open("client_config.json", "r") as f:
            config = json.load(f)
            username = config.get("username", "anonymous")                
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Using default values...")
        username = "anonymous"
       
    server_url = "http://workserverm1.curecoin.net:5005"
    
    # Get CPU core count
    available_cores = multiprocessing.cpu_count()
    print(f"\nAvailable CPU cores: {available_cores}")
    
    # Ask for processing mode
    while True:
        print("\nSelect processing mode:")
        print("1. Parallel Single Task (All cores work on one task)")
        print("2. Multiple Tasks (One task per core)")
        try:
            mode = input("Enter mode (1 or 2): ")
            if mode in ['1', '2']:
                break
            print("Please enter 1 or 2")
        except ValueError:
            print("Please enter a valid number")
    
    # Get core count based on mode
    if mode == '1':
        print("\nParallel Single Task Mode")
        print("All selected cores will work together on one task")
        while True:
            try:
                num_cores = input(f"Enter number of CPU cores to use (1-{available_cores}): ")
                num_cores = int(num_cores)
                if 1 <= num_cores <= available_cores:
                    break
                print(f"Please enter a number between 1 and {available_cores}")
            except ValueError:
                print("Please enter a valid number")
    else:
        print("\nMultiple Tasks Mode")
        print("Each core will process a separate task")
        while True:
            try:
                num_cores = input(f"Enter number of CPU cores to use (1-{available_cores}): ")
                num_cores = int(num_cores)
                if 1 <= num_cores <= available_cores:
                    break
                print(f"Please enter a number between 1 and {available_cores}")
            except ValueError:
                print("Please enter a valid number")
    
    # Create and run the client
    print(f"\nConnecting to server at {server_url} as {username}")
    print(f"Using {num_cores} CPU cores")
    print("Press Ctrl+C to stop")
    print("===============================")
    
    client = MersenneCPUClient(server_url, username, num_cores)
    try:
        if mode == '1':
            # Use parallel single task mode
            client.run_parallel_single_task()
        else:
            # Use multiple tasks mode
            client.run()
    except KeyboardInterrupt:
        print("\nStopping client...")
        client.shared_state['running'] = False