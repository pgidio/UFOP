import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import time
import math
import numpy as np
import socket
import json

COR_AZUL_METAL = "#005BC5"
COR_PRETA = "#1C1C1C"
COR_PRATA = "#C0C0C0"
COR_BRANCO = "#F5F5F5"
COR_AMARELO = "#FFCC00"
COR_VERMELHO = "#D32F2F"

BG = COR_PRETA
SURFACE = "#2A2A2A"
SURF2 = "#3A3A3A"
SURF3 = "#4A4A4A"
BORDER = COR_AZUL_METAL
TEXT = COR_BRANCO
TEXT_DIM = "#A0A0A0"
ACCENT = COR_AZUL_METAL
BLUE = COR_AZUL_METAL
YELLOW = COR_AMARELO
RED = COR_VERMELHO
ORANGE = "#F97316"
PURPLE = "#C084FC"

J_COLORS = ["#005BC5", "#F97316", "#22D3EE", "#C084FC", "#F43F5E", "#34D399", "#FBBF24", "#A78BFA"]

FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SECTION = ("Segoe UI", 8, "bold")
FONT_HEAD = ("Segoe UI", 10, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)
FONT_BIG = ("Segoe UI", 13, "bold")

class ConfiguracaoManipulador:
    def __init__(self):
        self.nome = "Manipulador Genérico"
        self.n_juntas = 6
        self.juntas_controle = []
        self.dh_params_controle = []
        self.dh_params_dh = []
        self.blender_map = {}
        self.servo_limits = {}

config = ConfiguracaoManipulador()
servo_vars = []
ser = None
blender_client = None
modo_atual = "fisico"
conectado_blender = False

class BlenderClient:
    def __init__(self, host='127.0.0.1', port=65432):
        self.host = host
        self.port = port
        self.socket = None
        self.connected = False
    
    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(2)
            self.socket.connect((self.host, self.port))
            self.connected = True
            return True
        except:
            self.connected = False
            return False
    
    def send(self, command):
        if not self.connected or not self.socket:
            return None
        try:
            self.socket.sendall(json.dumps(command).encode('utf-8'))
            return json.loads(self.socket.recv(1024).decode('utf-8'))
        except:
            return None
    
    def set_angle(self, joint, value):
        return self.send({'type': 'set_angle', 'joint': joint, 'value': value})
    
    def set_angles(self, angles):
        return self.send({'type': 'set_angles', 'angles': angles})
    
    def get_angles(self):
        return self.send({'type': 'get_angles'})
    
    def ping(self):
        return self.send({'type': 'ping'})
    
    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None
            self.connected = False

def dh_transform(theta, L, d, alpha):
    theta_rad = math.radians(theta)
    alpha_rad = math.radians(alpha)
    
    ct = math.cos(theta_rad)
    st = math.sin(theta_rad)
    ca = math.cos(alpha_rad)
    sa = math.sin(alpha_rad)
    
    return np.array([
        [ct, -st*ca, st*sa, L*ct],
        [st, ct*ca, -ct*sa, L*st],
        [0, sa, ca, d],
        [0, 0, 0, 1]
    ])

def calcular_cinematica_direta(joint_angles, dh_params):
    if not dh_params:
        return 0, 0, 0, np.eye(4)
    
    T = np.eye(4)
    
    for i in range(len(dh_params)):
        theta_dh, L, d, alpha = dh_params[i]
        
        if i < len(joint_angles):
            theta = joint_angles[i]
        else:
            theta = theta_dh
        
        Ti = dh_transform(theta, L, d, alpha)
        T = T @ Ti
    
    x = T[0][3]
    y = T[1][3]
    z = T[2][3]
    
    return x, y, z, T

def atualizar_posicao_controle():
    if not config.dh_params_controle:
        pos_x_var.set("0.0")
        pos_y_var.set("0.0")
        pos_z_var.set("0.0")
        return
    
    angles = [sv.get() for sv in servo_vars[:len(config.dh_params_controle)]]
    x, y, z, _ = calcular_cinematica_direta(angles, config.dh_params_controle)
    
    pos_x_var.set(f"{x:.1f}")
    pos_y_var.set(f"{y:.1f}")
    pos_z_var.set(f"{z:.1f}")

def atualizar_posicao_dh():
    if not config.dh_params_dh:
        pos_x_dh_var.set("0.0")
        pos_y_dh_var.set("0.0")
        pos_z_dh_var.set("0.0")
        return
    
    angles = [sv.get() for sv in servo_vars[:len(config.dh_params_dh)]]
    x, y, z, _ = calcular_cinematica_direta(angles, config.dh_params_dh)
    
    pos_x_dh_var.set(f"{x:.1f}")
    pos_y_dh_var.set(f"{y:.1f}")
    pos_z_dh_var.set(f"{z:.1f}")

