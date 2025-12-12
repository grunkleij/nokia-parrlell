import socket
import threading
import pickle
import random
import struct
import time

HOST = "0.0.0.0" 
PORT = 5555
GRID_SIZE = 20
GAME_WIDTH, GAME_HEIGHT = 1000, 1000
GRID_W = GAME_WIDTH // GRID_SIZE
GRID_H = GAME_HEIGHT // GRID_SIZE

# --- NETWORK HELPERS ---
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

# --- SHARED STATE ---
game_state = {
    "players": {},
    "scores": {},
    "threads": {},
    "food": (100, 100),
    "status": "WAITING", 
    "countdown": 3,
    "timer_start": None,
    "winner": None  # NEW: Tracks who won
}

state_lock = threading.Lock()

def generate_new_food():
    x = random.randint(2, GRID_W - 2) * GRID_SIZE
    y = random.randint(2, GRID_H - 2) * GRID_SIZE
    return (x, y)

def respawn_player(pid):
    """Resets a single player to a random spot"""
    sx = random.randint(5, GRID_W-5) * GRID_SIZE
    sy = random.randint(5, GRID_H-5) * GRID_SIZE
    return [(sx, sy), (sx+GRID_SIZE, sy)]

def handle_client(conn, player_id):
    thread_name = threading.current_thread().name
    print(f"[{thread_name}] Connected Player {player_id}")

    try:
        while True:
            # 1. Input Handling
            direction = receive_data(conn)
            if direction is None: break

            with state_lock:
                game_state["threads"][player_id] = thread_name
                player_count = len(game_state["players"])

                # --- PHASE 1: WAITING ---
                if player_count < 2:
                    game_state["status"] = "WAITING"
                    game_state["timer_start"] = None
                
                # --- PHASE 2: START COUNTDOWN ---
                elif player_count >= 2 and game_state["status"] == "WAITING":
                    game_state["status"] = "COUNTDOWN"
                    game_state["timer_start"] = time.time()
                    # Reset everyone's position for fairness
                    for pid in game_state["players"]:
                        game_state["players"][pid] = respawn_player(pid)
                        game_state["scores"][pid] = 0

                # --- PHASE 3: HANDLING COUNTDOWN ---
                elif game_state["status"] == "COUNTDOWN":
                    elapsed = time.time() - game_state["timer_start"]
                    if elapsed < 1: game_state["countdown"] = 3
                    elif elapsed < 2: game_state["countdown"] = 2
                    elif elapsed < 3: game_state["countdown"] = 1
                    else: game_state["status"] = "RUNNING"

                # --- PHASE 4: GAME OVER & RESTART ---
                elif game_state["status"] == "GAME_OVER":
                    # Wait 5 seconds, then restart
                    if time.time() - game_state["timer_start"] > 5:
                        game_state["status"] = "WAITING"
                        game_state["winner"] = None
                        game_state["scores"] = {pid: 0 for pid in game_state["players"]}

                # --- PHASE 5: RUNNING LOGIC ---
                if game_state["status"] == "RUNNING" and player_id in game_state["players"]:
                    snake = game_state["players"][player_id]
                    head_x, head_y = snake[-1]
                    dx, dy = direction
                    new_head = (head_x + dx * GRID_SIZE, head_y + dy * GRID_SIZE)

                    # --- DEATH CONDITIONS ---
                    died = False
                    # 1. Wall Hit
                    if not (0 <= new_head[0] < GAME_WIDTH and 0 <= new_head[1] < GAME_HEIGHT):
                        died = True
                        print(f"[{thread_name}] Player {player_id} hit wall.")

                    # 2. Self/Enemy Collision
                    # 2. Self/Enemy Collision
                    # We use list() so we can modify the dictionary (kill enemies) while looping
                    for other_pid, other_snake in list(game_state["players"].items()):
                        if new_head in other_snake:
                            
                            # CASE A: You hit yourself (Suicide)
                            if other_pid == player_id:
                                died = True
                                print(f"[{thread_name}] Player {player_id} committed suicide.")
                            
                            # CASE B: You hit an Enemy
                            else:
                                my_score = game_state["scores"].get(player_id, 0)
                                enemy_score = game_state["scores"].get(other_pid, 0)

                                if my_score > enemy_score:
                                    # YOU WIN: You have more points.
                                    # You survive, and the enemy is removed immediately.
                                    print(f"[{thread_name}] P{player_id} ({my_score}) CRUSHED P{other_pid} ({enemy_score})!")
                                    
                                    # Kill the enemy immediately
                                    if other_pid in game_state["players"]:
                                        del game_state["players"][other_pid]
                                    if other_pid in game_state["scores"]:
                                        del game_state["scores"][other_pid]
                                    
                                    # IMPORTANT: Do not set died=True. You just walk through them.
                                else:
                                    # YOU LOSE: They have more (or equal) points.
                                    died = True
                                    print(f"[{thread_name}] Player {player_id} lost collision to Player {other_pid}.")

                    if died:
                        game_state["status"] = "GAME_OVER"
                        game_state["timer_start"] = time.time() # Start 5s timer
                        # Determine Winner (The one who didn't die)
                        # Simplified: If P1 died, P2 wins.
                        survivors = [p for p in game_state["players"] if p != player_id]
                        if survivors:
                            game_state["winner"] = survivors[0]
                        else:
                            game_state["winner"] = "Draw"
                    else:
                        # Move Logic
                        if new_head == game_state["food"]:
                            snake.append(new_head)
                            game_state["food"] = generate_new_food()
                            game_state["scores"][player_id] += 10
                        else:
                            snake.append(new_head)
                            snake.pop(0)
                        game_state["players"][player_id] = snake

            send_data(conn, game_state)
            time.sleep(0.03)

    except Exception as e:
        print(f"[{thread_name}] Error: {e}")
    finally:
        with state_lock:
            if player_id in game_state["players"]: del game_state["players"][player_id]
            if player_id in game_state["scores"]: del game_state["scores"][player_id]
            if player_id in game_state["threads"]: del game_state["threads"][player_id]
            if len(game_state["players"]) < 2:
                game_state["status"] = "WAITING"
        conn.close()
        print(f"[{thread_name}] Disconnected")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"SERVER STARTED on {HOST}:{PORT}")
    
    player_count = 0
    while True:
        conn, addr = server.accept()
        player_count += 1
        
        with state_lock:
            game_state["players"][player_count] = respawn_player(player_count)
            game_state["scores"][player_count] = 0
            game_state["threads"][player_count] = "Connecting..."
            
        threading.Thread(target=handle_client, args=(conn, player_count)).start()

if __name__ == "__main__":
    start_server()