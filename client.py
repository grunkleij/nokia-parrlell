import pygame
import socket
import pickle
import struct
import os

# --- CONNECTIVITY ---
# CHANGE THIS: Use "127.0.0.1" for local testing
# Use your "what-locked..." address for Playit.gg
HOST = "jezby-2001-df5-d380-473f-9a37-611e-95c3-eb40.a.free.pinggy.link" 
PORT = 36017

# --- VISUAL CONFIGURATION ---
TARGET_PHONE_HEIGHT = 900  
DEBUG_MODE = False          # Set to False to hide the red box

# --- SCREEN ALIGNMENT ---
VIRTUAL_SCREEN_W = 850     
VIRTUAL_SCREEN_H = 700     
SCREEN_OFFSET_Y  = 105   

# --- NOKIA COLORS ---
NOKIA_GREEN = (155, 188, 15)
NOKIA_DARK  = (15, 56, 15)

# --- DASHBOARD COLORS ---
BLACK = (20, 20, 20)
DARK_GRAY = (40, 40, 40)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
BLUE = (50, 150, 255)
RED = (255, 50, 50)
YELLOW = (255, 255, 0)

# --- GAME CONSTANTS ---
LOGICAL_WIDTH = 1000
LOGICAL_HEIGHT = 1000
GRID_SIZE = 20

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