def on_slider_change(*args):
    atualizar_posicao_controle()
    atualizar_posicao_dh()

def angle_to_servo(angle, idx):
    if idx == 2:
        angle = -angle
    
    if idx < len(config.juntas_controle):
        servo_id = config.juntas_controle[idx][4]
        if servo_id in config.servo_limits:
            min_servo, max_servo = config.servo_limits[servo_id]
            min_angle = config.juntas_controle[idx][1]
            max_angle = config.juntas_controle[idx][2]
            if max_angle - min_angle != 0:
                v = int((angle - min_angle) / (max_angle - min_angle) * (max_servo - min_servo) + min_servo)
                return max(min_servo, min(max_servo, v))
    
    v = int((angle + 90) * 722 / 180 + 139)
    return max(139, min(861, v))

def configurar_padrao():
    config.nome = "Manipulador Genérico"
    config.n_juntas = 6
    
    config.juntas_controle = [
        ["Base", -90, 90, 0, 6],
        ["Ombro", 0, 180, 90, 5],
        ["Cotovelo", -90, 90, 0, 4],
        ["Punho Rot.", -90, 90, 0, 3],
        ["Punho Incl.", -90, 90, 0, 2],
        ["Garra", -90, 90, 0, 1]
    ]
    
    config.dh_params_controle = [
        [0, 0, 69, 90],
        [0, 95, 0, 0],
        [0, 95, 0, 0],
        [0, 169, 0, -90]
    ]
    
    config.dh_params_dh = [
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0]
    ]
    
    config.blender_map = {
        "Base": "BASE",
        "Ombro": "J1",
        "Cotovelo": "J2",
        "Punho Rot.": "J3",
        "Punho Incl.": "J4",
        "Garra": "J5"
    }
    
    config.servo_limits = {
        6: [139, 861],
        5: [139, 861],
        4: [139, 861],
        3: [139, 861],
        2: [139, 861],
        1: [139, 861]
    }
    
    recriar_interface()

def recriar_interface():
    criar_sliders()
    criar_tabela_dh_fixa()
    janela.after(100, atualizar_posicao_controle)
    janela.after(100, atualizar_posicao_dh)

def criar_sliders():
    global servo_vars
    servo_vars = []
    
    for widget in frame_sliders.winfo_children():
        widget.destroy()
    
    tk.Label(frame_sliders, text="CONTROLE DO MANIPULADOR", font=FONT_SECTION,
             bg=SURFACE, fg=TEXT_DIM).grid(
        row=0, column=0, columnspan=8, sticky="w", pady=(0, 6))
    
    for col, (lbl, anc) in enumerate([
        ("Junta", "w"), ("Mín", "e"), ("", "center"), ("Máx", "w"), ("Val", "center"), 
        ("Servo", "center")
    ]):
        tk.Label(frame_sliders, text=lbl, font=FONT_SMALL,
                 bg=SURFACE, fg=TEXT_DIM, anchor=anc, width=5 if col>0 else 16
        ).grid(row=1, column=col, padx=(0 if col else 0, 4))
    
    for i, (label, lo, hi, default, canal) in enumerate(config.juntas_controle):
        row = i + 2
        color = J_COLORS[i % len(J_COLORS)]
        
        pill = tk.Frame(frame_sliders, bg=color, width=4, height=24)
        pill.grid(row=row, column=0, sticky="w", pady=3, padx=(0, 6))
        
        if i == 2:
            label_text = f"{label} ↺"
        else:
            label_text = label
        
        tk.Label(frame_sliders, text=label_text, width=15, anchor="w",
                 font=FONT_HEAD, bg=SURFACE, fg=color
        ).grid(row=row, column=0, sticky="w", padx=(10, 0), pady=3)
        
        tk.Label(frame_sliders, text=f"{lo}°", font=FONT_SMALL,
                 bg=SURFACE, fg=TEXT_DIM, width=5, anchor="e"
        ).grid(row=row, column=1, padx=2)
        
        sv = tk.IntVar(value=default)
        servo_vars.append(sv)
        
        sl = tk.Scale(
            frame_sliders, variable=sv,
            from_=lo, to=hi, orient="horizontal",
            resolution=1, length=250, showvalue=False,
            bg=SURFACE, fg=TEXT, troughcolor=SURF2,
            activebackground=color, highlightthickness=0,
            sliderlength=20, bd=0, cursor="hand2",
            command=lambda *args: on_slider_change()
        )
        sl.grid(row=row, column=2, padx=8)
        
        tk.Label(frame_sliders, text=f"{hi}°", font=FONT_SMALL,
                 bg=SURFACE, fg=TEXT_DIM, width=5, anchor="w"
        ).grid(row=row, column=3, padx=2)
        
        val_frame = tk.Frame(frame_sliders, bg=SURF2, padx=6, pady=2)
        val_frame.grid(row=row, column=4, padx=6)
        
        tk.Label(val_frame, textvariable=sv, width=5, anchor="e",
                 font=("Consolas", 11, "bold"), bg=SURF2, fg=color
        ).pack(side="left")
        tk.Label(val_frame, text="°", font=FONT_SMALL,
                 bg=SURF2, fg=TEXT_DIM).pack(side="left")
        
        tk.Label(frame_sliders, text=f"Servo {canal}", font=FONT_SMALL,
                 bg=SURFACE, fg=TEXT_DIM, width=8, anchor="center"
        ).grid(row=row, column=5, padx=6)

