import socket
import time
import multiprocessing
import pickle
import struct
import random
import threading
import queue # Import standard queue for local exceptions
import os

HOST = "0.0.0.0" 
PORT = 5555
GRID_SIZE = 20
GAME_WIDTH, GAME_HEIGHT = 1000, 1000
GRID_W = GAME_WIDTH // GRID_SIZE
GRID_H = GAME_HEIGHT // GRID_SIZE

# --- HELPER FUNCTIONS ---
def send_data(sock, data):
    try:
        serialized = pickle.dumps(data)
        sock.sendall(struct.pack('>I', len(serialized)) + serialized)
    except: pass

def receive_data(sock):
    try:
        header = sock.recv(4)
        if not header: return None
        msg_len = struct.unpack('>I', header)[0]
        data = b""
        while len(data) < msg_len:
            packet = sock.recv(msg_len - len(data))
            if not packet: return None
            data += packet
        return pickle.loads(data)
    except: return None

def respawn_player(pid):
    sx = random.randint(5, GRID_W-5) * GRID_SIZE
    sy = random.randint(5, GRID_H-5) * GRID_SIZE
    return [(sx, sy), (sx+GRID_SIZE, sy)]

def generate_new_food():
    x = random.randint(2, GRID_W - 2) * GRID_SIZE
    y = random.randint(2, GRID_H - 2) * GRID_SIZE
    return (x, y)

# --- PROCESS 3: AI BOT (Real Parallelism) ---
def ai_player_process(shared_return_dict, input_queue):
    print("[AI] Bot Process Started")
    pid = os.getpid()
    shared_return_dict['compute_pid'] = pid
    
    # AI ID
    AI_PID = 99
    is_playing = False
    
    while True:
        try:
            state = shared_return_dict.get('game_state')
            if not state:
                time.sleep(0.1)
                continue
            
            # Check Game Mode
            mode = state.get("game_mode", "PVP")
            
            if mode == "PVP":
                if is_playing:
                    # Leave the game
                    input_queue.put((AI_PID, "DISCONNECT"))
                    is_playing = False
                    print("[AI] Mode is PVP. Bot sleeping.")
                time.sleep(1)
                continue
            
            # Mode is PVAI
            if not is_playing:
                # Join the game
                input_queue.put((AI_PID, "NEW_PLAYER"))
                is_playing = True
                print("[AI] Mode is PVAI. Bot joining.")
                time.sleep(1) # Wait for join
                continue

            if state.get("status") != "RUNNING":
                time.sleep(0.1)
                continue
            
            # Get my snake and food
            my_snake = state["players"].get(AI_PID)
            food = state["food"]
            
            if not my_snake:
                # Try to respawn if dead
                input_queue.put((AI_PID, "NEW_PLAYER"))
                time.sleep(1)
                continue

            head = my_snake[-1]
            
            # BFS Pathfinding
            queue_bfs = [(head, [])]
            visited = set()
            visited.add(head)
            
            # Obstacles (Walls + Other Snakes)
            obstacles = set()
            for p, s in state["players"].items():
                for segment in s:
                    obstacles.add(segment)
            
            # Remove own tail from obstacles (it will move)
            if my_snake[0] in obstacles:
                obstacles.remove(my_snake[0])

            best_move = None
            nodes_searched = 0
            
            while queue_bfs:
                current, path = queue_bfs.pop(0)
                nodes_searched += 1
                
                if current == food:
                    if path: best_move = path[0]
                    break
                
                cx, cy = current
                # Check 4 directions
                for dx, dy, move in [(0, -1, (0,-1)), (0, 1, (0,1)), (-1, 0, (-1,0)), (1, 0, (1,0))]:
                    nx, ny = cx + dx * GRID_SIZE, cy + dy * GRID_SIZE
                    neighbor = (nx, ny)
                    
                    # Bounds Check
                    if not (0 <= nx < GAME_WIDTH and 0 <= ny < GAME_HEIGHT):
                        continue
                        
                    # Obstacle Check
                    if neighbor in obstacles:
                        continue
                        
                    if neighbor not in visited:
                        visited.add(neighbor)
                        new_path = list(path)
                        new_path.append(move)
                        queue_bfs.append((neighbor, new_path))
            
            # Update Stats
            shared_return_dict['compute_count'] = nodes_searched
            
            if best_move:
                input_queue.put((AI_PID, best_move))
            else:
                # Fallback: Random valid move if no path found
                pass
                
            # AI thinks at 10Hz (same as game tick)
            time.sleep(0.1)
            
        except Exception as e:
            print(f"[AI] Error: {e}")
            time.sleep(1)

