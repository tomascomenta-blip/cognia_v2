import pygame
import random  # (splice manager: bug 1 de la ronda 9)
pygame.init()

screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption("Flappy Bird")

bird_pos = [400, 300]
bird_vel = 0
gravity = 0.5

pipe_pos = [800, 0]
pipe_gap = 150

score = 0

font = pygame.font.SysFont(None, 50)

clock = pygame.time.Clock()

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            quit()
        if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            bird_vel = -8

    pipe_pos[0] -= 4  # (splice manager: bug 2 de la ronda 9)
    bird_pos[1] += bird_vel
    bird_vel += gravity

    if bird_pos[1] > 600:
        bird_pos[1] = 300
        bird_vel = 0
        pygame.quit()
        quit()

    if pipe_pos[0] < 0:
        pipe_pos = [800, random.randint(100, 500)]
        score += 1

    screen.fill((135, 206, 235))

    pygame.draw.circle(screen, (255, 255, 0), bird_pos, 20)

    pygame.draw.rect(screen, (0, 255, 0), (pipe_pos[0], 0, 50, pipe_pos[1]))
    pygame.draw.rect(screen, (0, 255, 0), (pipe_pos[0], pipe_pos[1] + pipe_gap, 50, 600))

    text = font.render(f"Score: {score}", True, (0, 0, 0))
    screen.blit(text, (10, 10))

    pygame.display.flip()
    clock.tick(60)