def mostrar_transformacao_individual(row_idx):
    try:
        ler_valores_dh_fixos()
        
        if row_idx >= len(config.dh_params_dh):
            messagebox.showerror("Erro", "Elo não encontrado!")
            return
        
        theta_dh, L, d, alpha = config.dh_params_dh[row_idx]
        
        angles = [sv.get() for sv in servo_vars[:len(config.dh_params_dh)]]
        theta = angles[row_idx] if row_idx < len(angles) else theta_dh
        
        Ti = dh_transform(theta, L, d, alpha)
        
        janela_matriz = tk.Toplevel(janela)
        janela_matriz.title(f"Transformação Individual - Elo {row_idx+1}")
        janela_matriz.configure(bg=BG)
        janela_matriz.geometry("500x500")
        
        tk.Label(janela_matriz, text=f"Transformação do Elo {row_idx+1}", 
                 font=FONT_TITLE, bg=BG, fg=TEXT).pack(pady=10)
        
        params_frame = tk.Frame(janela_matriz, bg=SURFACE, padx=20, pady=10)
        params_frame.pack(pady=5)
        
        tk.Label(params_frame, 
                 text=f"θ = {theta:.1f}°   L = {L:.1f} mm   d = {d:.1f} mm   α = {alpha:.1f}°",
                 font=FONT_BODY, bg=SURFACE, fg=ACCENT).pack()
        
        frame_matriz = tk.Frame(janela_matriz, bg=SURFACE, padx=20, pady=20)
        frame_matriz.pack(pady=10)
        
        for i in range(4):
            for j in range(4):
                valor = f"{Ti[i][j]:.3f}"
                tk.Label(frame_matriz, text=valor, font=("Consolas", 11),
                         bg=SURFACE, fg=TEXT, width=10, anchor="center",
                         relief="solid", bd=1, padx=5, pady=5
                ).grid(row=i, column=j, padx=2, pady=2)
        
        pos_frame = tk.Frame(janela_matriz, bg=SURFACE, padx=20, pady=10)
        pos_frame.pack(pady=10)
        
        tk.Label(pos_frame, 
                 text=f"Posição local: X={Ti[0][3]:.1f}, Y={Ti[1][3]:.1f}, Z={Ti[2][3]:.1f} mm",
                 font=FONT_BODY, bg=SURFACE, fg=ACCENT).pack()
        
        tk.Button(
            janela_matriz, text="Fechar",
            command=janela_matriz.destroy,
            bg=SURF2, fg=TEXT, relief="flat",
            activebackground=SURF3, activeforeground=TEXT,
            font=FONT_BODY, cursor="hand2", bd=0,
            padx=20, pady=8
        ).pack(pady=10)
        
    except Exception as e:
        messagebox.showerror("Erro", f"Erro ao calcular transformação: {str(e)}")

