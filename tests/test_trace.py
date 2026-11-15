"""The decision trace replays a real round and checks itself against the AIs' own answers."""

from experiments.trace_scenario import run


def test_trace_map42_round5_matches_the_game():
    t = run(42, 5)
    assert t["red"]["chosen"] == t["red"]["astar_next"]          # MCTS agreed with A* here
    assert t["blue"]["chosen"].startswith("isolate FS-01")
    assert t["blue"]["minimax"][0]["alloc"] == t["blue"]["chosen"]
    s = t["blue"]["search"]
    assert s["evaluated_with_pruning"] < s["evaluated_without"]    # alpha-beta saved work
    assert "cut Red off" in t["outcome"]["events"][0]
