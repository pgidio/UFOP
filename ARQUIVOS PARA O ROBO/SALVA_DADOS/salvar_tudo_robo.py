import serial
import time
import os as os_local
from datetime import datetime

# Definir pasta de backup na RAIZ DO C:
pasta_base = r"C:\backup_robo"
pasta_backup = os_local.path.join(pasta_base, f"backup_completo_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
os_local.makedirs(pasta_backup, exist_ok=True)

print(f"[INFO] Criando backup em: {pasta_backup}")
print("[INFO] Conectando ao robo...")

ser = serial.Serial('COM3', 115200, timeout=3)
time.sleep(2)

# Ctrl+C para interromper
print("[INFO] Interrompendo codigo...")
for _ in range(5):
    ser.write(b'\x03')
    time.sleep(0.3)

time.sleep(1)

def ler_resposta():
    time.sleep(0.5)
    while ser.in_waiting:
        print(ser.readline().decode('utf-8', errors='ignore'), end='')

# Listar arquivos
print("\n[INFO] Listando arquivos do robo...")
ser.write(b'import os\r\n')
time.sleep(0.3)
ser.write(b'print([f for f in os.listdir() if f.endswith(".py")])\r\n')
time.sleep(0.5)

# Capturar lista de arquivos
arquivos = []
time.sleep(0.5)
while ser.in_waiting:
    linha = ser.readline().decode('utf-8', errors='ignore').strip()
    if linha and not linha.startswith('>>>'):
        print(f"   {linha}")
        if '[' in linha and ']' in linha:
            try:
                linha_limpa = linha.replace('[', '').replace(']', '').replace("'", "").replace(' ', '')
                arquivos = [a for a in linha_limpa.split(',') if a and '.' in a]
            except:
                pass

print(f"\n[INFO] Encontrados {len(arquivos)} arquivos")

# Fazer backup de cada arquivo
print("\n[INFO] Salvando TODOS os arquivos...")

for arquivo in arquivos:
    try:
        print(f"   [INFO] Lendo {arquivo}...")
        ser.write(f'print(open("{arquivo}").read())\r\n'.encode())
        time.sleep(0.5)
        
        conteudo = []
        while ser.in_waiting:
            linha = ser.readline().decode('utf-8', errors='ignore')
            if not linha.startswith('>>>'):
                conteudo.append(linha)
        
        caminho_backup = os_local.path.join(pasta_backup, arquivo)
        with open(caminho_backup, 'w', encoding='utf-8') as f:
            f.write(''.join(conteudo))
        
        print(f"   [OK] {arquivo} salvo ({len(''.join(conteudo))} bytes)")
        
    except Exception as e:
        print(f"   [ERRO] Erro ao salvar {arquivo}: {e}")

# Tentar salvar arquivos importantes mesmo se não estiverem na lista
print("\n[INFO] Verificando arquivos importantes...")
arquivos_importantes = ['boot.py', 'main.py', 'qdeex.py', 'entry.py']

for arquivo in arquivos_importantes:
    if arquivo not in arquivos:
        try:
            ser.write(f'print(open("{arquivo}").read())\r\n'.encode())
            time.sleep(0.5)
            
            conteudo = []
            while ser.in_waiting:
                linha = ser.readline().decode('utf-8', errors='ignore')
                if not linha.startswith('>>>'):
                    conteudo.append(linha)
            
            if conteudo:
                caminho_backup = os_local.path.join(pasta_backup, arquivo)
                with open(caminho_backup, 'w', encoding='utf-8') as f:
                    f.write(''.join(conteudo))
                print(f"   [OK] {arquivo} salvo ({len(''.join(conteudo))} bytes)")
        except:
            pass

# Salvar lista completa
with open(os_local.path.join(pasta_backup, 'LISTA_COMPLETA.txt'), 'w') as f:
    f.write("=" * 50 + "\n")
    f.write("BACKUP COMPLETO DO ROBO\n")
    f.write(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("=" * 50 + "\n\n")
    f.write("Arquivos salvos:\n")
    for a in arquivos:
        f.write(f"  - {a}\n")

print("\n" + "=" * 50)
print("[OK] BACKUP COMPLETO CONCLUIDO!")
print(f"[INFO] Pasta: {pasta_backup}")
print(f"[INFO] Arquivos salvos: {len(arquivos)}")
print("=" * 50)
print("\n[INFO] NENHUM arquivo foi alterado no robo!")
print("[INFO] Todos os arquivos foram apenas LIDOS e SALVOS no PC.")

ser.close()