def criar_tabela_dh_fixa():
    for widget in frame_dh_tabela.winfo_children():
        widget.destroy()
    
    headers = ["Elo", "θ (°)", "L (mm)", "d (mm)", "α (°)", "Transformação"]
    for col, header in enumerate(headers):
        tk.Label(frame_dh_tabela, text=header, font=FONT_HEAD,
                 bg=SURFACE, fg=ACCENT, width=12 if col < 5 else 14, anchor="center"
        ).grid(row=0, column=col, padx=4, pady=4, sticky="ew")
    
    while len(config.dh_params_dh) < 6:
        config.dh_params_dh.append([0, 0, 0, 0])
    
    for row in range(6):
        params = config.dh_params_dh[row]
        i = row + 1
        
        tk.Label(frame_dh_tabela, text=str(row+1), font=FONT_BODY,
                 bg=SURFACE, fg=TEXT).grid(row=i, column=0, padx=4, pady=2)
        
        theta_entry = tk.Entry(frame_dh_tabela, width=10,
                              bg=SURF2, fg=TEXT, font=FONT_MONO,
                              relief="flat", justify="center")
        theta_entry.insert(0, "0")
        theta_entry.grid(row=i, column=1, padx=4, pady=2)
        
        L_entry = tk.Entry(frame_dh_tabela, width=10,
                          bg=SURF2, fg=TEXT, font=FONT_MONO,
                          relief="flat", justify="center")
        L_entry.insert(0, "0")
        L_entry.grid(row=i, column=2, padx=4, pady=2)
        
        d_entry = tk.Entry(frame_dh_tabela, width=10,
                          bg=SURF2, fg=TEXT, font=FONT_MONO,
                          relief="flat", justify="center")
        d_entry.insert(0, "0")
        d_entry.grid(row=i, column=3, padx=4, pady=2)
        
        alpha_entry = tk.Entry(frame_dh_tabela, width=10,
                              bg=SURF2, fg=TEXT, font=FONT_MONO,
                              relief="flat", justify="center")
        alpha_entry.insert(0, "0")
        alpha_entry.grid(row=i, column=4, padx=4, pady=2)
        
        btn_frame = tk.Frame(frame_dh_tabela, bg=SURFACE)
        btn_frame.grid(row=i, column=5, padx=4, pady=2)
        tk.Button(
            btn_frame, text="Ver T", 
            command=lambda r=row: mostrar_transformacao_individual(r),
            bg=SURF2, fg=TEXT, relief="flat",
            activebackground=SURF3, activeforeground=TEXT,
            font=FONT_SMALL, cursor="hand2", bd=0,
            padx=8, pady=2
        ).pack()
        
        if not hasattr(config, 'dh_entries_dh'):
            config.dh_entries_dh = []
        if len(config.dh_entries_dh) <= row:
            config.dh_entries_dh.append({})
        config.dh_entries_dh[row] = {
            'theta': theta_entry,
            'L': L_entry,
            'd': d_entry,
            'alpha': alpha_entry
        }

def ler_valores_dh_fixos():
    if hasattr(config, 'dh_entries_dh'):
        for i, entry_dict in enumerate(config.dh_entries_dh):
            if i < len(config.dh_params_dh):
                try:
                    theta = float(entry_dict['theta'].get()) if entry_dict['theta'].get() else 0
                    L = float(entry_dict['L'].get()) if entry_dict['L'].get() else 0
                    d = float(entry_dict['d'].get()) if entry_dict['d'].get() else 0
                    alpha = float(entry_dict['alpha'].get()) if entry_dict['alpha'].get() else 0
                    config.dh_params_dh[i] = [theta, L, d, alpha]
                except ValueError:
                    pass

def atualizar_dh_fixo():
    ler_valores_dh_fixos()
    atualizar_posicao_dh()
    messagebox.showinfo("Sucesso", "Parâmetros DH atualizados!")

def listar_portas():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    combo_portas["values"] = ports
    if ports:
        combo_portas.current(0)
    else:
        combo_portas.set("")

def conectar():
    global ser
    porta = combo_portas.get()
    if not porta:
        messagebox.showerror("Erro", "Selecione uma porta COM.")
        return
    try:
        ser = serial.Serial(porta, 115200, timeout=1)
        time.sleep(2)
        status_var.set(f"● Conectado em {porta}")
        lbl_status.config(fg=ACCENT)
        _enviar("from Hiwonder import LSC")
    except Exception as e:
        messagebox.showerror("Erro de conexão", str(e))

def desconectar():
    global ser
    if ser:
        ser.close()
        ser = None
    status_var.set("○ Desconectado")
    lbl_status.config(fg=RED)

def _enviar(cmd):
    if ser:
        ser.write((cmd + "\r\n").encode())

def verificar_limites(x, y, z):
    if z < 0:
        return False, f"Z = {z:.1f} mm (não pode ser negativo!)"
    
    if x < 0 and -100 <= y <= 100 and 0 <= z <= 75:
        return False, f"Posição na caixa proibida!\nX = {x:.1f} mm (negativo)\nY = {y:.1f} mm\nZ = {z:.1f} mm (0 a 75)"
    
    ombro_angle = servo_vars[1].get() if len(servo_vars) > 1 else 0
    cotovelo_angle = servo_vars[2].get() if len(servo_vars) > 2 else 0
    
    if ombro_angle >= 150:
        reducao = ombro_angle - 150
        cotovelo_limite = 50 - reducao
        if cotovelo_angle > cotovelo_limite:
            return False, f"Restrição de movimento!\nOmbro = {ombro_angle}° (≥150°)\nCotovelo deve ser ≤ {cotovelo_limite:.0f}°\nCotovelo atual = {cotovelo_angle}°"
    
    return True, "Posição válida"

