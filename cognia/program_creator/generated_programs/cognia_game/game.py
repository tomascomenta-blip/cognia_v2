

import random

def adivina_el_numero():
    numero_a_adivinar = random.randint(1, 100)
    intentos = 0

    print("Bienvenido al juego de adivina el número!")
    print("Estoy pensando en un número entre 1 y 100.")
    
    while True:
        try:
            intento = int(input("Adivina el número: "))
            intentos += 1

            if intento < numero_a_adivinar:
                print("¡El número es mayor!")
            elif intento > numero_a_adivinar:
                print("¡El número es menor!")
            else:
                print(f"¡Correcto! Adivinaste el número en {intentos} intentos.")
                break
        except ValueError:
            print("Por favor, ingresa un número válido.")

if __name__ == "__main__":
    adivina_el_numero()
