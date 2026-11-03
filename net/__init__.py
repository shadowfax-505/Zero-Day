"""Online play: two copies of the game run the same match in lockstep over TCP.

Both sides generate the same map from the shared seed and the engine's random
numbers come from that seed too, so only the moves travel over the network.
Each move carries a short fingerprint of the sender's game state, which lets
either side spot a desync straight away.
"""