def mover_confirmar():
    if modo_atual == "fisico" and ser is None:
        messagebox.showerror("Sem conexão", "Conecte primeiro à controladora.")
        return
    
    if (modo_atual == "blender" or modo_atual == "ambos") and not conectado_blender:
        messagebox.showerror("Sem conexão", "Conecte-se ao Blender primeiro.")
        return
    
    atualizar_posicao_controle()
    
    x = float(pos_x_var.get())
    y = float(pos_y_var.get())
    z = float(pos_z_var.get())
    
    valido, mensagem = verificar_limites(x, y, z)
    if not valido:
        messagebox.showerror("Posição Inválida", 
                            f"❌ Posição fora dos limites de segurança!\n\n{mensagem}\n\n"
                            f"X = {x:.1f} mm\n"
                            f"Y = {y:.1f} mm\n"
                            f"Z = {z:.1f} mm")
        return
    
    angles = [sv.get() for sv in servo_vars[:len(config.juntas_controle)]]
    angles_str = ", ".join([f"{config.juntas_controle[i][0]}={angles[i]}°" for i in range(len(angles))])
    
    modo_texto = {
        "fisico": "Robô Físico",
        "blender": "Simulação Blender",
        "ambos": "Robô Físico + Blender"
    }.get(modo_atual, "Robô Físico")
    
    if messagebox.askyesno("Confirmar Movimento", 
                          f"Posição final:\n"
                          f"X: {pos_x_var.get()} mm\n"
                          f"Y: {pos_y_var.get()} mm\n"
                          f"Z: {pos_z_var.get()} mm\n\n"
                          f"Ângulos: {angles_str}\n\n"
                          f"Modo: {modo_texto}\n"
                          f"Deseja continuar?"):
        mover()

def mover():
    if modo_atual == "fisico":
        mover_fisico()
    elif modo_atual == "blender":
        mover_blender()
    else:
        mover_fisico()
        mover_blender()

def mover_fisico():
    servo_comandos = []
    for i, sv in enumerate(servo_vars):
        if i < len(config.juntas_controle):
            canal = config.juntas_controle[i][4]
            valor = angle_to_servo(sv.get(), i)
            servo_comandos.append(f"({canal},{valor})")
    
    t = tempo_var.get()
    cmd = f"LSC.moveServos(({','.join(servo_comandos)}),{t})"
    print(f"Comando enviado: {cmd}")
    _enviar(cmd)

def mover_blender():
    if not conectado_blender or not blender_client:
        return
    
    try:
        angles_blender = {}
        for i, sv in enumerate(servo_vars):
            if i < len(config.juntas_controle):
                nome = config.juntas_controle[i][0]
                if nome in config.blender_map:
                    angles_blender[config.blender_map[nome]] = sv.get()
        
        response = blender_client.set_angles(angles_blender)
        if response and response.get('status') == 'success':
            messagebox.showinfo("Sucesso", "Ângulos enviados para o Blender!")
        else:
            messagebox.showerror("Erro", "Falha ao enviar para o Blender")
    except Exception as e:
        messagebox.showerror("Erro", f"Erro: {str(e)}")

def centralizar():
    for i, sv in enumerate(servo_vars):
        if i < len(config.juntas_controle):
            sv.set(config.juntas_controle[i][3])
    atualizar_posicao_controle()
    atualizar_posicao_dh()

def alternar_modo():
    global modo_atual
    modo_selecionado = modo_var.get()
    
    if modo_selecionado == "Robô Físico":
        modo_atual = "fisico"
        btn_mover.config(text="▶  MOVER BRAÇO", bg=ACCENT)
    elif modo_selecionado == "Simulação Blender":
        modo_atual = "blender"
        btn_mover.config(text="▶  MOVER (BLENDER)", bg=BLUE)
        if not conectado_blender:
            conectar_blender()
    else:
        modo_atual = "ambos"
        btn_mover.config(text="▶  MOVER (AMBOS)", bg=PURPLE)
        if not conectado_blender:
            conectar_blender()
    
    status_modo_var.set(f"Modo: {modo_selecionado}")

def conectar_blender():
    global blender_client, conectado_blender
    try:
        if blender_client:
            blender_client.close()
        
        blender_client = BlenderClient()
        if blender_client.connect():
            conectado_blender = True
            status_blender_var.set("● Conectado ao Blender")
            lbl_status_blender.config(fg=ACCENT)
            return True
        else:
            conectado_blender = False
            status_blender_var.set("○ Blender não encontrado")
            lbl_status_blender.config(fg=RED)
            return False
    except:
        conectado_blender = False
        status_blender_var.set("○ Erro na conexão")
        lbl_status_blender.config(fg=RED)
        return False

def desconectar_blender():
    global blender_client, conectado_blender
    if blender_client:
        blender_client.close()
        blender_client = None
    conectado_blender = False
    status_blender_var.set("○ Desconectado do Blender")
    lbl_status_blender.config(fg=RED)

def card(parent, **kw):
    f = tk.Frame(parent, bg=SURFACE, **kw)
    return f

def flat_btn(parent, text, cmd, bg=SURF2, fg=TEXT, **kw):
    return tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, relief="flat",
        activebackground=SURF3, activeforeground=TEXT,
        font=FONT_BODY, cursor="hand2", bd=0,
        padx=12, pady=6, **kw
    )

