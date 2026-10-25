"""Named agent builders, shared by the batch runner, the GA and the UI."""

from agents.baseline.random_agents import RandomRed, RandomBlue
from agents.blue.agent import BlueAI, DEFAULT_WEIGHTS
from agents.red.agent import RedAI

RED = {
    "ai": lambda fast=False: RedAI(time_limit=0.05 if fast else 0.2, iterations=400 if fast else 1000),
    "astar": lambda fast=False: RedAI(use_mcts=False),
    "random": lambda fast=False: RandomRed(),
}

BLUE = {
    "ai": lambda fast=False: BlueAI(particles=1000 if fast else 2000),
    "untuned": lambda fast=False: BlueAI(weights=DEFAULT_WEIGHTS, particles=1000 if fast else 2000,
                                         name="Blue AI (untuned)"),
    "nofilter": lambda fast=False: BlueAI(use_filter=False),
    "random": lambda fast=False: RandomBlue(),
}
