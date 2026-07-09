import serial
import time

ser = serial.Serial('COM4', 115200, timeout=2)
time.sleep(2)

# Ctrl+C para interromper
ser.write(b'\x03')
time.sleep(0.5)
ser.write(b'\x03')
time.sleep(0.5)
ser.write(b'\x03')
time.sleep(1)

# Comandos
comandos = [
    b'import os\r\n',
    b'os.remove("main.py")\r\n',
    b'os.listdir()\r\n',
    b'import machine\r\n',
    b'machine.reset()\r\n',
]

for cmd in comandos:
    ser.write(cmd)
    time.sleep(0.5)
    while ser.in_waiting:
        print(ser.readline().decode('utf-8', errors='ignore'), end='')

ser.close()