janela = tk.Tk()
janela.title("Cinemática Direta · Denavit-Hartenberg")
janela.geometry("1366x768")
janela.configure(bg=BG)
janela.resizable(True, True)

main_canvas = tk.Canvas(janela, bg=BG, highlightthickness=0)
v_scroll = tk.Scrollbar(janela, orient="vertical", command=main_canvas.yview)
main_canvas.configure(yscrollcommand=v_scroll.set)

v_scroll.pack(side="right", fill="y")
main_canvas.pack(side="left", fill="both", expand=True)

scrollable_frame = tk.Frame(main_canvas, bg=BG)
canvas_window = main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

def _update_scroll_region(event=None):
    main_canvas.configure(scrollregion=main_canvas.bbox("all"))

def _resize_frame(event):
    main_canvas.itemconfig(canvas_window, width=event.width)

scrollable_frame.bind("<Configure>", _update_scroll_region)
main_canvas.bind("<Configure>", _resize_frame)

def _mousewheel(event):
    main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

main_canvas.bind_all("<MouseWheel>", _mousewheel)

style = ttk.Style(janela)
style.theme_use("clam")
style.configure("TCombobox",
    fieldbackground=SURF2, background=SURF2,
    foreground=TEXT, selectbackground=SURF3,
    selectforeground=TEXT, bordercolor=BORDER,
    arrowcolor=TEXT_DIM, relief="flat", padding=4)
style.map("TCombobox",
    fieldbackground=[("readonly", SURF2)],
    background=[("readonly", SURF2)])

style.configure("TNotebook", background=BG, borderwidth=0)
style.configure("TNotebook.Tab", 
    background=SURF2, foreground=TEXT_DIM,
    padding=[15, 8], font=FONT_HEAD)
style.map("TNotebook.Tab",
    background=[("selected", SURFACE)],
    foreground=[("selected", TEXT)])

hdr = tk.Frame(scrollable_frame, bg=SURFACE, height=58)
hdr.pack(fill="x")
hdr.pack_propagate(False)

accent_bar = tk.Frame(hdr, bg=ACCENT, height=3)
accent_bar.pack(fill="x", side="top")

tk.Label(hdr, text="🤖", font=("Segoe UI", 18), bg=SURFACE).pack(side="left", padx=(18,6))
tk.Label(hdr, text="Cinemática Direta · Denavit-Hartenberg",
         font=FONT_TITLE, bg=SURFACE, fg=TEXT).pack(side="left")

corpo = tk.Frame(scrollable_frame, bg=BG)
corpo.pack(fill="both", expand=True, padx=16, pady=14)

c_conn = card(corpo, padx=18, pady=14)
c_conn.pack(fill="x", pady=(0, 6))

tk.Label(c_conn, text="CONEXÃO", font=FONT_SECTION,
         bg=SURFACE, fg=TEXT_DIM).grid(row=0, column=0, columnspan=8,
         sticky="w", pady=(0,10))

tk.Label(c_conn, text="Porta:", font=FONT_BODY,
         bg=SURFACE, fg=TEXT_DIM).grid(row=1, column=0, sticky="w")

combo_portas = ttk.Combobox(c_conn, width=13, state="readonly")
combo_portas.grid(row=1, column=1, padx=(6, 2))

flat_btn(c_conn, "↺ Atualizar", listar_portas).grid(row=1, column=2, padx=5)
flat_btn(c_conn, "Conectar", conectar, bg=ACCENT, fg="#fff").grid(row=1, column=3, padx=5)
flat_btn(c_conn, "Desconectar", desconectar, bg=RED, fg="#fff").grid(row=1, column=4, padx=5)

status_var = tk.StringVar(value="○ Desconectado")
lbl_status = tk.Label(c_conn, textvariable=status_var,
                      font=FONT_BODY, bg=SURFACE, fg=RED)
lbl_status.grid(row=1, column=5, padx=(20, 0))

tk.Label(c_conn, text="Blender:", font=FONT_BODY,
         bg=SURFACE, fg=TEXT_DIM).grid(row=2, column=0, padx=(0,10), sticky="w")

flat_btn(c_conn, "Conectar", conectar_blender, bg=BLUE, fg="#fff").grid(row=2, column=1, padx=5)
flat_btn(c_conn, "Desconectar", desconectar_blender, bg=RED, fg="#fff").grid(row=2, column=2, padx=5)

status_blender_var = tk.StringVar(value="○ Desconectado do Blender")
lbl_status_blender = tk.Label(c_conn, textvariable=status_blender_var,
                              font=FONT_BODY, bg=SURFACE, fg=RED)
lbl_status_blender.grid(row=2, column=3, padx=(20, 0))

