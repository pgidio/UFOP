# RoboDH Control — Controle de Braço Robótico (Blender + Robô Físico)

Sistema de controle para um braço robótico (XArm) com duas frentes de trabalho:

1. **Simulação 3D no Blender**, usando um *armature* (esqueleto de ossos) que representa as juntas do braço.
2. **Controle do robô físico** (baseado em MicroPython, servos Hiwonder LSC), enviado via porta serial/USB.

> ⚠️ **Aviso importante:** este repositório contém scripts que **apagam arquivos do robô físico** (ver seção [Scripts de manutenção](#-scripts-de-manutenção-cuidado)). Leia a documentação antes de executar qualquer coisa em um robô real.

---

## 📁 Estrutura do repositório

| Arquivo | Descrição |
|---|---|
| `1.blend` / `1.blend1` | Cena do Blender com o braço robótico (armature) e a simulação visual. `.blend1` é o backup automático gerado pelo Blender. |
| `XArm.glb` | Modelo 3D do braço robótico (formato glTF binário), exportado do Blender para uso em outras engines/visualizadores. |
| `robo_dh_controle.py` | Script de cinemática do robô (DH = *Denavit–Hartenberg*), usado para calcular/aplicar os ângulos das juntas. |
| `codigo_bruto.txt` | Versão inicial (rascunho) do script que aplica ângulos fixos nos ossos do armature dentro do Blender. |
| `codigo_lapdado.txt` | Versão refinada do controle: roda **dentro do Blender**, sobe um **servidor TCP local** (`127.0.0.1:65432`) e recebe comandos JSON para mover as juntas em tempo real. |
| `main.py` | Programa que roda **no robô físico** (MicroPython). Lê comandos via `stdin`/serial no formato `s1,s2,s3,s4,s5,s6,tempo` e move os 6 servos usando a biblioteca `Hiwonder.LSC`. |
| `salvar_tudo_robo.py` | Utilitário de **backup**: conecta ao robô via serial, lista e copia todos os arquivos `.py` para o computador. Não altera nada no robô. |
| `remover_main_critico_nao_mecha.py` | Utilitário de **manutenção crítica**: conecta ao robô, apaga o `main.py` e reinicia o dispositivo. ⚠️ Use com extremo cuidado. |
| `Instalação_e_envio_da_main_py_para_o_robô.pdf` | Passo a passo para instalar dependências e enviar o `main.py` para o robô via `mpremote`. |
| `RoboDH_Control_part1.rar`, `RoboDH_Control_part2.rar` | Projeto completo compactado em partes (para upload/distribuição). |
| `leia.txt` | Explicação rápida (em português) sobre os dois scripts de backup/manutenção. |

---

## 🧠 Como o sistema funciona

```
┌─────────────────────┐        JSON via TCP        ┌───────────────────────────┐
│   Script externo /   │  ────────────────────────▶ │   Blender (codigo_lapdado) │
│   controlador (não    │   {"type": "set_angle",   │   Servidor em 127.0.0.1:  │
│   incluso no repo)   │    "joint": "J1", ...}      │   65432, move o armature   │
└─────────────────────┘                              └───────────────────────────┘

┌─────────────────────┐        Serial (USB)         ┌───────────────────────────┐
│  salvar_tudo_robo.py │  ────────────────────────▶ │        Robô físico         │
│  remover_main_...py  │                              │  (MicroPython + main.py)  │
└─────────────────────┘                              └───────────────────────────┘
```

- **No Blender**, o `codigo_lapdado.txt` (rodado como script interno do Blender) inicia um servidor de sockets que aceita comandos `set_angle`, `set_angles`, `get_angles` e `ping` para mover os ossos (`Bone.001` a `Bone.007`) que representam Base, J1, J2, J3, J4 e J5.
- **No robô físico**, o `main.py` fica em loop lendo linhas no formato:
  ```
  s1,s2,s3,s4,s5,s6,tempo
  ```
  e move os 6 servos com `LSC.moveServos(...)`.
- Os scripts `salvar_tudo_robo.py` e `remover_main_critico_nao_mecha.py` conversam com o robô por **serial** (porta COM) para fazer backup ou apagar o programa principal, respectivamente.

> ℹ️ O script que efetivamente conecta o Blender ao robô físico em tempo real (citado no PDF como `controle_do_braco.py`) **não está presente neste conjunto de arquivos** — adicione-o ao repositório se ele existir, ou documente que essa ponte ainda precisa ser criada.

---

## 🔧 Requisitos

- **Blender** (versão compatível com o arquivo `1.blend`)
- **Python 3** instalado no computador (marcar "Add Python to PATH" na instalação)
- Bibliotecas Python:
  ```bash
  pip install pyserial
  pip install mpremote
  python -m pip install numpy
  ```
- Robô com **MicroPython** e a biblioteca `Hiwonder` (`LSC`) instalada

---

## 🚀 Instalação e envio do `main.py` para o robô

1. Instale o Python marcando a opção **"Add Python to PATH"**.
2. Abra o PowerShell e instale as dependências:
   ```powershell
   pip install pyserial
   pip install mpremote
   python -m pip install numpy
   ```
3. Acesse a pasta onde está o `main.py` compatível:
   ```powershell
   cd "C:\caminho\para\a\pasta"
   ```
4. Liste as portas seriais disponíveis:
   ```powershell
   mpremote connect list
   ```
5. Apague o `main.py` existente no robô:
   ```powershell
   mpremote connect COMX rm main.py
   ```
   *(substitua `COMX` pela porta correta, ex.: `COM3`)*
6. Envie o novo `main.py` para o robô:
   ```powershell
   mpremote connect auto fs cp main.py :
   ```
7. Reinicie o robô:
   ```powershell
   mpremote connect COMX reset
   ```

---

## 🎮 Uso

### Simulação no Blender
1. Abra `1.blend` no Blender.
2. Rode o script `codigo_lapdado.txt` (cole no editor de texto/script do Blender) para iniciar o servidor de controle em `127.0.0.1:65432`.
3. Envie comandos JSON via socket, por exemplo:
   ```json
   {"type": "set_angle", "joint": "J1", "value": 45}
   ```

### Robô físico
1. Envie o `main.py` para o robô seguindo os passos de instalação acima.
2. Envie comandos via serial no formato:
   ```
   90,90,90,90,90,90,1000
   ```
   (posição de cada servo 1–6 e tempo de movimento em ms)

---

## 🛠️ Scripts de manutenção (⚠️ cuidado)

### `salvar_tudo_robo.py` — Backup (seguro)
Conecta ao robô, interrompe o programa em execução, lista e copia todos os arquivos `.py` para uma pasta local (`C:\backup_robo\...`). **Não altera nada no robô.**

```bash
python salvar_tudo_robo.py
```

### `remover_main_critico_nao_mecha.py` — Remoção do `main.py` (⚠️ destrutivo)
Conecta ao robô, apaga o arquivo `main.py` e reinicia o dispositivo. Sem esse arquivo, o robô **para de executar automaticamente** seu comportamento até que um novo `main.py` seja enviado.

```bash
python remover_main_critico_nao_mecha.py
```

> Use apenas se tiver certeza do que está fazendo — faça sempre um backup com `salvar_tudo_robo.py` antes.

---
