# Cognia Generated Game | 2026-04-16T20:25:05.311081
# Category: number guessing game with hints and high score
# Score: 7.3/10 | Version: 1 | Fixes: 0

import random

# Initialize variables
number_to_guess = random.randint(1, 100)
hint_counter = 0
high_score = 0

while True:
    try:
        # Get user's guess
        guess = int(input("Guess the number (1-100): "))

        # Check if guess is correct
        if guess < number_to_guess:
            print("Too low!")
            hint_counter += 1
        elif guess > number_to_guess:
            print("Too high!")
            hint_counter += 1
        else:
            print("Congratulations! You won!")

            # Update high score
            if guess < high_score:
                high_score = guess

            # Reset game for new round
            number_to_guess = random.randint(1, 100)
            hint_counter = 0

        # Display hints and progress
        print(f"Hints: {hint_counter}")
        print(f"Score: {high_score}")

    except ValueError:
        print("Invalid input. Please enter a number.")

    # Exit on keyboard interrupt
    if input("\nPress Enter to play again or Ctrl+C to quit: ") in ["", "quit"]:
        break

print("Game over! Final score:", high_score)