modo_var = tk.StringVar(value="Robô Físico")
rb_fisico = tk.Radiobutton(c_conn, text="Robô Físico", variable=modo_var, 
                          value="Robô Físico", command=alternar_modo,
                          bg=SURFACE, fg=TEXT, selectcolor=SURF2,
                          activebackground=SURFACE, activeforeground=TEXT,
                          font=FONT_BODY)
rb_fisico.grid(row=2, column=4, padx=5)

rb_blender = tk.Radiobutton(c_conn, text="Simulação Blender", variable=modo_var, 
                          value="Simulação Blender", command=alternar_modo,
                          bg=SURFACE, fg=TEXT, selectcolor=SURF2,
                          activebackground=SURFACE, activeforeground=TEXT,
                          font=FONT_BODY)
rb_blender.grid(row=2, column=5, padx=5)

rb_ambos = tk.Radiobutton(c_conn, text="Ambos", variable=modo_var, 
                         value="Ambos", command=alternar_modo,
                         bg=SURFACE, fg=TEXT, selectcolor=SURF2,
                         activebackground=SURFACE, activeforeground=TEXT,
                         font=FONT_BODY)
rb_ambos.grid(row=2, column=6, padx=5)

status_modo_var = tk.StringVar(value="Modo: Robô Físico")
tk.Label(c_conn, textvariable=status_modo_var,
         font=FONT_BODY, bg=SURFACE, fg=ACCENT).grid(row=2, column=7, padx=20)

notebook = ttk.Notebook(corpo)
notebook.pack(fill="both", expand=True, pady=8)

aba_controle = tk.Frame(notebook, bg=BG)
notebook.add(aba_controle, text="Controle")

frame_sliders = tk.Frame(aba_controle, bg=SURFACE, padx=18, pady=14)
frame_sliders.pack(fill="x", pady=6)

c_pos = card(aba_controle, padx=18, pady=14)
c_pos.pack(fill="x", pady=6)

tk.Label(c_pos, text="POSIÇÃO DO EFETUADOR", font=FONT_SECTION,
         bg=SURFACE, fg=TEXT_DIM).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0,8))

pos_x_var = tk.StringVar(value="0.0")
pos_y_var = tk.StringVar(value="0.0")
pos_z_var = tk.StringVar(value="0.0")

coords = [
    ("X", pos_x_var, BLUE),
    ("Y", pos_y_var, ACCENT),
    ("Z", pos_z_var, YELLOW)
]

for col, (label, var, color) in enumerate(coords):
    frame = tk.Frame(c_pos, bg=SURF2, padx=12, pady=8)
    frame.grid(row=1, column=col, padx=8, sticky="ew")
    
    tk.Label(frame, text=label + ":", font=FONT_HEAD,
             bg=SURF2, fg=TEXT_DIM).pack(side="left")
    tk.Label(frame, textvariable=var, font=("Consolas", 14, "bold"),
             bg=SURF2, fg=color, width=8, anchor="e").pack(side="left", padx=(8,0))
    tk.Label(frame, text="mm", font=FONT_SMALL,
             bg=SURF2, fg=TEXT_DIM).pack(side="left", padx=(4,0))

c_pos.grid_columnconfigure(0, weight=1)
c_pos.grid_columnconfigure(1, weight=1)
c_pos.grid_columnconfigure(2, weight=1)

c_tempo = card(aba_controle, padx=18, pady=14)
c_tempo.pack(fill="x", pady=6)

tk.Label(c_tempo, text="TEMPO DE MOVIMENTO", font=FONT_SECTION,
         bg=SURFACE, fg=TEXT_DIM).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0,8))

tk.Label(c_tempo, text="Duração:", font=FONT_BODY,
         bg=SURFACE, fg=TEXT_DIM).grid(row=1, column=0, sticky="w")
tk.Label(c_tempo, text="100ms", font=FONT_SMALL,
         bg=SURFACE, fg=TEXT_DIM, width=6, anchor="e").grid(row=1, column=1, padx=2)

tempo_var = tk.IntVar(value=3000)
tk.Scale(
    c_tempo, variable=tempo_var,
    from_=100, to=5000, orient="horizontal",
    resolution=100, length=350, showvalue=False,
    bg=SURFACE, fg=TEXT, troughcolor=SURF2,
    activebackground=YELLOW, highlightthickness=0,
    sliderlength=20, bd=0, cursor="hand2"
).grid(row=1, column=2, padx=8)

tk.Label(c_tempo, text="5 s", font=FONT_SMALL,
         bg=SURFACE, fg=TEXT_DIM, width=4).grid(row=1, column=3)

t_frame = tk.Frame(c_tempo, bg=SURF2, padx=6, pady=2)
t_frame.grid(row=1, column=4, padx=6)
tk.Label(t_frame, textvariable=tempo_var, width=5, anchor="e",
         font=("Consolas", 11, "bold"), bg=SURF2, fg=YELLOW).pack(side="left")
