"""
Cinemática Direta · Denavit-Hartenberg — Painel de Controle do Manipulador
============================================================================
Versão aprimorada do painel original. Principais melhorias em relação à
versão anterior:

  ARQUITETURA / QUALIDADE DE CÓDIGO
  - Estado global (variáveis soltas no módulo) substituído por uma classe
    `RobotArmApp`, o que evita colisões de nome e facilita manutenção/testes.
  - `except:` genéricos substituídos por exceções específicas
    (serial.SerialException, OSError, socket.timeout, json.JSONDecodeError,
    ValueError), sempre registradas no log em vez de falhar silenciosamente.
  - Comunicação serial e com o Blender agora rodam em threads separadas
    (com fila thread-safe `queue.Queue`), então a interface NUNCA congela
    durante `time.sleep(2)` de conexão ou timeouts de socket.
  - Lista de juntas com sinal invertido (antes só o índice 2 "Cotovelo"
    estava fixo no código) virou `config.juntas_invertidas`, configurável.
  - Validação de campos da tabela DH agora sinaliza visualmente (borda
    vermelha) o campo inválido em vez de engolir o erro com `pass`.
  - Configuração do robô pode ser salva/carregada em JSON (extensível para
    outros manipuladores, não só o "Manipulador Genérico" fixo).

  INTERFACE / EXPERIÊNCIA
  - Cabeçalho com gradiente animado e indicador de conexão pulsante.
  - Visualizador 2D AO VIVO do braço (vista lateral + vista de topo),
    desenhado a partir da cinemática direta real, atualizado a cada
    movimento de slider — ótimo para conferir a pose antes de mover o
    robô de verdade.
  - Zona proibida de segurança agora é desenhada visualmente na vista
    de topo, não só bloqueada por mensagem de erro.
  - Aba "Poses Salvas": salvar, carregar, excluir, exportar/importar
    (JSON) e reproduzir sequências de poses com animação suave.
  - Aba "Log": console com histórico de comandos enviados e eventos,
    com timestamp e níveis (info/aviso/erro).
  - Tooltips explicativos nos principais controles.
  - Barra de menu (Arquivo) e barra de status com relógio.
  - Movimento animado: os sliders interpolam suavemente até a pose alvo
    durante o tempo configurado, dando feedback visual do movimento.

Cores do robô mantidas: Azul Metalizado, Preto Fosco, Prata, Branco,
Amarelo, Vermelho.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
import serial
import serial.tools.list_ports
import threading
import queue
import time
import math
import numpy as np
import socket
import json
import os
from datetime import datetime

# ==========================================================================
# PALETA / TIPOGRAFIA
# ==========================================================================
COR_AZUL_METAL = "#005BC5"
COR_PRETA = "#1C1C1C"
COR_PRATA = "#C0C0C0"
COR_BRANCO = "#F5F5F5"
COR_AMARELO = "#FFCC00"
COR_VERMELHO = "#D32F2F"

BG = COR_PRETA
SURFACE = "#232323"
SURF2 = "#2E2E2E"
SURF3 = "#3C3C3C"
SURF4 = "#4A4A4A"
BORDER = COR_AZUL_METAL
TEXT = COR_BRANCO
TEXT_DIM = "#9A9A9A"
ACCENT = COR_AZUL_METAL
ACCENT_HOVER = "#1E76E0"
BLUE = COR_AZUL_METAL
YELLOW = COR_AMARELO
RED = COR_VERMELHO
GREEN = "#2ECC71"
ORANGE = "#F97316"
PURPLE = "#C084FC"
CYAN = "#22D3EE"

J_COLORS = ["#2E8BFF", "#F97316", "#22D3EE", "#C084FC", "#F43F5E", "#34D399", "#FBBF24", "#A78BFA"]

FONT_TITLE = ("Segoe UI", 17, "bold")
FONT_SUBTITLE = ("Segoe UI", 9)
FONT_SECTION = ("Segoe UI", 8, "bold")
FONT_HEAD = ("Segoe UI", 10, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TINY = ("Segoe UI", 8)
FONT_MONO = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 9)
FONT_BIG = ("Segoe UI", 13, "bold")

CONFIG_PATH_PADRAO = os.path.join(os.path.expanduser("~"), ".robo_dh_config.json")
POSES_PATH_PADRAO = os.path.join(os.path.expanduser("~"), ".robo_dh_poses.json")


# ==========================================================================
# UTILITÁRIOS DE UI
# ==========================================================================
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def interpolar_cor(cor_a, cor_b, t):
    a = hex_to_rgb(cor_a)
    b = hex_to_rgb(cor_b)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


class Tooltip:
    """Tooltip simples exibido ao passar o mouse sobre um widget."""

    def __init__(self, widget, texto):
        self.widget = widget
        self.texto = texto
        self.tip = None
        widget.bind("<Enter>", self._mostrar)
        widget.bind("<Leave>", self._esconder)

    def _mostrar(self, _event=None):
        if self.tip or not self.texto:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        try:
            self.tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.tip, text=self.texto, bg="#101010", fg=COR_BRANCO,
            font=FONT_TINY, padx=8, pady=4, relief="solid", bd=1,
            justify="left", wraplength=260
        ).pack()

    def _esconder(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def card(parent, **kw):
    kw.setdefault("bg", SURFACE)
    kw.setdefault("highlightbackground", SURF3)
    kw.setdefault("highlightthickness", 1)
    return tk.Frame(parent, **kw)


def flat_btn(parent, text, cmd, bg=SURF2, fg=TEXT, hover=None, tooltip=None, **kw):
    b = tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, relief="flat",
        activebackground=hover or SURF4, activeforeground=fg,
        font=kw.pop("font", FONT_BODY), cursor="hand2", bd=0,
        padx=kw.pop("padx", 12), pady=kw.pop("pady", 6), **kw
    )
    if tooltip:
        Tooltip(b, tooltip)
    return b


# ==========================================================================
# MODELO DE DADOS DO MANIPULADOR
# ==========================================================================
class ConfiguracaoManipulador:
    def __init__(self):
        self.nome = "Manipulador Genérico"
        self.n_juntas = 6
        self.juntas_controle = []       # [nome, min, max, default, canal_servo]
        self.dh_params_controle = []    # [theta, L, d, alpha] usados p/ calcular posição real
        self.dh_params_dh = []          # tabela DH livre/editável (independente)
        self.blender_map = {}
        self.servo_limits = {}
        self.juntas_invertidas = [2]    # índices de junta cujo sinal deve ser invertido
        self.dh_entries_dh = []         # widgets Entry da tabela DH (preenchido pela UI)

    def to_dict(self):
        return {
            "nome": self.nome,
            "n_juntas": self.n_juntas,
            "juntas_controle": self.juntas_controle,
            "dh_params_controle": self.dh_params_controle,
            "dh_params_dh": self.dh_params_dh,
            "blender_map": self.blender_map,
            "servo_limits": {str(k): v for k, v in self.servo_limits.items()},
            "juntas_invertidas": self.juntas_invertidas,
        }

    def from_dict(self, d):
        self.nome = d.get("nome", self.nome)
        self.n_juntas = d.get("n_juntas", self.n_juntas)
        self.juntas_controle = d.get("juntas_controle", self.juntas_controle)
        self.dh_params_controle = d.get("dh_params_controle", self.dh_params_controle)
        self.dh_params_dh = d.get("dh_params_dh", self.dh_params_dh)
        self.blender_map = d.get("blender_map", self.blender_map)
        self.servo_limits = {int(k): v for k, v in d.get("servo_limits", {}).items()}
        self.juntas_invertidas = d.get("juntas_invertidas", self.juntas_invertidas)


# ==========================================================================
# CINEMÁTICA DIRETA (funções puras — fáceis de testar isoladamente)
# ==========================================================================
def dh_transform(theta, L, d, alpha):
    theta_rad = math.radians(theta)
    alpha_rad = math.radians(alpha)

    ct, st = math.cos(theta_rad), math.sin(theta_rad)
    ca, sa = math.cos(alpha_rad), math.sin(alpha_rad)

    return np.array([
        [ct, -st * ca, st * sa, L * ct],
        [st, ct * ca, -ct * sa, L * st],
        [0, sa, ca, d],
        [0, 0, 0, 1]
    ])


def calcular_cinematica_direta(joint_angles, dh_params):
    """Retorna (x, y, z, T_final) do efetuador."""
    if not dh_params:
        return 0.0, 0.0, 0.0, np.eye(4)

    T = np.eye(4)
    for i, params in enumerate(dh_params):
        theta_dh, L, d, alpha = params
        theta = joint_angles[i] if i < len(joint_angles) else theta_dh
        T = T @ dh_transform(theta, L, d, alpha)

    return T[0, 3], T[1, 3], T[2, 3], T


def cinematica_completa(joint_angles, dh_params):
    """Retorna a lista de posições (x, y, z) de CADA junta (incluindo a base
    em (0,0,0)), útil para desenhar o braço inteiro, não só o efetuador."""
    pontos = [(0.0, 0.0, 0.0)]
    if not dh_params:
        return pontos

    T = np.eye(4)
    for i, params in enumerate(dh_params):
        theta_dh, L, d, alpha = params
        theta = joint_angles[i] if i < len(joint_angles) else theta_dh
        T = T @ dh_transform(theta, L, d, alpha)
        pontos.append((T[0, 3], T[1, 3], T[2, 3]))

    return pontos


def alcance_maximo(dh_params):
    alcance = sum(abs(L) + abs(d) for _theta, L, d, _alpha in dh_params)
    return max(alcance, 50.0)


# ==========================================================================
# CLIENTE BLENDER (socket) — agora com locks e exceções específicas
# ==========================================================================
class BlenderClient:
    def __init__(self, host="127.0.0.1", port=65432, timeout=2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.connected = False
        self._lock = threading.Lock()

    def connect(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            self.socket = s
            self.connected = True
            return True
        except (OSError, socket.timeout) as e:
            self.connected = False
            self._ultimo_erro = str(e)
            return False

    def send(self, command):
        if not self.connected or not self.socket:
            return None
        with self._lock:
            try:
                self.socket.sendall(json.dumps(command).encode("utf-8"))
                bruto = self.socket.recv(4096).decode("utf-8")
                return json.loads(bruto)
            except (OSError, socket.timeout, json.JSONDecodeError, UnicodeDecodeError):
                self.connected = False
                return None

    def set_angle(self, joint, value):
        return self.send({"type": "set_angle", "joint": joint, "value": value})

    def set_angles(self, angles):
        return self.send({"type": "set_angles", "angles": angles})

    def get_angles(self):
        return self.send({"type": "get_angles"})

    def ping(self):
        return self.send({"type": "ping"})

    def close(self):
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None
        self.connected = False


# ==========================================================================
# APLICAÇÃO PRINCIPAL
# ==========================================================================
class RobotArmApp:
    def __init__(self, root):
        self.root = root
        self.config = ConfiguracaoManipulador()

        self.servo_vars = []
        self.ser = None
        self.blender_client = None
        self.modo_atual = "fisico"
        self.conectado_blender = False
        self.animando = False

        self.poses = []  # cada item: {"nome": str, "angulos": [int, ...]}

        self.fila_eventos = queue.Queue()

        self._pulse_t = 0.0
        self._blender_ping_falhas = 0

        self._construir_janela()
        self._construir_menu()
        self._construir_ui()
        self.configurar_padrao()

        self.root.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.root.after(100, self._drenar_fila_eventos)
        self.root.after(200, self._animar_pulso_conexao)
        self.root.after(1000, self._atualizar_relogio)
        self.root.after(4000, self._blender_heartbeat)

        self.log("Aplicação iniciada.", "info")

    # ------------------------------------------------------------------
    # JANELA / SCROLL
    # ------------------------------------------------------------------
    def _construir_janela(self):
        self.root.title("Cinemática Direta · Denavit-Hartenberg")
        self.root.geometry("1420x820")
        self.root.configure(bg=BG)
        self.root.minsize(1100, 650)

        self.main_canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        v_scroll = tk.Scrollbar(self.root, orient="vertical", command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=v_scroll.set)

        v_scroll.pack(side="right", fill="y")
        self.main_canvas.pack(side="left", fill="both", expand=True)

        self.scrollable_frame = tk.Frame(self.main_canvas, bg=BG)
        self.canvas_window = self.main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")))
        self.main_canvas.bind("<Configure>", lambda e: self.main_canvas.itemconfig(self.canvas_window, width=e.width))
        self.main_canvas.bind_all("<MouseWheel>", lambda e: self.main_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=SURF2, background=SURF2,
                         foreground=TEXT, selectbackground=SURF3, selectforeground=TEXT,
                         bordercolor=BORDER, arrowcolor=TEXT_DIM, relief="flat", padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", SURF2)], background=[("readonly", SURF2)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=SURF2, foreground=TEXT_DIM, padding=[16, 9], font=FONT_HEAD)
        style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", TEXT)])

    def _construir_menu(self):
        menubar = tk.Menu(self.root, bg=SURFACE, fg=TEXT, activebackground=ACCENT, activeforeground="#fff", bd=0)

        m_arquivo = tk.Menu(menubar, tearoff=0, bg=SURFACE, fg=TEXT, activebackground=ACCENT, activeforeground="#fff")
        m_arquivo.add_command(label="Salvar configuração...", command=self.salvar_configuracao)
        m_arquivo.add_command(label="Carregar configuração...", command=self.carregar_configuracao)
        m_arquivo.add_separator()
        m_arquivo.add_command(label="Restaurar padrão de fábrica", command=self.configurar_padrao)
        m_arquivo.add_separator()
        m_arquivo.add_command(label="Sair", command=self._ao_fechar)
        menubar.add_cascade(label="Arquivo", menu=m_arquivo)

        m_poses = tk.Menu(menubar, tearoff=0, bg=SURFACE, fg=TEXT, activebackground=ACCENT, activeforeground="#fff")
        m_poses.add_command(label="Exportar poses...", command=self.exportar_poses)
        m_poses.add_command(label="Importar poses...", command=self.importar_poses)
        menubar.add_cascade(label="Poses", menu=m_poses)

        m_ajuda = tk.Menu(menubar, tearoff=0, bg=SURFACE, fg=TEXT, activebackground=ACCENT, activeforeground="#fff")
        m_ajuda.add_command(label="Sobre", command=lambda: messagebox.showinfo(
            "Sobre",
            "Painel de Controle · Cinemática Direta DH\n"
            "Controle de manipulador robótico via Hiwonder LSC e/ou Blender.\n"
            "Cores do robô: Azul Metalizado, Preto, Prata, Branco, Amarelo, Vermelho."))
        menubar.add_cascade(label="Ajuda", menu=m_ajuda)

        self.root.config(menu=menubar)

    # ------------------------------------------------------------------
    # CONSTRUÇÃO DA UI
    # ------------------------------------------------------------------
    def _construir_ui(self):
        self._construir_header()

        corpo = tk.Frame(self.scrollable_frame, bg=BG)
        corpo.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        self._construir_card_conexao(corpo)

        self.notebook = ttk.Notebook(corpo)
        self.notebook.pack(fill="both", expand=True, pady=8)

        self.aba_controle = tk.Frame(self.notebook, bg=BG)
        self.aba_dh = tk.Frame(self.notebook, bg=BG)
        self.aba_poses = tk.Frame(self.notebook, bg=BG)
        self.aba_log = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.aba_controle, text="🎮  Controle")
        self.notebook.add(self.aba_dh, text="📐  Parâmetros DH")
        self.notebook.add(self.aba_poses, text="⭐  Poses Salvas")
        self.notebook.add(self.aba_log, text="🗒  Log")

        self._construir_aba_controle(self.aba_controle)
        self._construir_aba_dh(self.aba_dh)
        self._construir_aba_poses(self.aba_poses)
        self._construir_aba_log(self.aba_log)

        self._construir_status_bar()

    # ---------- HEADER (gradiente) ----------
    def _construir_header(self):
        hdr_wrap = tk.Frame(self.scrollable_frame, bg=SURFACE, height=64)
        hdr_wrap.pack(fill="x")
        hdr_wrap.pack_propagate(False)

        grad = tk.Canvas(hdr_wrap, height=3, bg=SURFACE, highlightthickness=0)
        grad.pack(fill="x", side="top")

        def desenhar_gradiente(event=None):
            grad.delete("all")
            largura = grad.winfo_width() or 1400
            passos = 60
            for i in range(passos):
                t = i / passos
                cor = interpolar_cor(BLUE, CYAN, t)
                x0 = int(largura * i / passos)
                x1 = int(largura * (i + 1) / passos)
                grad.create_rectangle(x0, 0, x1, 3, fill=cor, width=0)

        grad.bind("<Configure>", desenhar_gradiente)

        conteudo = tk.Frame(hdr_wrap, bg=SURFACE)
        conteudo.pack(fill="both", expand=True)

        tk.Label(conteudo, text="🤖", font=("Segoe UI", 20), bg=SURFACE).pack(side="left", padx=(18, 8))
        titulo_frame = tk.Frame(conteudo, bg=SURFACE)
        titulo_frame.pack(side="left")
        tk.Label(titulo_frame, text="Cinemática Direta · Denavit-Hartenberg", font=FONT_TITLE,
                 bg=SURFACE, fg=TEXT).pack(anchor="w")
        self.subtitulo_var = tk.StringVar(value="Manipulador Genérico  ·  6 juntas")
        tk.Label(titulo_frame, textvariable=self.subtitulo_var, font=FONT_SUBTITLE,
                 bg=SURFACE, fg=TEXT_DIM).pack(anchor="w")

        # indicador de pulso geral (resumo de conexão) no canto direito do header
        self.pulso_canvas = tk.Canvas(conteudo, width=22, height=22, bg=SURFACE, highlightthickness=0)
        self.pulso_canvas.pack(side="right", padx=20)

    # ---------- CARD DE CONEXÃO ----------
    def _construir_card_conexao(self, parent):
        c_conn = card(parent, padx=18, pady=14)
        c_conn.pack(fill="x", pady=(12, 6))

        tk.Label(c_conn, text="CONEXÃO", font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).grid(
            row=0, column=0, columnspan=9, sticky="w", pady=(0, 10))

        tk.Label(c_conn, text="Porta:", font=FONT_BODY, bg=SURFACE, fg=TEXT_DIM).grid(row=1, column=0, sticky="w")
        self.combo_portas = ttk.Combobox(c_conn, width=13, state="readonly")
        self.combo_portas.grid(row=1, column=1, padx=(6, 2))

        flat_btn(c_conn, "↺ Atualizar", self.listar_portas, tooltip="Procurar portas seriais disponíveis").grid(row=1, column=2, padx=5)
        flat_btn(c_conn, "Conectar", self.conectar, bg=ACCENT, fg="#fff", hover=ACCENT_HOVER,
                 tooltip="Conectar à placa controladora do robô físico").grid(row=1, column=3, padx=5)
        flat_btn(c_conn, "Desconectar", self.desconectar, bg=RED, fg="#fff").grid(row=1, column=4, padx=5)

        self.status_var = tk.StringVar(value="○ Desconectado")
        self.lbl_status = tk.Label(c_conn, textvariable=self.status_var, font=FONT_BODY, bg=SURFACE, fg=RED)
        self.lbl_status.grid(row=1, column=5, padx=(20, 0), sticky="w")

        self.dot_fisico = tk.Canvas(c_conn, width=14, height=14, bg=SURFACE, highlightthickness=0)
        self.dot_fisico.grid(row=1, column=6, padx=(6, 0))

        tk.Label(c_conn, text="Blender:", font=FONT_BODY, bg=SURFACE, fg=TEXT_DIM).grid(row=2, column=0, sticky="w", pady=(8, 0))
        flat_btn(c_conn, "Conectar", self.conectar_blender, bg=BLUE, fg="#fff", hover=ACCENT_HOVER).grid(row=2, column=1, padx=5, pady=(8, 0))
        flat_btn(c_conn, "Desconectar", self.desconectar_blender, bg=RED, fg="#fff").grid(row=2, column=2, padx=5, pady=(8, 0))

        self.status_blender_var = tk.StringVar(value="○ Desconectado do Blender")
        self.lbl_status_blender = tk.Label(c_conn, textvariable=self.status_blender_var, font=FONT_BODY, bg=SURFACE, fg=RED)
        self.lbl_status_blender.grid(row=2, column=3, padx=(20, 0), pady=(8, 0), sticky="w")

        self.dot_blender = tk.Canvas(c_conn, width=14, height=14, bg=SURFACE, highlightthickness=0)
        self.dot_blender.grid(row=2, column=4, padx=(6, 0), pady=(8, 0))

        self.modo_var = tk.StringVar(value="Robô Físico")
        for i, valor in enumerate(["Robô Físico", "Simulação Blender", "Ambos"]):
            tk.Radiobutton(
                c_conn, text=valor, variable=self.modo_var, value=valor, command=self.alternar_modo,
                bg=SURFACE, fg=TEXT, selectcolor=SURF2, activebackground=SURFACE,
                activeforeground=TEXT, font=FONT_BODY
            ).grid(row=2, column=6 + i, padx=5, pady=(8, 0))

        self.status_modo_var = tk.StringVar(value="Modo: Robô Físico")
        tk.Label(c_conn, textvariable=self.status_modo_var, font=FONT_BODY, bg=SURFACE, fg=ACCENT).grid(
            row=1, column=8, rowspan=2, padx=20)

    # ---------- ABA CONTROLE ----------
    def _construir_aba_controle(self, parent):
        linha_sup = tk.Frame(parent, bg=BG)
        linha_sup.pack(fill="both", expand=True, pady=6)

        esquerda = tk.Frame(linha_sup, bg=BG)
        esquerda.pack(side="left", fill="both", expand=True)

        direita = tk.Frame(linha_sup, bg=BG)
        direita.pack(side="left", fill="y", padx=(10, 0))

        self.frame_sliders = card(esquerda, padx=18, pady=14)
        self.frame_sliders.pack(fill="x")

        c_pos = card(esquerda, padx=18, pady=14)
        c_pos.pack(fill="x", pady=6)
        tk.Label(c_pos, text="POSIÇÃO DO EFETUADOR (calculada a partir dos parâmetros DE CONTROLE)",
                 font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))

        self.pos_x_var = tk.StringVar(value="0.0")
        self.pos_y_var = tk.StringVar(value="0.0")
        self.pos_z_var = tk.StringVar(value="0.0")
        for col, (label, var, color) in enumerate([("X", self.pos_x_var, BLUE), ("Y", self.pos_y_var, ACCENT), ("Z", self.pos_z_var, YELLOW)]):
            f = tk.Frame(c_pos, bg=SURF2, padx=12, pady=8)
            f.grid(row=1, column=col, padx=8, sticky="ew")
            tk.Label(f, text=label + ":", font=FONT_HEAD, bg=SURF2, fg=TEXT_DIM).pack(side="left")
            tk.Label(f, textvariable=var, font=("Consolas", 14, "bold"), bg=SURF2, fg=color, width=8, anchor="e").pack(side="left", padx=(8, 0))
            tk.Label(f, text="mm", font=FONT_SMALL, bg=SURF2, fg=TEXT_DIM).pack(side="left", padx=(4, 0))
        c_pos.grid_columnconfigure(0, weight=1)
        c_pos.grid_columnconfigure(1, weight=1)
        c_pos.grid_columnconfigure(2, weight=1)

        c_tempo = card(esquerda, padx=18, pady=14)
        c_tempo.pack(fill="x", pady=6)
        tk.Label(c_tempo, text="TEMPO DE MOVIMENTO", font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))
        tk.Label(c_tempo, text="Duração:", font=FONT_BODY, bg=SURFACE, fg=TEXT_DIM).grid(row=1, column=0, sticky="w")
        tk.Label(c_tempo, text="100ms", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM, width=6, anchor="e").grid(row=1, column=1, padx=2)
        self.tempo_var = tk.IntVar(value=3000)
        tk.Scale(c_tempo, variable=self.tempo_var, from_=100, to=5000, orient="horizontal",
                 resolution=100, length=320, showvalue=False, bg=SURFACE, fg=TEXT, troughcolor=SURF2,
                 activebackground=YELLOW, highlightthickness=0, sliderlength=20, bd=0, cursor="hand2"
                 ).grid(row=1, column=2, padx=8)
        tk.Label(c_tempo, text="5 s", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM, width=4).grid(row=1, column=3)
        t_frame = tk.Frame(c_tempo, bg=SURF2, padx=6, pady=2)
        t_frame.grid(row=1, column=4, padx=6)
        tk.Label(t_frame, textvariable=self.tempo_var, width=5, anchor="e", font=("Consolas", 11, "bold"),
                 bg=SURF2, fg=YELLOW).pack(side="left")
        tk.Label(t_frame, text=" ms", font=FONT_SMALL, bg=SURF2, fg=TEXT_DIM).pack(side="left")

        c_btns = tk.Frame(esquerda, bg=BG)
        c_btns.pack(pady=16)
        flat_btn(c_btns, "⌖  Centralizar", self.centralizar, bg=SURF2, fg=TEXT,
                 tooltip="Volta todas as juntas para a posição padrão").pack(side="left", padx=8)
        self.btn_mover = tk.Button(
            c_btns, text="▶  MOVER BRAÇO", command=self.mover_confirmar,
            bg=ACCENT, fg="#fff", relief="flat", activebackground=ACCENT_HOVER, activeforeground="#fff",
            font=FONT_BIG, cursor="hand2", bd=0, padx=34, pady=12
        )
        self.btn_mover.pack(side="left", padx=8)
        flat_btn(c_btns, "💾  Salvar Pose", self.salvar_pose, bg=SURF2, fg=TEXT,
                 tooltip="Salva os ângulos atuais na aba Poses Salvas").pack(side="left", padx=8)

        # ---- Visualizador 2D ao vivo ----
        c_vis = card(direita, padx=14, pady=14)
        c_vis.pack(fill="y")
        tk.Label(c_vis, text="VISUALIZAÇÃO AO VIVO", font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).pack(anchor="w", pady=(0, 8))

        tk.Label(c_vis, text="Vista Lateral (alcance × altura)", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(anchor="w")
        self.canvas_lateral = tk.Canvas(c_vis, width=280, height=230, bg="#161616", highlightthickness=1, highlightbackground=SURF3)
        self.canvas_lateral.pack(pady=(2, 12))

        tk.Label(c_vis, text="Vista de Topo (X × Y)", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(anchor="w")
        self.canvas_topo = tk.Canvas(c_vis, width=280, height=230, bg="#161616", highlightthickness=1, highlightbackground=SURF3)
        self.canvas_topo.pack(pady=(2, 4))

        legenda = tk.Frame(c_vis, bg=SURFACE)
        legenda.pack(fill="x", pady=(8, 0))
        tk.Label(legenda, text="⬤", fg=RED, bg=SURFACE, font=FONT_SMALL).grid(row=0, column=0)
        tk.Label(legenda, text="zona proibida de segurança", fg=TEXT_DIM, bg=SURFACE, font=FONT_TINY).grid(row=0, column=1, sticky="w")

    # ---------- ABA DH ----------
    def _construir_aba_dh(self, parent):
        frame_dh = card(parent, padx=18, pady=14)
        frame_dh.pack(fill="both", expand=True, pady=6)

        tk.Label(frame_dh, text="PARÂMETROS DH - 6 ELOS FIXOS", font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 12))

        frame_dh_pos = tk.Frame(frame_dh, bg=SURFACE, padx=10, pady=8)
        frame_dh_pos.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(0, 10))
        tk.Label(frame_dh_pos, text="POSIÇÃO DO EFETUADOR:", font=FONT_HEAD, bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=(0, 15))

        self.pos_x_dh_var = tk.StringVar(value="0.0")
        self.pos_y_dh_var = tk.StringVar(value="0.0")
        self.pos_z_dh_var = tk.StringVar(value="0.0")
        for label, var, color in [("X:", self.pos_x_dh_var, BLUE), ("Y:", self.pos_y_dh_var, ACCENT), ("Z:", self.pos_z_dh_var, YELLOW)]:
            tk.Label(frame_dh_pos, text=label, font=FONT_BODY, bg=SURFACE, fg=color).pack(side="left")
            tk.Label(frame_dh_pos, textvariable=var, font=("Consolas", 11, "bold"), bg=SURFACE, fg=color, width=6, anchor="e").pack(side="left", padx=(2, 10))
            tk.Label(frame_dh_pos, text="mm", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=(0, 15))

        self.frame_dh_tabela = tk.Frame(frame_dh, bg=SURFACE)
        self.frame_dh_tabela.grid(row=2, column=0, columnspan=6, sticky="nsew", pady=(0, 10))
        frame_dh.grid_rowconfigure(2, weight=1)
        frame_dh.grid_columnconfigure(0, weight=1)

        c_dh_controls = tk.Frame(frame_dh, bg=SURFACE)
        c_dh_controls.grid(row=3, column=0, columnspan=6, pady=10)
        flat_btn(c_dh_controls, "↻ Atualizar DH", self.atualizar_dh_fixo, bg=ACCENT, fg="#fff", hover=ACCENT_HOVER).pack(side="left", padx=4)
        tk.Label(c_dh_controls, text="(6 elos fixos - independente do Controle)", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=15)

    # ---------- ABA POSES ----------
    def _construir_aba_poses(self, parent):
        c = card(parent, padx=18, pady=14)
        c.pack(fill="both", expand=True, pady=6)

        tk.Label(c, text="POSES SALVAS", font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).pack(anchor="w", pady=(0, 10))

        corpo = tk.Frame(c, bg=SURFACE)
        corpo.pack(fill="both", expand=True)

        lista_frame = tk.Frame(corpo, bg=SURFACE)
        lista_frame.pack(side="left", fill="both", expand=True)

        self.lista_poses = tk.Listbox(
            lista_frame, bg=SURF2, fg=TEXT, selectbackground=ACCENT, selectforeground="#fff",
            font=FONT_MONO_SM, height=16, activestyle="none", selectmode="extended",
            highlightthickness=0, bd=0
        )
        self.lista_poses.pack(side="left", fill="both", expand=True)
        scroll_poses = tk.Scrollbar(lista_frame, command=self.lista_poses.yview)
        scroll_poses.pack(side="left", fill="y")
        self.lista_poses.config(yscrollcommand=scroll_poses.set)

        botoes = tk.Frame(corpo, bg=SURFACE)
        botoes.pack(side="left", fill="y", padx=(16, 0))

        tk.Label(botoes, text="Nome da pose:", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(anchor="w")
        self.nome_pose_var = tk.StringVar(value="")
        tk.Entry(botoes, textvariable=self.nome_pose_var, bg=SURF2, fg=TEXT, font=FONT_BODY,
                  relief="flat", insertbackground=TEXT, width=22).pack(pady=(2, 10))

        flat_btn(botoes, "💾  Salvar pose atual", self.salvar_pose, bg=ACCENT, fg="#fff", hover=ACCENT_HOVER).pack(fill="x", pady=3)
        flat_btn(botoes, "↩  Carregar selecionada", self.carregar_pose_selecionada, bg=SURF2, fg=TEXT).pack(fill="x", pady=3)
        flat_btn(botoes, "🗑  Excluir selecionada(s)", self.excluir_poses_selecionadas, bg=RED, fg="#fff").pack(fill="x", pady=3)
        tk.Frame(botoes, bg=SURF3, height=1).pack(fill="x", pady=10)
        flat_btn(botoes, "▶▶  Reproduzir sequência", self.reproduzir_sequencia, bg=PURPLE, fg="#1C1C1C",
                  tooltip="Reproduz, em ordem, as poses selecionadas na lista").pack(fill="x", pady=3)
        tk.Frame(botoes, bg=SURF3, height=1).pack(fill="x", pady=10)
        flat_btn(botoes, "⬇  Exportar poses (.json)", self.exportar_poses, bg=SURF2, fg=TEXT).pack(fill="x", pady=3)
        flat_btn(botoes, "⬆  Importar poses (.json)", self.importar_poses, bg=SURF2, fg=TEXT).pack(fill="x", pady=3)

    # ---------- ABA LOG ----------
    def _construir_aba_log(self, parent):
        c = card(parent, padx=18, pady=14)
        c.pack(fill="both", expand=True, pady=6)

        topo = tk.Frame(c, bg=SURFACE)
        topo.pack(fill="x")
        tk.Label(topo, text="LOG DE EVENTOS E COMANDOS", font=FONT_SECTION, bg=SURFACE, fg=TEXT_DIM).pack(side="left")
        flat_btn(topo, "Limpar", self._limpar_log, bg=SURF2, fg=TEXT).pack(side="right")

        self.texto_log = ScrolledText(
            c, bg="#141414", fg=TEXT, font=FONT_MONO_SM, height=24, bd=0,
            insertbackground=TEXT, wrap="word", state="disabled"
        )
        self.texto_log.pack(fill="both", expand=True, pady=(10, 0))
        self.texto_log.tag_config("info", foreground=CYAN)
        self.texto_log.tag_config("aviso", foreground=YELLOW)
        self.texto_log.tag_config("erro", foreground=RED)
        self.texto_log.tag_config("envio", foreground=GREEN)

    # ---------- BARRA DE STATUS ----------
    def _construir_status_bar(self):
        footer = tk.Frame(self.scrollable_frame, bg=SURFACE, height=32)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        tk.Label(footer, text="Cores do Robô: Azul Metalizado • Preto Fosco • Prata • Branco • Amarelo • Vermelho",
                 font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM).pack(side="left", padx=18)

        self.relogio_var = tk.StringVar(value="")
        tk.Label(footer, textvariable=self.relogio_var, font=FONT_MONO_SM, bg=SURFACE, fg=TEXT_DIM).pack(side="right", padx=18)

    # ==================================================================
    # LOG / FILA DE EVENTOS (thread-safe)
    # ==================================================================
    def log(self, mensagem, nivel="info"):
        """Pode ser chamado de qualquer thread: apenas empilha na fila."""
        self.fila_eventos.put(("log", nivel, mensagem))

    def _drenar_fila_eventos(self):
        try:
            while True:
                item = self.fila_eventos.get_nowait()
                tipo = item[0]
                if tipo == "log":
                    _, nivel, msg = item
                    self._escrever_log(nivel, msg)
                elif tipo == "serial_status":
                    _, ok, msg = item
                    self._aplicar_status_serial(ok, msg)
                elif tipo == "blender_status":
                    _, ok, msg = item
                    self._aplicar_status_blender(ok, msg)
                elif tipo == "blender_resposta":
                    _, ok, msg = item
                    if ok:
                        messagebox.showinfo("Sucesso", msg)
                    else:
                        messagebox.showerror("Erro", msg)
        except queue.Empty:
            pass
        self.root.after(80, self._drenar_fila_eventos)

    def _escrever_log(self, nivel, mensagem):
        ts = datetime.now().strftime("%H:%M:%S")
        self.texto_log.config(state="normal")
        self.texto_log.insert("end", f"[{ts}] ", "info")
        self.texto_log.insert("end", f"{mensagem}\n", nivel)
        self.texto_log.see("end")
        self.texto_log.config(state="disabled")

    def _limpar_log(self):
        self.texto_log.config(state="normal")
        self.texto_log.delete("1.0", "end")
        self.texto_log.config(state="disabled")

    # ==================================================================
    # ANIMAÇÕES DE INTERFACE (pulso de conexão / relógio)
    # ==================================================================
    def _animar_pulso_conexao(self):
        self._pulse_t += 0.12
        raio = 3 + 2.2 * abs(math.sin(self._pulse_t))

        for canvas, ativo in ((self.dot_fisico, self.ser is not None), (self.dot_blender, self.conectado_blender)):
            canvas.delete("all")
            cor = GREEN if ativo else RED
            canvas.create_oval(7 - raio, 7 - raio, 7 + raio, 7 + raio, fill=cor, outline="")
            if ativo:
                canvas.create_oval(7 - 6, 7 - 6, 7 + 6, 7 + 6, outline=cor, width=1)

        self.pulso_canvas.delete("all")
        geral_ok = (self.ser is not None) or self.conectado_blender
        cor_geral = GREEN if geral_ok else TEXT_DIM
        self.pulso_canvas.create_oval(11 - raio, 11 - raio, 11 + raio, 11 + raio, fill=cor_geral, outline="")

        self.root.after(90, self._animar_pulso_conexao)

    def _atualizar_relogio(self):
        self.relogio_var.set(datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))
        self.root.after(1000, self._atualizar_relogio)

    # ==================================================================
    # CONFIGURAÇÃO PADRÃO / SALVAR / CARREGAR
    # ==================================================================
    def configurar_padrao(self):
        self.config.nome = "Manipulador Genérico"
        self.config.n_juntas = 6

        self.config.juntas_controle = [
            ["Base", -90, 90, 0, 6],
            ["Ombro", 0, 180, 90, 5],
            ["Cotovelo", -90, 90, 0, 4],
            ["Punho Rot.", -90, 90, 0, 3],
            ["Punho Incl.", -90, 90, 0, 2],
            ["Garra", -90, 90, 0, 1],
        ]

        self.config.dh_params_controle = [
            [0, 0, 69, 90],
            [0, 95, 0, 0],
            [0, 95, 0, 0],
            [0, 169, 0, -90],
        ]

        self.config.dh_params_dh = [[0, 0, 0, 0] for _ in range(6)]

        self.config.blender_map = {
            "Base": "BASE", "Ombro": "J1", "Cotovelo": "J2",
            "Punho Rot.": "J3", "Punho Incl.": "J4", "Garra": "J5",
        }

        # Mínimo: 122 | Central: 497 | Máximo: 872
        self.config.servo_limits = {6: [122, 872], 5: [122, 872], 4: [122, 872],
                                     3: [122, 872], 2: [122, 872], 1: [122, 872]}
        self.config.juntas_invertidas = [2]  # Cotovelo com sinal invertido

        self.subtitulo_var.set(f"{self.config.nome}  ·  {self.config.n_juntas} juntas")
        self._recriar_interface()
        self.log("Configuração padrão de fábrica carregada.", "info")

    def salvar_configuracao(self):
        caminho = filedialog.asksaveasfilename(
            title="Salvar configuração do manipulador", defaultextension=".json",
            initialfile="config_manipulador.json", filetypes=[("JSON", "*.json")])
        if not caminho:
            return
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(self.config.to_dict(), f, ensure_ascii=False, indent=2)
            self.log(f"Configuração salva em: {caminho}", "info")
            messagebox.showinfo("Sucesso", "Configuração salva com sucesso!")
        except OSError as e:
            self.log(f"Falha ao salvar configuração: {e}", "erro")
            messagebox.showerror("Erro", f"Não foi possível salvar o arquivo:\n{e}")

    def carregar_configuracao(self):
        caminho = filedialog.askopenfilename(title="Carregar configuração do manipulador", filetypes=[("JSON", "*.json")])
        if not caminho:
            return
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            self.config.from_dict(dados)
            self.subtitulo_var.set(f"{self.config.nome}  ·  {self.config.n_juntas} juntas")
            self._recriar_interface()
            self.log(f"Configuração carregada de: {caminho}", "info")
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            self.log(f"Falha ao carregar configuração: {e}", "erro")
            messagebox.showerror("Erro", f"Arquivo de configuração inválido:\n{e}")

    def _recriar_interface(self):
        self._criar_sliders()
        self._criar_tabela_dh_fixa()
        self.root.after(80, self.atualizar_posicao_controle)
        self.root.after(80, self.atualizar_posicao_dh)

    # ==================================================================
    # SLIDERS DE CONTROLE
    # ==================================================================
    def _criar_sliders(self):
        self.servo_vars = []
        for widget in self.frame_sliders.winfo_children():
            widget.destroy()

        tk.Label(self.frame_sliders, text="CONTROLE DO MANIPULADOR", font=FONT_SECTION,
                 bg=SURFACE, fg=TEXT_DIM).grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 6))

        for col, (lbl, anc) in enumerate([("Junta", "w"), ("Mín", "e"), ("", "center"), ("Máx", "w"), ("Val", "center"), ("Servo", "center")]):
            tk.Label(self.frame_sliders, text=lbl, font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM,
                     anchor=anc, width=5 if col > 0 else 16).grid(row=1, column=col, padx=(0, 4))

        for i, (label, lo, hi, default, canal) in enumerate(self.config.juntas_controle):
            row = i + 2
            color = J_COLORS[i % len(J_COLORS)]

            pill = tk.Frame(self.frame_sliders, bg=color, width=4, height=24)
            pill.grid(row=row, column=0, sticky="w", pady=3, padx=(0, 6))

            marca = " ↺" if i in self.config.juntas_invertidas else ""
            tk.Label(self.frame_sliders, text=label + marca, width=15, anchor="w", font=FONT_HEAD,
                     bg=SURFACE, fg=color).grid(row=row, column=0, sticky="w", padx=(10, 0), pady=3)

            tk.Label(self.frame_sliders, text=f"{lo}°", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM,
                     width=5, anchor="e").grid(row=row, column=1, padx=2)

            sv = tk.IntVar(value=default)
            self.servo_vars.append(sv)

            sl = tk.Scale(
                self.frame_sliders, variable=sv, from_=lo, to=hi, orient="horizontal",
                resolution=1, length=250, showvalue=False, bg=SURFACE, fg=TEXT, troughcolor=SURF2,
                activebackground=color, highlightthickness=0, sliderlength=20, bd=0, cursor="hand2",
                command=lambda *_: self._on_slider_change()
            )
            sl.grid(row=row, column=2, padx=8)

            tk.Label(self.frame_sliders, text=f"{hi}°", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM,
                     width=5, anchor="w").grid(row=row, column=3, padx=2)

            val_frame = tk.Frame(self.frame_sliders, bg=SURF2, padx=6, pady=2)
            val_frame.grid(row=row, column=4, padx=6)
            tk.Label(val_frame, textvariable=sv, width=5, anchor="e", font=("Consolas", 11, "bold"),
                     bg=SURF2, fg=color).pack(side="left")
            tk.Label(val_frame, text="°", font=FONT_SMALL, bg=SURF2, fg=TEXT_DIM).pack(side="left")

            tk.Label(self.frame_sliders, text=f"Servo {canal}", font=FONT_SMALL, bg=SURFACE, fg=TEXT_DIM,
                     width=8, anchor="center").grid(row=row, column=5, padx=6)

    def _on_slider_change(self):
        self.atualizar_posicao_controle()
        self.atualizar_posicao_dh()
        self._atualizar_visualizador()

    # ==================================================================
    # TABELA DH EDITÁVEL
    # ==================================================================
    def _criar_tabela_dh_fixa(self):
        for widget in self.frame_dh_tabela.winfo_children():
            widget.destroy()

        headers = ["Elo", "θ (°)", "L (mm)", "d (mm)", "α (°)", "Transformação"]
        for col, header in enumerate(headers):
            tk.Label(self.frame_dh_tabela, text=header, font=FONT_HEAD, bg=SURFACE, fg=ACCENT,
                     width=12 if col < 5 else 14, anchor="center").grid(row=0, column=col, padx=4, pady=4, sticky="ew")

        while len(self.config.dh_params_dh) < 6:
            self.config.dh_params_dh.append([0, 0, 0, 0])

        self.config.dh_entries_dh = []
        for row in range(6):
            params = self.config.dh_params_dh[row]
            i = row + 1

            tk.Label(self.frame_dh_tabela, text=str(row + 1), font=FONT_BODY, bg=SURFACE, fg=TEXT).grid(row=i, column=0, padx=4, pady=2)

            entradas = {}
            for col, (chave, valor) in enumerate(zip(["theta", "L", "d", "alpha"], params), start=1):
                e = tk.Entry(self.frame_dh_tabela, width=10, bg=SURF2, fg=TEXT, font=FONT_MONO,
                             relief="flat", justify="center", insertbackground=TEXT)
                e.insert(0, str(valor))
                e.grid(row=i, column=col, padx=4, pady=2)
                entradas[chave] = e

            btn_frame = tk.Frame(self.frame_dh_tabela, bg=SURFACE)
            btn_frame.grid(row=i, column=5, padx=4, pady=2)
            flat_btn(btn_frame, "Ver T", lambda r=row: self.mostrar_transformacao_individual(r),
                     bg=SURF2, fg=TEXT, font=FONT_SMALL, padx=8, pady=2).pack()

            self.config.dh_entries_dh.append(entradas)

    def ler_valores_dh_fixos(self):
        """Lê e valida a tabela DH. Campos inválidos ficam com borda vermelha
        em vez de serem silenciosamente ignorados."""
        houve_erro = False
        for i, entry_dict in enumerate(self.config.dh_entries_dh):
            if i >= len(self.config.dh_params_dh):
                continue
            valores = {}
            campo_invalido = False
            for chave, entry in entry_dict.items():
                texto = entry.get().strip()
                try:
                    valores[chave] = float(texto) if texto else 0.0
                    entry.config(highlightthickness=0)
                except ValueError:
                    campo_invalido = True
                    houve_erro = True
                    entry.config(highlightthickness=2, highlightbackground=RED, highlightcolor=RED)
            if not campo_invalido:
                self.config.dh_params_dh[i] = [valores["theta"], valores["L"], valores["d"], valores["alpha"]]
        if houve_erro:
            self.log("Existem campos inválidos na tabela DH (destacados em vermelho).", "aviso")
        return not houve_erro

    def atualizar_dh_fixo(self):
        if self.ler_valores_dh_fixos():
            self.atualizar_posicao_dh()
            self.log("Parâmetros DH atualizados.", "info")
            messagebox.showinfo("Sucesso", "Parâmetros DH atualizados!")
        else:
            messagebox.showerror("Erro", "Corrija os campos inválidos (bordas vermelhas) antes de atualizar.")

    def mostrar_transformacao_individual(self, row_idx):
        try:
            self.ler_valores_dh_fixos()
            if row_idx >= len(self.config.dh_params_dh):
                messagebox.showerror("Erro", "Elo não encontrado!")
                return

            theta_dh, L, d, alpha = self.config.dh_params_dh[row_idx]
            angles = [sv.get() for sv in self.servo_vars[:len(self.config.dh_params_dh)]]
            theta = angles[row_idx] if row_idx < len(angles) else theta_dh
            Ti = dh_transform(theta, L, d, alpha)

            janela_matriz = tk.Toplevel(self.root)
            janela_matriz.title(f"Transformação Individual - Elo {row_idx + 1}")
            janela_matriz.configure(bg=BG)
            janela_matriz.geometry("500x500")

            tk.Label(janela_matriz, text=f"Transformação do Elo {row_idx + 1}", font=FONT_TITLE, bg=BG, fg=TEXT).pack(pady=10)

            params_frame = tk.Frame(janela_matriz, bg=SURFACE, padx=20, pady=10)
            params_frame.pack(pady=5)
            tk.Label(params_frame, text=f"θ = {theta:.1f}°   L = {L:.1f} mm   d = {d:.1f} mm   α = {alpha:.1f}°",
                     font=FONT_BODY, bg=SURFACE, fg=ACCENT).pack()

            frame_matriz = tk.Frame(janela_matriz, bg=SURFACE, padx=20, pady=20)
            frame_matriz.pack(pady=10)
            for r in range(4):
                for c in range(4):
                    tk.Label(frame_matriz, text=f"{Ti[r][c]:.3f}", font=("Consolas", 11), bg=SURFACE, fg=TEXT,
                             width=10, anchor="center", relief="solid", bd=1, padx=5, pady=5).grid(row=r, column=c, padx=2, pady=2)

            pos_frame = tk.Frame(janela_matriz, bg=SURFACE, padx=20, pady=10)
            pos_frame.pack(pady=10)
            tk.Label(pos_frame, text=f"Posição local: X={Ti[0][3]:.1f}, Y={Ti[1][3]:.1f}, Z={Ti[2][3]:.1f} mm",
                     font=FONT_BODY, bg=SURFACE, fg=ACCENT).pack()

            flat_btn(janela_matriz, "Fechar", janela_matriz.destroy, bg=SURF2, fg=TEXT, padx=20, pady=8).pack(pady=10)
        except (ValueError, IndexError, TypeError) as e:
            messagebox.showerror("Erro", f"Erro ao calcular transformação: {e}")

    # ==================================================================
    # CINEMÁTICA / POSIÇÃO / VISUALIZADOR
    # ==================================================================
    def atualizar_posicao_controle(self):
        if not self.config.dh_params_controle or not self.servo_vars:
            self.pos_x_var.set("0.0"); self.pos_y_var.set("0.0"); self.pos_z_var.set("0.0")
            return
        angles = [sv.get() for sv in self.servo_vars[:len(self.config.dh_params_controle)]]
        x, y, z, _ = calcular_cinematica_direta(angles, self.config.dh_params_controle)
        self.pos_x_var.set(f"{x:.1f}"); self.pos_y_var.set(f"{y:.1f}"); self.pos_z_var.set(f"{z:.1f}")

    def atualizar_posicao_dh(self):
        if not self.config.dh_params_dh or not self.servo_vars:
            self.pos_x_dh_var.set("0.0"); self.pos_y_dh_var.set("0.0"); self.pos_z_dh_var.set("0.0")
            return
        angles = [sv.get() for sv in self.servo_vars[:len(self.config.dh_params_dh)]]
        x, y, z, _ = calcular_cinematica_direta(angles, self.config.dh_params_dh)
        self.pos_x_dh_var.set(f"{x:.1f}"); self.pos_y_dh_var.set(f"{y:.1f}"); self.pos_z_dh_var.set(f"{z:.1f}")

    def _atualizar_visualizador(self):
        if not hasattr(self, "canvas_lateral") or not self.config.dh_params_controle or not self.servo_vars:
            return
        angles = [sv.get() for sv in self.servo_vars[:len(self.config.dh_params_controle)]]
        pontos = cinematica_completa(angles, self.config.dh_params_controle)
        alcance = alcance_maximo(self.config.dh_params_controle)
        self._desenhar_vista_lateral(pontos, alcance)
        self._desenhar_vista_topo(pontos, alcance)

    def _desenhar_vista_lateral(self, pontos, alcance):
        cv = self.canvas_lateral
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        origem_x, origem_y = 34, h - 24
        escala = (h - 55) / alcance

        # grade / chão
        cv.create_line(10, origem_y, w - 10, origem_y, fill=SURF3, dash=(2, 3))
        cv.create_text(w - 30, origem_y + 10, text="chão (Z=0)", fill=TEXT_DIM, font=FONT_TINY)
        for gz in range(0, int(alcance) + 1, max(50, int(alcance // 4) or 50)):
            y = origem_y - gz * escala
            cv.create_line(10, y, w - 10, y, fill="#1E1E1E")
            cv.create_text(20, y, text=f"{gz}", fill=TEXT_DIM, font=FONT_TINY, anchor="e")

        cv.create_oval(origem_x - 8, origem_y - 6, origem_x + 8, origem_y + 6, fill=SURF4, outline="")

        coords = []
        for (x, y, z) in pontos:
            r = math.hypot(x, y)
            cx = origem_x + r * escala
            cy = origem_y - z * escala
            coords.append((cx, cy))

        for i in range(len(coords) - 1):
            cor = J_COLORS[i % len(J_COLORS)]
            x0, y0 = coords[i]
            x1, y1 = coords[i + 1]
            cv.create_line(x0, y0, x1, y1, fill=cor, width=5, capstyle="round")
            cv.create_oval(x0 - 5, y0 - 5, x0 + 5, y0 + 5, fill=cor, outline="#0C0C0C", width=1)

        if coords:
            xe, ye = coords[-1]
            cv.create_oval(xe - 7, ye - 7, xe + 7, ye + 7, fill=YELLOW, outline="#0C0C0C", width=1)
            cv.create_text(xe + 12, ye - 4, text="efetuador", fill=YELLOW, font=FONT_TINY, anchor="w")

    def _desenhar_vista_topo(self, pontos, alcance):
        cv = self.canvas_topo
        cv.delete("all")
        w, h = int(cv["width"]), int(cv["height"])
        origem_x, origem_y = w // 2, h // 2
        escala = (min(w, h) / 2 - 25) / alcance

        cv.create_line(origem_x, 10, origem_x, h - 10, fill="#1E1E1E")
        cv.create_line(10, origem_y, w - 10, origem_y, fill="#1E1E1E")

        # zona proibida: x<0, -100<=y<=100 (aprox., válida quando 0<=Z<=75)
        x0 = 10
        x1 = origem_x
        y0 = origem_y - 100 * escala
        y1 = origem_y + 100 * escala
        cv.create_rectangle(x0, max(10, y0), x1, min(h - 10, y1), fill="#3A1414", outline=RED, dash=(3, 2))
        cv.create_text((x0 + x1) / 2, 20, text="zona proibida (Z 0-75mm)", fill=RED, font=FONT_TINY)

        cv.create_oval(origem_x - 8, origem_y - 8, origem_x + 8, origem_y + 8, fill=SURF4, outline="")

        coords = []
        for (x, y, _z) in pontos:
            cx = origem_x + x * escala
            cy = origem_y - y * escala
            coords.append((cx, cy))

        for i in range(len(coords) - 1):
            cor = J_COLORS[i % len(J_COLORS)]
            x0p, y0p = coords[i]
            x1p, y1p = coords[i + 1]
            cv.create_line(x0p, y0p, x1p, y1p, fill=cor, width=5, capstyle="round")
            cv.create_oval(x0p - 5, y0p - 5, x0p + 5, y0p + 5, fill=cor, outline="#0C0C0C", width=1)

        if coords:
            xe, ye = coords[-1]
            cv.create_oval(xe - 7, ye - 7, xe + 7, ye + 7, fill=YELLOW, outline="#0C0C0C", width=1)

    # ==================================================================
    # CONVERSÃO ÂNGULO → SERVO
    # ==================================================================
    def angle_to_servo(self, angle, idx):
        if idx in self.config.juntas_invertidas:
            angle = -angle

        if idx < len(self.config.juntas_controle):
            servo_id = self.config.juntas_controle[idx][4]
            if servo_id in self.config.servo_limits:
                min_servo, max_servo = self.config.servo_limits[servo_id]
                min_angle = self.config.juntas_controle[idx][1]
                max_angle = self.config.juntas_controle[idx][2]
                if max_angle - min_angle != 0:
                    v = int((angle - min_angle) / (max_angle - min_angle) * (max_servo - min_servo) + min_servo)
                    return max(min_servo, min(max_servo, v))

        v = int((angle + 90) * (750 / 180) + 122)
        return max(122, min(872, v))

    # ==================================================================
    # PORTA SERIAL
    # ==================================================================
    def listar_portas(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_portas["values"] = ports
        if ports:
            self.combo_portas.current(0)
        else:
            self.combo_portas.set("")
        self.log(f"{len(ports)} porta(s) serial encontrada(s).", "info")

    def conectar(self):
        porta = self.combo_portas.get()
        if not porta:
            messagebox.showerror("Erro", "Selecione uma porta COM.")
            return

        def worker():
            try:
                s = serial.Serial(porta, 115200, timeout=1)
                time.sleep(2)
                self.ser = s
                self._enviar_serial_thread("from Hiwonder import LSC")
                self.fila_eventos.put(("serial_status", True, porta))
            except serial.SerialException as e:
                self.ser = None
                self.fila_eventos.put(("serial_status", False, str(e)))

        threading.Thread(target=worker, daemon=True).start()
        self.status_var.set(f"⏳ Conectando em {porta}...")
        self.lbl_status.config(fg=YELLOW)

    def _aplicar_status_serial(self, ok, msg):
        if ok:
            self.status_var.set(f"● Conectado em {msg}")
            self.lbl_status.config(fg=GREEN)
            self.log(f"Conectado à controladora em {msg}.", "info")
        else:
            self.status_var.set("○ Desconectado")
            self.lbl_status.config(fg=RED)
            self.log(f"Falha ao conectar: {msg}", "erro")
            messagebox.showerror("Erro de conexão", msg)

    def desconectar(self):
        if self.ser:
            try:
                self.ser.close()
            except serial.SerialException:
                pass
            self.ser = None
        self.status_var.set("○ Desconectado")
        self.lbl_status.config(fg=RED)
        self.log("Desconectado da controladora.", "info")

    def _enviar_serial_thread(self, cmd):
        """Só deve ser chamado de dentro de uma thread de trabalho."""
        if self.ser:
            try:
                self.ser.write((cmd + "\r\n").encode())
                self.log(f"Enviado: {cmd}", "envio")
            except serial.SerialException as e:
                self.log(f"Erro ao enviar comando serial: {e}", "erro")

    # ==================================================================
    # BLENDER
    # ==================================================================
    def conectar_blender(self):
        def worker():
            client = BlenderClient()
            if client.connect():
                self.blender_client = client
                self.conectado_blender = True
                self.fila_eventos.put(("blender_status", True, ""))
            else:
                self.blender_client = None
                self.conectado_blender = False
                self.fila_eventos.put(("blender_status", False, "Blender não encontrado"))

        if self.blender_client:
            self.blender_client.close()
        self.status_blender_var.set("⏳ Conectando ao Blender...")
        self.lbl_status_blender.config(fg=YELLOW)
        threading.Thread(target=worker, daemon=True).start()

    def _aplicar_status_blender(self, ok, msg):
        if ok:
            self.status_blender_var.set("● Conectado ao Blender")
            self.lbl_status_blender.config(fg=GREEN)
            self.log("Conectado ao Blender.", "info")
        else:
            self.status_blender_var.set(f"○ {msg or 'Erro na conexão'}")
            self.lbl_status_blender.config(fg=RED)
            self.log(f"Falha ao conectar ao Blender: {msg}", "aviso")

    def desconectar_blender(self):
        if self.blender_client:
            self.blender_client.close()
            self.blender_client = None
        self.conectado_blender = False
        self.status_blender_var.set("○ Desconectado do Blender")
        self.lbl_status_blender.config(fg=RED)
        self.log("Desconectado do Blender.", "info")

    def _blender_heartbeat(self):
        """Faz ping periódico ao Blender para manter o status de conexão
        honesto (detecta quedas de conexão sem precisar clicar em nada)."""
        if self.conectado_blender and self.blender_client:
            def worker():
                resp = self.blender_client.ping()
                ainda_ok = resp is not None
                self.fila_eventos.put(("blender_status", ainda_ok, "" if ainda_ok else "conexão perdida"))
                if not ainda_ok:
                    self.conectado_blender = False
            threading.Thread(target=worker, daemon=True).start()
        self.root.after(5000, self._blender_heartbeat)

    # ==================================================================
    # MOVIMENTO
    # ==================================================================
    def verificar_limites(self, x, y, z):
        if z < 0:
            return False, f"Z = {z:.1f} mm (não pode ser negativo!)"

        if x < 0 and -100 <= y <= 100 and 0 <= z <= 75:
            return False, f"Posição na caixa proibida!\nX = {x:.1f} mm (negativo)\nY = {y:.1f} mm\nZ = {z:.1f} mm (0 a 75)"

        ombro_angle = self.servo_vars[1].get() if len(self.servo_vars) > 1 else 0
        cotovelo_angle = self.servo_vars[2].get() if len(self.servo_vars) > 2 else 0

        if ombro_angle >= 150:
            reducao = ombro_angle - 150
            cotovelo_limite = 50 - reducao
            if cotovelo_angle > cotovelo_limite:
                return False, (f"Restrição de movimento!\nOmbro = {ombro_angle}° (≥150°)\n"
                                f"Cotovelo deve ser ≤ {cotovelo_limite:.0f}°\nCotovelo atual = {cotovelo_angle}°")

        return True, "Posição válida"

    def mover_confirmar(self):
        if self.modo_atual == "fisico" and self.ser is None:
            messagebox.showerror("Sem conexão", "Conecte primeiro à controladora.")
            return
        if self.modo_atual in ("blender", "ambos") and not self.conectado_blender:
            messagebox.showerror("Sem conexão", "Conecte-se ao Blender primeiro.")
            return

        self.atualizar_posicao_controle()
        x, y, z = float(self.pos_x_var.get()), float(self.pos_y_var.get()), float(self.pos_z_var.get())

        valido, mensagem = self.verificar_limites(x, y, z)
        if not valido:
            messagebox.showerror("Posição Inválida",
                                  f"❌ Posição fora dos limites de segurança!\n\n{mensagem}\n\n"
                                  f"X = {x:.1f} mm\nY = {y:.1f} mm\nZ = {z:.1f} mm")
            return

        angles = [sv.get() for sv in self.servo_vars[:len(self.config.juntas_controle)]]
        angles_str = ", ".join(f"{self.config.juntas_controle[i][0]}={angles[i]}°" for i in range(len(angles)))
        modo_texto = {"fisico": "Robô Físico", "blender": "Simulação Blender", "ambos": "Robô Físico + Blender"}.get(self.modo_atual, "Robô Físico")

        if messagebox.askyesno(
            "Confirmar Movimento",
            f"Posição final:\nX: {self.pos_x_var.get()} mm\nY: {self.pos_y_var.get()} mm\nZ: {self.pos_z_var.get()} mm\n\n"
            f"Ângulos: {angles_str}\n\nModo: {modo_texto}\nDeseja continuar?"
        ):
            self.mover()

    def mover(self):
        if self.modo_atual == "fisico":
            self.mover_fisico()
        elif self.modo_atual == "blender":
            self.mover_blender()
        else:
            self.mover_fisico()
            self.mover_blender()

    def mover_fisico(self):
        servo_comandos = []
        for i, sv in enumerate(self.servo_vars):
            if i < len(self.config.juntas_controle):
                canal = self.config.juntas_controle[i][4]
                valor = self.angle_to_servo(sv.get(), i)
                servo_comandos.append(f"({canal},{valor})")

        t = self.tempo_var.get()
        cmd = f"LSC.moveServos(({','.join(servo_comandos)}),{t})"

        def worker():
            self._enviar_serial_thread(cmd)

        threading.Thread(target=worker, daemon=True).start()

    def mover_blender(self):
        if not self.conectado_blender or not self.blender_client:
            return

        angles_blender = {}
        for i, sv in enumerate(self.servo_vars):
            if i < len(self.config.juntas_controle):
                nome = self.config.juntas_controle[i][0]
                if nome in self.config.blender_map:
                    angles_blender[self.config.blender_map[nome]] = sv.get()

        def worker():
            resp = self.blender_client.set_angles(angles_blender)
            if resp and resp.get("status") == "success":
                self.fila_eventos.put(("blender_resposta", True, "Ângulos enviados para o Blender!"))
                self.log("Ângulos enviados para o Blender.", "envio")
            else:
                self.fila_eventos.put(("blender_resposta", False, "Falha ao enviar para o Blender"))
                self.log("Falha ao enviar ângulos para o Blender.", "erro")

        threading.Thread(target=worker, daemon=True).start()

    def centralizar(self):
        for i, sv in enumerate(self.servo_vars):
            if i < len(self.config.juntas_controle):
                sv.set(self.config.juntas_controle[i][3])
        self.atualizar_posicao_controle()
        self.atualizar_posicao_dh()
        self._atualizar_visualizador()

    def alternar_modo(self):
        modo_selecionado = self.modo_var.get()
        if modo_selecionado == "Robô Físico":
            self.modo_atual = "fisico"
            self.btn_mover.config(text="▶  MOVER BRAÇO", bg=ACCENT)
        elif modo_selecionado == "Simulação Blender":
            self.modo_atual = "blender"
            self.btn_mover.config(text="▶  MOVER (BLENDER)", bg=BLUE)
            if not self.conectado_blender:
                self.conectar_blender()
        else:
            self.modo_atual = "ambos"
            self.btn_mover.config(text="▶  MOVER (AMBOS)", bg=PURPLE)
            if not self.conectado_blender:
                self.conectar_blender()
        self.status_modo_var.set(f"Modo: {modo_selecionado}")

    # ==================================================================
    # POSES SALVAS
    # ==================================================================
    def salvar_pose(self):
        nome = (self.nome_pose_var.get().strip() if hasattr(self, "nome_pose_var") else "") or f"Pose {len(self.poses) + 1}"
        angulos = [sv.get() for sv in self.servo_vars]
        self.poses.append({"nome": nome, "angulos": angulos})
        self._atualizar_lista_poses()
        self.nome_pose_var.set("")
        self.log(f"Pose '{nome}' salva.", "info")

    def _atualizar_lista_poses(self):
        if not hasattr(self, "lista_poses"):
            return
        self.lista_poses.delete(0, "end")
        for p in self.poses:
            resumo = ", ".join(str(a) for a in p["angulos"])
            self.lista_poses.insert("end", f"{p['nome']}   [{resumo}]")

    def _poses_selecionadas(self):
        return list(self.lista_poses.curselection())

    def carregar_pose_selecionada(self):
        sel = self._poses_selecionadas()
        if not sel:
            messagebox.showwarning("Nenhuma pose selecionada", "Selecione uma pose na lista.")
            return
        pose = self.poses[sel[0]]
        self._animar_para_pose(pose["angulos"])
        self.log(f"Pose '{pose['nome']}' carregada.", "info")

    def excluir_poses_selecionadas(self):
        sel = self._poses_selecionadas()
        if not sel:
            messagebox.showwarning("Nenhuma pose selecionada", "Selecione ao menos uma pose para excluir.")
            return
        for i in sorted(sel, reverse=True):
            removida = self.poses.pop(i)
            self.log(f"Pose '{removida['nome']}' excluída.", "aviso")
        self._atualizar_lista_poses()

    def exportar_poses(self):
        caminho = filedialog.asksaveasfilename(title="Exportar poses", defaultextension=".json",
                                                 initialfile="poses.json", filetypes=[("JSON", "*.json")])
        if not caminho:
            return
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(self.poses, f, ensure_ascii=False, indent=2)
            self.log(f"{len(self.poses)} pose(s) exportada(s) para {caminho}.", "info")
        except OSError as e:
            self.log(f"Falha ao exportar poses: {e}", "erro")
            messagebox.showerror("Erro", str(e))

    def importar_poses(self):
        caminho = filedialog.askopenfilename(title="Importar poses", filetypes=[("JSON", "*.json")])
        if not caminho:
            return
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if not isinstance(dados, list):
                raise ValueError("Formato inesperado (esperava uma lista de poses).")
            self.poses.extend(dados)
            self._atualizar_lista_poses()
            self.log(f"{len(dados)} pose(s) importada(s) de {caminho}.", "info")
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self.log(f"Falha ao importar poses: {e}", "erro")
            messagebox.showerror("Erro", str(e))

    def _animar_para_pose(self, angulos_alvo, passos=20, intervalo_ms=15, ao_concluir=None):
        if self.animando:
            return
        self.animando = True
        angulos_iniciais = [sv.get() for sv in self.servo_vars]
        n = min(len(angulos_iniciais), len(angulos_alvo))

        def passo(k):
            if k > passos:
                self.animando = False
                if ao_concluir:
                    ao_concluir()
                return
            t = k / passos
            for i in range(n):
                valor = angulos_iniciais[i] + (angulos_alvo[i] - angulos_iniciais[i]) * t
                self.servo_vars[i].set(int(round(valor)))
            self._on_slider_change()
            self.root.after(intervalo_ms, lambda: passo(k + 1))

        passo(0)

    def reproduzir_sequencia(self):
        sel = self._poses_selecionadas()
        if not sel:
            messagebox.showwarning("Nenhuma pose selecionada", "Selecione uma ou mais poses (Ctrl/Shift + clique) para reproduzir em sequência.")
            return
        indices = list(sel)
        self.log(f"Reproduzindo sequência de {len(indices)} pose(s)...", "info")
        self._reproduzir_proxima(indices, 0)

    def _reproduzir_proxima(self, indices, k):
        if k >= len(indices):
            self.log("Sequência de poses concluída.", "info")
            return
        pose = self.poses[indices[k]]

        def apos_animar():
            self.mover()
            self.root.after(max(600, self.tempo_var.get()), lambda: self._reproduzir_proxima(indices, k + 1))

        self._animar_para_pose(pose["angulos"], ao_concluir=apos_animar)

    # ==================================================================
    # ENCERRAMENTO
    # ==================================================================
    def _ao_fechar(self):
        try:
            if self.ser:
                self.ser.close()
        except serial.SerialException:
            pass
        if self.blender_client:
            self.blender_client.close()
        self.root.destroy()


# ==========================================================================
# PONTO DE ENTRADA
# ==========================================================================
def main():
    janela = tk.Tk()
    RobotArmApp(janela)
    janela.mainloop()


if __name__ == "__main__":
    main()
