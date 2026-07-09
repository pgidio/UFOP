from Hiwonder import LSC
import sys
import time
import threading

def rodar_qdeex():
    try:
        import qdeex
    except:
        pass

def modo_servo():
    while True:
        try:
            linha = sys.stdin.readline().strip()
            if linha:
                valores = linha.split(",")
                if len(valores) == 7:
                    s1 = int(valores[0])
                    s2 = int(valores[1])
                    s3 = int(valores[2])
                    s4 = int(valores[3])
                    s5 = int(valores[4])
                    s6 = int(valores[5])
                    tempo = int(valores[6])
                    LSC.moveServos(
                        (
                            (1, s1),
                            (2, s2),
                            (3, s3),
                            (4, s4),
                            (5, s5),
                            (6, s6),
                        ),
                        tempo
                    )
        except:
            pass

if __name__ == "__main__":
    try:
        thread_qdeex = threading.Thread(target=rodar_qdeex, daemon=True)
        thread_qdeex.start()
    except:
        pass
    modo_servo()