# This is a Guess the Number Game.

import random

guessesTaken = 0

print("Hello! What is your name?")
myName = input()

number = random.randint(1, 20)
print("Well, " + myName + ", I am thinking of a number between 1 and 20.")

for i in range(6):
    print("Take a guess.")
    guess = input()
    guess = int(guess)

    if guess < number:
        print("Your number is too low.")
        guessesTaken = guessesTaken + 1

    if guess > number:
        print("Your number is too high.")
        guessesTaken = guessesTaken + 1

    if guess == number:
        guessesTaken = guessesTaken + 1
        break

if guess == number:
    guessesTaken = str(guessesTaken)
    print("Good job, " + myName + "! You guessed my number in " + guessesTaken + " guesses!")

if guess != number:
    number = str(number)
    print("Nope. The number I was thinking of was " + number + ".")