def draw_nokia_game(surface, game_state, font_main, font_huge):
    """Draws the game logic onto the virtual Nokia screen surface"""
    surface.fill(NOKIA_GREEN)
    
    status = game_state.get("status", "WAITING")

    # Draw Food
    if status in ["RUNNING", "COUNTDOWN"]:
        fx, fy = game_state["food"]
        # Food is a small solid block + outline
        pygame.draw.rect(surface, NOKIA_DARK, (fx + 4, fy + 4, GRID_SIZE - 8, GRID_SIZE - 8))
        pygame.draw.rect(surface, NOKIA_DARK, (fx, fy, GRID_SIZE, GRID_SIZE), 1)

    # Draw Snakes
    if status in ["RUNNING", "COUNTDOWN", "GAME_OVER"]:
        for pid, snake in game_state["players"].items():
            
            # --- VISUAL DISTINCTION LOGIC ---
            # Player 1 (Odd IDs) = Solid Snake
            # Player 2 (Even IDs) = Hollow Snake
            is_solid = (pid % 2 != 0) 

            for i, segment in enumerate(snake):
                rect = (segment[0], segment[1], GRID_SIZE, GRID_SIZE)
                
                if is_solid:
                    # DRAW SOLID SNAKE (P1)
                    pygame.draw.rect(surface, NOKIA_DARK, rect)
                    # Tiny light gap between segments to see movement
                    pygame.draw.rect(surface, NOKIA_GREEN, rect, 1)
                else:
                    # DRAW HOLLOW SNAKE (P2)
                    # Thick outline
                    pygame.draw.rect(surface, NOKIA_DARK, rect, 3)
                    # If it's the head, put a dot in the middle
                    if i == len(snake) - 1:
                        pygame.draw.rect(surface, NOKIA_DARK, (segment[0]+6, segment[1]+6, 8, 8))

    # UI Text Logic
    if status == "WAITING":
        txt1 = font_main.render("WAITING FOR", True, NOKIA_DARK)
        txt2 = font_main.render("PLAYER 2...", True, NOKIA_DARK)
        surface.blit(txt1, (LOGICAL_WIDTH//2 - txt1.get_width()//2, LOGICAL_HEIGHT//2 - 60))
        surface.blit(txt2, (LOGICAL_WIDTH//2 - txt2.get_width()//2, LOGICAL_HEIGHT//2 + 10))
        
        if game_state["players"]:
            try:
                my_id = list(game_state["players"].keys())[-1]
                sub = font_main.render(f"YOU: P{my_id}", True, NOKIA_DARK)
                surface.blit(sub, (LOGICAL_WIDTH//2 - sub.get_width()//2, LOGICAL_HEIGHT//2 + 80))
            except: pass
    
    elif status == "COUNTDOWN":
        count_val = str(game_state.get("countdown", 3))
        txt = font_huge.render(count_val, True, NOKIA_DARK)
        rect = txt.get_rect(center=(LOGICAL_WIDTH//2, LOGICAL_HEIGHT//2))
        surface.blit(txt, rect)

    elif status == "GAME_OVER":
        winner = game_state.get("winner", "Unknown")
        
        if winner == "Draw":
            msg = "DRAW GAME"
        else:
            msg = f"WINNER: P{winner}"
            
        txt = font_main.render(msg, True, NOKIA_DARK)
        surface.blit(txt, (LOGICAL_WIDTH//2 - txt.get_width()//2, LOGICAL_HEIGHT//2))

def draw_dashboard(screen, x_offset, height, game_state, font_title, font_body):
    """Draws the detailed System Monitor"""
    MENU_WIDTH = 300
    menu_rect = pygame.Rect(x_offset, 0, MENU_WIDTH, height)
    pygame.draw.rect(screen, DARK_GRAY, menu_rect)
    pygame.draw.line(screen, WHITE, (x_offset, 0), (x_offset, height), 2)

    # Title
    title = font_title.render("SYSTEM MONITOR", True, YELLOW)
    screen.blit(title, (x_offset + 15, 20))

    y_pos = 60
    # Status
    status_text = f"Status: {game_state.get('status', 'Unknown')}"
    screen.blit(font_body.render(status_text, True, WHITE), (x_offset + 15, y_pos))
    y_pos += 40

    # Process Info Header
    screen.blit(font_body.render("Active Processes (PIDs):", True, WHITE), (x_offset + 15, y_pos))
    y_pos += 25

    debug_info = game_state.get("debug_info", {})
    
    # Server PID
    s_pid = debug_info.get("server_pid", "???")
    screen.blit(font_body.render(f"Network: {s_pid}", True, BLUE), (x_offset + 15, y_pos))
    y_pos += 20

    # Engine PID
    e_pid = debug_info.get("engine_pid", "???")
    screen.blit(font_body.render(f"Physics: {e_pid}", True, GREEN), (x_offset + 15, y_pos))
    y_pos += 20

    # AI Bot PID
    c_pid = debug_info.get("compute_pid", "???")
    screen.blit(font_body.render(f"AI Bot: {c_pid}", True, RED), (x_offset + 15, y_pos))
    y_pos += 30

    # AI Stats
    screen.blit(font_body.render("AI Nodes Searched:", True, WHITE), (x_offset + 15, y_pos))
    y_pos += 20
    cycles = debug_info.get("compute_cycles", 0)
    screen.blit(font_body.render(f"{cycles:,}", True, YELLOW), (x_offset + 15, y_pos))
    y_pos += 40

    # Player Scores
    screen.blit(font_body.render("Player Scores:", True, WHITE), (x_offset + 15, y_pos))
    y_pos += 25

    for pid, score in game_state.get("scores", {}).items():
        color = GREEN if pid % 2 != 0 else BLUE
        p_text = font_body.render(f"P{pid}: {score}", True, color)
        screen.blit(p_text, (x_offset + 15, y_pos))
        y_pos += 20

def draw_menu(screen, font_title, font_body):
    """Draws the startup menu and returns the selected mode"""
    screen.fill(NOKIA_GREEN)
    
    # Title
    title = font_title.render("SNAKE PARALLEL", True, NOKIA_DARK)
    screen.blit(title, (TOTAL_WIDTH//2 - title.get_width()//2, 200))
    
    # Options
    opt1 = font_body.render("1. Play vs Player (PVP)", True, NOKIA_DARK)
    opt2 = font_body.render("2. Play vs AI Bot (PVAI)", True, NOKIA_DARK)
    
    screen.blit(opt1, (TOTAL_WIDTH//2 - opt1.get_width()//2, 350))
    screen.blit(opt2, (TOTAL_WIDTH//2 - opt2.get_width()//2, 400))
    
    pygame.display.flip()
    
    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: return "PVP"
                if event.key == pygame.K_2: return "PVAI"
        pygame.time.wait(50)

def main():
    pygame.init()
    
    # 1. LOAD IMAGE
    img_path = "nokiainterface.jpg"
    if not os.path.exists(img_path):
        img_path = "nokiainterface.png" 

    try:
        raw_img = pygame.image.load(img_path)
        raw_w, raw_h = raw_img.get_size()
        scale_factor = TARGET_PHONE_HEIGHT / raw_h
        new_w, new_h = int(raw_w * scale_factor), int(raw_h * scale_factor)
        phone_img = pygame.transform.smoothscale(raw_img, (new_w, new_h))
    except:
        new_w, new_h = 500, 900
        phone_img = pygame.Surface((new_w, new_h))
        phone_img.fill((50,50,50))

def main():
    pygame.init()
    
    # 1. LOAD IMAGE
    img_path = "nokiainterface.jpg"
    if not os.path.exists(img_path):
        img_path = "nokiainterface.png" 

    try:
        raw_img = pygame.image.load(img_path)
        raw_w, raw_h = raw_img.get_size()
        scale_factor = TARGET_PHONE_HEIGHT / raw_h
        new_w, new_h = int(raw_w * scale_factor), int(raw_h * scale_factor)
        phone_img = pygame.transform.smoothscale(raw_img, (new_w, new_h))
    except:
        new_w, new_h = 500, 900
        phone_img = pygame.Surface((new_w, new_h))
        phone_img.fill((50,50,50))
    
    screen_x = (new_w - VIRTUAL_SCREEN_W) // 2
    screen_y = SCREEN_OFFSET_Y
    
    # Total Window
    DASHBOARD_WIDTH = 300
    global TOTAL_WIDTH # Make global for menu
    TOTAL_WIDTH = new_w + DASHBOARD_WIDTH
    TOTAL_HEIGHT = new_h

    screen = pygame.display.set_mode((TOTAL_WIDTH, TOTAL_HEIGHT))
    pygame.display.set_caption("Parallel Snake - Nokia Edition")
    
    virtual_lcd = pygame.surface.Surface((LOGICAL_WIDTH, LOGICAL_HEIGHT))

    # Fonts
    font_nokia_main = pygame.font.SysFont("Consolas", 60, bold=True)
    font_nokia_huge = pygame.font.SysFont("Consolas", 120, bold=True)
    font_dash_title = pygame.font.SysFont("Consolas", 22, bold=True)
    font_dash_body = pygame.font.SysFont("Consolas", 16)

    # Networking
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((HOST, PORT))
    except:
        print("Server not found. Running in visual mode.")
        client_socket = None

    # --- SHOW MENU ---
    selected_mode = draw_menu(screen, font_nokia_main, font_nokia_main)
    if not selected_mode: return # User closed window
    
    if client_socket:
        send_data(client_socket, f"MODE:{selected_mode}")

    clock = pygame.time.Clock()
    current_direction = (1, 0) # Default starting direction
    running = True
    
    game_state = {"status": "WAITING", "threads": {}, "players": {}, "food": (100,100), "scores": {}}

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: running = False
            if event.type == pygame.KEYDOWN:
                # Update direction locally so we keep sending the correct intent
                if event.key == pygame.K_UP and current_direction != (0, 1): current_direction = (0, -1)
                elif event.key == pygame.K_DOWN and current_direction != (0, -1): current_direction = (0, 1)
                elif event.key == pygame.K_LEFT and current_direction != (1, 0): current_direction = (-1, 0)
                elif event.key == pygame.K_RIGHT and current_direction != (-1, 0): current_direction = (1, 0)

        # Network update
        if client_socket:
            send_data(client_socket, current_direction)
            new_state = receive_data(client_socket)
            if new_state: game_state = new_state

        # --- DRAWING ---
        screen.fill(BLACK) 
        screen.blit(phone_img, (0, 0))

        draw_nokia_game(virtual_lcd, game_state, font_nokia_main, font_nokia_huge)
        
        scaled_game = pygame.transform.scale(virtual_lcd, (VIRTUAL_SCREEN_W, VIRTUAL_SCREEN_H))
        screen.blit(scaled_game, (screen_x, screen_y))

        if DEBUG_MODE:
            pygame.draw.rect(screen, RED, (screen_x, screen_y, VIRTUAL_SCREEN_W, VIRTUAL_SCREEN_H), 2)

        draw_dashboard(screen, new_w, TOTAL_HEIGHT, game_state, font_dash_title, font_dash_body)

        pygame.display.flip()
        clock.tick(30)

    if client_socket: client_socket.close()

if __name__ == "__main__":
    main()