# --- PROCESS 2: PHYSICS ENGINE (True Parallelism) ---
def game_engine_process(shared_return_dict, input_queue):
    print("[ENGINE] Physics Process Started")
    engine_pid = os.getpid()
    
    local_state = {
        "players": {},
        "scores": {},
        "food": (100, 100),
        "status": "WAITING",
        "game_mode": "PVP",
        "countdown": 3,
        "timer_start": None,
        "winner": None,
        "game_over_time": None,
        "debug_info": {"engine_pid": engine_pid}
    }
    
    player_inputs = {}

    while True:
        # Update Debug Info
        local_state["debug_info"]["server_pid"] = shared_return_dict.get('server_pid', 'Unknown')
        local_state["debug_info"]["compute_pid"] = shared_return_dict.get('compute_pid', 'Unknown')
        local_state["debug_info"]["compute_cycles"] = shared_return_dict.get('compute_count', 0)

        # 1. READ ALL INPUTS
        while not input_queue.empty():
            try:
                pid, direction = input_queue.get_nowait()
                
                if isinstance(direction, str) and direction.startswith("MODE:"):
                    local_state["game_mode"] = direction.split(":")[1]
                    continue

                if direction == "NEW_PLAYER":
                    local_state["players"][pid] = respawn_player(pid)
                    local_state["scores"][pid] = 0
                    player_inputs[pid] = (0,0)
                elif direction == "DISCONNECT":
                    if pid in local_state["players"]: del local_state["players"][pid]
                else:
                    player_inputs[pid] = direction
            except: pass

        # 2. GAME LOGIC
        if len(local_state["players"]) < 2:
            local_state["status"] = "WAITING"
            local_state["timer_start"] = None
            
        elif local_state["status"] == "WAITING" and len(local_state["players"]) >= 2:
            local_state["status"] = "COUNTDOWN"
            local_state["timer_start"] = time.time()
            
            # --- FIX 1: CLEAR INPUTS ON START ---
            for pid in local_state["players"]:
                local_state["players"][pid] = respawn_player(pid)
                local_state["scores"][pid] = 0
                player_inputs[pid] = (0,0) # Force stop moving

        elif local_state["status"] == "COUNTDOWN":
            elapsed = time.time() - local_state["timer_start"]
            if elapsed < 3: local_state["countdown"] = 3 - int(elapsed)
            else: local_state["status"] = "RUNNING"

        elif local_state["status"] == "RUNNING":
            collision_detected = False
            round_winner = None
            
            next_positions = {}
            for pid, snake in local_state["players"].items():
                head_x, head_y = snake[-1]
                dx, dy = player_inputs.get(pid, (0,0))
                
                # --- FIX 2: NECK CHECK (Prevent 180 Turns) ---
                if len(snake) > 1:
                    neck_x, neck_y = snake[-2]
                    # If input tries to go backwards into neck, ignore it
                    if (head_x + dx * GRID_SIZE, head_y + dy * GRID_SIZE) == (neck_x, neck_y):
                        dx, dy = 0, 0 # Stop instead of crashing
                
                if dx == 0 and dy == 0: 
                    next_positions[pid] = snake[-1]
                    continue
                
                new_head = (head_x + dx * GRID_SIZE, head_y + dy * GRID_SIZE)
                next_positions[pid] = new_head

            # Check Collisions
            for pid, new_head in next_positions.items():
                # Wall
                if not (0 <= new_head[0] < GAME_WIDTH and 0 <= new_head[1] < GAME_HEIGHT):
                    collision_detected = True
                    round_winner = "Draw"
                    break
                
                # Body
                for other_pid, other_snake in local_state["players"].items():
                    body_to_check = other_snake[:-1] if other_pid == pid else other_snake
                    if new_head in body_to_check:
                        collision_detected = True
                        round_winner = other_pid if other_pid != pid else "Draw"
                        break
                if collision_detected: break
            
            if collision_detected:
                local_state["status"] = "GAME_OVER"
                local_state["winner"] = round_winner if round_winner else "Draw"
                local_state["game_over_time"] = time.time()
            else:
                # Apply Moves
                for pid, snake in local_state["players"].items():
                    if pid not in next_positions: continue
                    new_head = next_positions[pid]
                    if new_head == snake[-1]: continue 

                    snake.append(new_head)
                    if new_head == local_state["food"]:
                        local_state["food"] = generate_new_food()
                        local_state["scores"][pid] += 10
                    else:
                        snake.pop(0)
                    local_state["players"][pid] = snake

        elif local_state["status"] == "GAME_OVER":
            if time.time() - local_state["game_over_time"] > 3:
                # Restart Game
                local_state["status"] = "COUNTDOWN"
                local_state["timer_start"] = time.time()
                local_state["winner"] = None
                
                # --- FIX 3: CLEAR INPUTS ON RESTART ---
                for pid in local_state["players"]:
                    local_state["players"][pid] = respawn_player(pid)
                    # local_state["scores"][pid] = 0 # Optional: reset scores
                    player_inputs[pid] = (0,0) # CRITICAL: Reset inputs to stationary

        shared_return_dict['game_state'] = local_state
        time.sleep(0.1)