tk.Label(t_frame, text=" ms", font=FONT_SMALL, bg=SURF2, fg=TEXT_DIM).pack(side="left")

c_btns = tk.Frame(aba_controle, bg=BG)
c_btns.pack(pady=16)

flat_btn(
    c_btns, "⌖  Centralizar", centralizar,
    bg=SURF2, fg=TEXT
).pack(side="left", padx=8)

btn_mover = tk.Button(
    c_btns, text="▶  MOVER BRAÇO",
    command=mover_confirmar,
    bg=ACCENT, fg="#fff", relief="flat",
    activebackground="#0077E8", activeforeground="#fff",
    font=FONT_BIG, cursor="hand2", bd=0,
    padx=34, pady=12
)
btn_mover.pack(side="left", padx=8)

aba_dh = tk.Frame(notebook, bg=BG)
notebook.add(aba_dh, text="Parâmetros DH")

frame_dh = card(aba_dh, padx=18, pady=14)
frame_dh.pack(fill="both", expand=True, pady=6)

tk.Label(frame_dh, text="PARÂMETROS DH - 6 ELOS FIXOS", font=FONT_SECTION,
         bg=SURFACE, fg=TEXT_DIM).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0,12))

frame_dh_pos = tk.Frame(frame_dh, bg=SURFACE, padx=10, pady=8)
frame_dh_pos.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(0,10))

tk.Label(frame_dh_pos, text="POSIÇÃO DO EFETUADOR:", font=FONT_HEAD,
         bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=(0, 15))

pos_x_dh_var = tk.StringVar(value="0.0")
pos_y_dh_var = tk.StringVar(value="0.0")
pos_z_dh_var = tk.StringVar(value="0.0")

tk.Label(frame_dh_pos, text="X:", font=FONT_BODY,
         bg=SURFACE, fg=BLUE).pack(side="left")
tk.Label(frame_dh_pos, textvariable=pos_x_dh_var, font=("Consolas", 11, "bold"),
         bg=SURFACE, fg=BLUE, width=6, anchor="e").pack(side="left", padx=(2, 10))
tk.Label(frame_dh_pos, text="mm", font=FONT_SMALL,
         bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=(0, 15))

tk.Label(frame_dh_pos, text="Y:", font=FONT_BODY,
         bg=SURFACE, fg=ACCENT).pack(side="left")
tk.Label(frame_dh_pos, textvariable=pos_y_dh_var, font=("Consolas", 11, "bold"),
         bg=SURFACE, fg=ACCENT, width=6, anchor="e").pack(side="left", padx=(2, 10))
tk.Label(frame_dh_pos, text="mm", font=FONT_SMALL,
         bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=(0, 15))

tk.Label(frame_dh_pos, text="Z:", font=FONT_BODY,
         bg=SURFACE, fg=YELLOW).pack(side="left")
tk.Label(frame_dh_pos, textvariable=pos_z_dh_var, font=("Consolas", 11, "bold"),
         bg=SURFACE, fg=YELLOW, width=6, anchor="e").pack(side="left", padx=(2, 10))
tk.Label(frame_dh_pos, text="mm", font=FONT_SMALL,
         bg=SURFACE, fg=TEXT_DIM).pack(side="left")

frame_dh_tabela = tk.Frame(frame_dh, bg=SURFACE)
frame_dh_tabela.grid(row=2, column=0, columnspan=6, sticky="nsew", pady=(0,10))

frame_dh.grid_rowconfigure(2, weight=1)
frame_dh.grid_columnconfigure(0, weight=1)

c_dh_controls = tk.Frame(frame_dh, bg=SURFACE)
c_dh_controls.grid(row=3, column=0, columnspan=6, pady=10)

tk.Button(
    c_dh_controls, text="↻ Atualizar DH",
    command=atualizar_dh_fixo,
    bg=ACCENT, fg="#fff", relief="flat",
    activebackground="#0077E8", activeforeground="#fff",
    font=FONT_BODY, cursor="hand2", bd=0,
    padx=20, pady=8
).pack(side="left", padx=4)

tk.Label(c_dh_controls, text="(6 elos fixos - independente do Controle)", font=FONT_SMALL,
         bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=15)

footer = tk.Frame(scrollable_frame, bg=SURFACE, height=30)
footer.pack(fill="x", side="bottom")
footer.pack_propagate(False)

tk.Label(footer, text="Cores do Robô: Azul Metalizado • Preto Fosco • Prata • Branco • Amarelo • Vermelho",
         font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=18)

configurar_padrao()
listar_portas()

janela.after(500, atualizar_posicao_controle)
janela.after(500, atualizar_posicao_dh)

janela.mainloop()

if ser:
    ser.close()