# --- THREAD: INPUT LISTENER ---
# Continually listens for keys from ONE client
def client_input_thread(conn, pid, input_queue):
    try:
        while True:
            direction = receive_data(conn)
            if direction is None: break
            input_queue.put((pid, direction))
    except: pass
    finally:
        input_queue.put((pid, "DISCONNECT"))
        print(f"[NET] Player {pid} Input Stopped")

# --- THREAD: STATE SENDER ---
# Continually sends the map to ONE client (Fixes the lag!)
def client_output_thread(conn, shared_return_dict):
    try:
        while True:
            # Grab the latest state from the Engine Process
            state = shared_return_dict.get('game_state')
            if state:
                send_data(conn, state)
            time.sleep(0.05) # Send updates 20 times/sec
    except: pass

def start_server():
    # Setup Multiprocessing
    manager = multiprocessing.Manager()
    shared_return_dict = manager.dict()
    shared_return_dict['game_state'] = {}
    shared_return_dict['server_pid'] = os.getpid()
    shared_return_dict['compute_count'] = 0
    
    input_queue = multiprocessing.Queue()

    # Start Physics Engine Process
    p_engine = multiprocessing.Process(target=game_engine_process, args=(shared_return_dict, input_queue))
    p_engine.daemon = True
    p_engine.start()

    # Start AI Bot Process (Replaces Heavy Compute)
    p_ai = multiprocessing.Process(target=ai_player_process, args=(shared_return_dict, input_queue))
    p_ai.daemon = True
    p_ai.start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[MAIN] Server Listening on {HOST}:{PORT}")
    print(f"[MAIN] Server PID: {os.getpid()}")

    player_count = 0
    
    while True:
        conn, addr = server.accept()
        player_count += 1
        print(f"[NET] Player {player_count} Connected")
        
        # Notify Engine
        input_queue.put((player_count, "NEW_PLAYER"))
        
        # 1. Start Input Thread (Reads keys)
        threading.Thread(target=client_input_thread, args=(conn, player_count, input_queue), daemon=True).start()
        
        # 2. Start Output Thread (Sends map)
        threading.Thread(target=client_output_thread, args=(conn, shared_return_dict), daemon=True).start()

if __name__ == "__main__":
    start_server()