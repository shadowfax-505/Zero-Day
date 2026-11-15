"""Step-by-step decision trace for one round of one match.

    python -m experiments.trace_scenario --seed 42 --round 5

Plays a Red AI vs Blue AI match on the given map up to the given round, then
prints every number both AIs used to choose their move in that round:

Red   opponent model -> lambda -> A* expansions (g, h, f, step costs) ->
      IS-MCTS root statistics, the tree under each first move and the
      paired test that decides whether MCTS may override A*.
Blue  particle filter (prior, likelihood, posterior) -> fuzzy triage for the
      most threatening nodes (memberships, rules fired, centroid) ->
      candidate actions -> minimax with alpha-beta over the root allocations,
      with the search tree under the chosen and the runner-up allocation.

Nothing is re-implemented with different numbers: the A* and minimax traces
mirror the game's own functions step for step and are checked against the
answer the real code returned. The result is also saved as JSON
(--json PATH) for the report and the slides.
"""

import argparse
import heapq
import json
import math

import numpy as np

from agents.blue.agent import BlueAI
from agents.blue.fuzzy import RULES, OUT, OUT_SETS
from agents.blue.stackelberg import GAMMA
from agents.red.agent import RedAI
from agents.red.astar import plan, heuristic, step_cost, frontier_cost, node_risk, GOAL, UNKNOWN_WEAKNESS
from engine import config as C
from engine.match import Match


def r3(x):
    return None if x is None or x == math.inf else round(float(x), 3)


def act_str(net, a):
    if a[0] in ("scout", "claim", "fog"):
        return a[0]
    return f"{a[0]} {net.label[a[1]]}"


def alloc_str(net, alloc):
    out = []
    for k, t in alloc:
        out.append(f"{k} {C.ZONE_NAMES[t]}" if k == "monitor" else f"{k} {net.label[t]}")
    return " + ".join(out) or "(nothing)"


# ---------------------------------------------------------------- Red: A*
def trace_astar(obs, model, lam, net):
    """Same search as agents.red.astar.plan, logging every pop and relaxation."""
    seen = [0, 0, 0]
    for info in obs.nodes.values():
        seen[info.zone] += 1
    start = obs.pos
    g, prev = {start: 0.0}, {start: None}
    openq = [(heuristic(obs, start), 0.0, start)]
    closed, log = set(), []
    lab = lambda u: "GOAL (through the fog)" if u == GOAL else net.label[u]
    while openq:
        f, gu, u = heapq.heappop(openq)
        if u == GOAL or u == obs.database:
            log.append({"pop": lab(u), "g": r3(gu), "f": r3(f), "goal": True})
            break
        if u in closed:
            continue
        closed.add(u)
        entry = {"pop": lab(u), "node": u, "g": r3(gu), "h": r3(heuristic(obs, u)), "f": r3(f), "relax": []}
        for v in obs.edges.get(u, ()):
            if v not in obs.nodes or obs.nodes[v].isolated:
                continue
            c = step_cost(obs, model, u, v, lam, seen)
            info = obs.nodes[v]
            risk = node_risk(obs, model, v, seen)
            w = model.weakness(v, info, UNKNOWN_WEAKNESS)
            gate = frozenset((u, v)) in obs.gates and not obs.gates[frozenset((u, v))]
            ng = gu + c
            better = ng < g.get(v, math.inf)
            entry["relax"].append({
                "to": lab(v), "id": v, "known_weakness": info.weakness, "est_weakness": r3(w),
                "sens": r3(model.sensitivity(info.zone)), "p_decoy": r3(model.p_decoy(v, info, seen[info.zone])),
                "risk": r3(risk), "gate": gate, "step": r3(c), "g_new": r3(ng),
                "h": r3(heuristic(obs, v)), "f_new": r3(ng + heuristic(obs, v)), "improves": better,
            })
            if better:
                g[v], prev[v] = ng, u
                heapq.heappush(openq, (ng + heuristic(obs, v), ng, v))
        if u not in obs.expanded:
            ng = gu + frontier_cost(obs, u, lam)
            entry["fog_link"] = {"cost": r3(frontier_cost(obs, u, lam)), "g_goal": r3(ng)}
            if ng < g.get(GOAL, math.inf):
                g[GOAL], prev[GOAL] = ng, u
                heapq.heappush(openq, (ng, ng, GOAL))
        log.append(entry)
    return log


def red_tree(net, root, depth=2, top=4):
    def walk(node, d):
        kids = sorted(node.children.values(), key=lambda c: -c.n)
        out = []
        for c in kids[:top]:
            out.append({"action": act_str(net, c.action) if c.action[0] != "fog" else "into the fog",
                        "n": c.n, "q": r3(c.w / c.n) if c.n else None, "avail": c.avail,
                        "children": walk(c, d + 1) if d < depth else [],
                        "more": max(0, len(node.children) - top) if False else 0})
        return out
    return walk(root, 1)


# ---------------------------------------------------------------- Blue: fuzzy
def trace_fuzzy(fz, alert, value, conf):
    mu = {"alert": fz.memberships("alert", alert), "value": fz.memberships("value", value),
          "conf": fz.memberships("conf", conf)}
    fired, agg = [], np.zeros_like(OUT)
    for (a, b), out in RULES:
        s = min(mu[a[0]][a[1]], mu[b[0]][b[1]])
        if s > 0:
            fired.append({"rule": f"IF {a[0]} is {a[1]} AND {b[0]} is {b[1]} THEN {out}", "strength": r3(s), "out": out})
            agg = np.maximum(agg, np.minimum(s, OUT_SETS[out]))
    score = float((agg * OUT).sum() / agg.sum()) if agg.sum() else 0.0
    return {"inputs": {"alert": r3(alert), "value": r3(value), "conf": r3(conf)},
            "memberships": {k: {lv: r3(x) for lv, x in v.items()} for k, v in mu.items()},
            "fired": fired, "centroid": r3(score),
            "level": fz.level(score)}


# ---------------------------------------------------------------- Blue: filter
def trace_likelihood(pf, net, alerts, monitored, v):
    """The pieces of ParticleFilter.likelihood for one node."""
    from agents.blue.particle_filter import EXPECTED_NOISE
    alert_map = dict(alerts)

    def ratio(x):
        mon = C.MONITOR_BOOST if net.zone[x] in monitored else 1.0
        pd = min(0.95, EXPECTED_NOISE * net.sensitivity[x] * mon)
        if x in alert_map:
            s = alert_map[x]
            f_real = math.exp(-((s - 0.6) ** 2) / (2 * 0.22 ** 2)) / 0.55
            f_false = 2.0 if s <= 0.56 else 0.05
            return pd, s, f_real, f_false, (pd * f_real + C.FALSE_ALARM * f_false) / (C.FALSE_ALARM * f_false)
        return pd, None, None, None, (1 - pd * 0.6) / (1 - C.FALSE_ALARM)

    pd, s, f_real, f_false, r = ratio(v)
    spill = sum(ratio(a)[4] - 1 for a in net.adj[v] if a in alert_map)
    return {"node": net.label[v], "pd": r3(pd), "alert": s, "f_real": r3(f_real), "f_false": r3(f_false),
            "ratio": r3(r), "spill_from": [net.label[a] for a in net.adj[v] if a in alert_map],
            "spill": r3(0.3 * spill if spill > 0 else 0.0), "likelihood": r3(r + (0.3 * spill if spill > 0 else 0.0)),
            "sensitivity": net.sensitivity[v], "monitored": net.zone[v] in monitored}


# ---------------------------------------------------------------- Blue: minimax
def utility_parts(pl, st, p, r):
    """Stackelberg.utility for a 'move' reply, term by term."""
    net, w = pl.net, pl.w
    d = pl.dist_to_db(st)
    dmax = max(x for x in d if x != math.inf) or 1.0
    q = r[1]
    mon = C.MONITOR_BOOST if net.zone[q] in st.monitored else 1.0
    cap = 1.0 if q in st.decoys else st.weak[q]
    pd = 1.0 if q in st.decoys else min(1.0, C.NOISE["capture"] * net.sensitivity[q] * mon)
    dq = d[q] if d[q] != math.inf else dmax
    dp = d[p] if d[p] != math.inf else dmax
    after = cap * dq + (1 - cap) * dp
    terms = {"path": w["path"] * after / dmax, "detect": w["detect"] * pd, "loss": -w["value"] * net.value[q] * cap,
             "decoy": w["decoy"] if q in st.decoys else 0.0}
    total = sum(terms.values())
    assert abs(total - pl.utility(st, p, r)) < 1e-9
    return {"reply": f"{r[0]} {net.label[q]}", "cap": r3(cap), "pd": r3(pd), "d_from": r3(dp), "d_to": r3(dq),
            "dmax": r3(dmax), "dist_after": r3(after), "value_q": net.value[q],
            "terms": {k: r3(x) for k, x in terms.items()}, "u": r3(total)}


class MinimaxTracer:
    """Mirror of Stackelberg.red_min / blue_max that keeps the tree."""

    def __init__(self, planner, prune=True):
        self.pl, self.prune = planner, prune
        self.evaluated = 0
        self.cutoffs = 0

    def red_min(self, st, p, depth, alpha, beta):
        pl, net = self.pl, self.pl.net
        best, kids = math.inf, []
        replies = pl.replies(st, p)
        for i, r in enumerate(replies):
            self.evaluated += 1
            u = pl.utility(st, p, r)
            node = {"reply": f"{r[0]} {net.label[r[1]]}", "u_now": r3(u)}
            if st.hit:
                node.update(value=r3(u), note="Red is cut off: this branch ends here")
                kids.append(node)
                return u, kids
            if depth > 1:
                st2, p2 = pl.advance(st, p, r)
                v2, sub = self.blue_max(st2, p2, depth - 1, -math.inf, math.inf)
                node.update(blue_next=r3(v2), red_after=net.label[p2], sub=sub)
                u += GAMMA * v2
            node["value"] = r3(u)
            kids.append(node)
            best = min(best, u)
            beta = min(beta, best)
            if self.prune and best <= alpha:
                self.cutoffs += 1
                kids.append({"pruned": len(replies) - i - 1})
                break
        return best, kids

    def blue_max(self, st, p, depth, alpha, beta):
        pl, net = self.pl, self.pl.net
        best, kids = -math.inf, []
        allocs = pl.lookahead_allocs(st, p)
        for i, al in enumerate(allocs):
            v, sub = self.red_min(pl.apply(st, al, p), p, depth, alpha, beta)
            kids.append({"alloc": alloc_str(net, al), "value": r3(v), "replies": sub})
            best = max(best, v)
            alpha = max(alpha, best)
            if self.prune and best >= beta:
                self.cutoffs += 1
                kids.append({"pruned": len(allocs) - i - 1})
                break
        return best, kids


def trace_minimax(planner, base, positions, root_allocs, depth, net):
    tr = MinimaxTracer(planner, prune=True)
    rows = []
    for alloc in root_allocs:
        per, total = [], 0.0
        for p, bp in positions:
            st = planner.apply(base, alloc, p)
            v, tree = tr.red_min(st, p, depth, -math.inf, math.inf)
            per.append({"pos": net.label[p], "prob": r3(bp), "value": r3(v), "tree": tree})
            total += bp * v
        rows.append({"alloc": alloc_str(net, alloc), "raw": [list(a) for a in alloc], "expected": r3(total), "per_pos": per})
    rows.sort(key=lambda r: -r["expected"])
    full = MinimaxTracer(planner, prune=False)
    for alloc in root_allocs:
        for p, _ in positions:
            full.red_min(planner.apply(base, alloc, p), p, depth, -math.inf, math.inf)
    return rows, {"evaluated_with_pruning": tr.evaluated, "evaluated_without": full.evaluated,
                  "cutoffs": tr.cutoffs}


# ---------------------------------------------------------------- main
def run(seed, rnd):
    red, blue = RedAI(), BlueAI()
    m = Match(red, blue, seed=seed)
    net = m.net
    while m.game.round < rnd and not m.over:
        m.play_round()
    if m.over:
        raise SystemExit(f"match on map {seed} ended before round {rnd}")
    g = m.game
    truth = {"red_pos": net.label[g.red_pos], "red_held": [net.label[u] for u in sorted(g.red_held)],
             "decoys": [net.label[u] for u in sorted(g.decoys)],
             "patched": [net.label[u] for u in sorted(g.patched)],
             "isolated": [net.label[u] for u in g.isolated], "isolate_ready": g.isolate_ready}

    # capture what Blue's planner is handed this round
    grab = {}
    if blue.planner is not None:
        orig_choose, orig_update = blue.planner.choose, blue.pf.update

        def choose(base, positions, root_allocs, depth=2):
            grab.update(base=base, positions=positions, root_allocs=root_allocs, depth=depth)
            return orig_choose(base, positions, root_allocs, depth)

        def update(*a, **k):
            grab["prior"] = np.bincount(blue.pf.particles, minlength=net.n) / blue.pf.n
            return orig_update(*a, **k)

        blue.planner.choose, blue.pf.update = choose, update

    prev_monitored = set(blue.last_monitored)
    red_obs = g.red_observation()
    blue_obs = g.blue_observation()
    red_act, blue_acts = m.decide()
    rd, bd = m.red_debug, m.blue_debug

    # ------------------------------------------------ Red
    w = red.weights
    late = max(0.0, red_obs.round - w["late_round"]) / max(1.0, 40 - w["late_round"])
    seen = [0, 0, 0]
    for info in red_obs.nodes.values():
        seen[info.zone] += 1
    red_out = {
        "observation": {
            "pos": net.label[red_obs.pos], "held": [net.label[u] for u in sorted(red_obs.held)],
            "known_nodes": len(red_obs.nodes), "events_last_round": [list(e[:1]) + [net.label[e[1]]] for e in red_obs.events],
            "legal": [act_str(net, a) for a in red_obs.legal],
            "neighbours": [{"node": net.label[v], "zone": C.ZONE_NAMES[red_obs.nodes[v].zone],
                            "weakness": red_obs.nodes[v].weakness,
                            "gate": frozenset((red_obs.pos, v)) in red_obs.gates,
                            "h": r3(heuristic(red_obs, v))}
                           for v in red_obs.edges.get(red_obs.pos, ())],
        },
        "model": {
            "zone_acts": red.model.zone_acts, "zone_caught": red.model.zone_caught,
            "p_monitor": [r3(red.model.p_monitor(z)) for z in range(3)],
            "sensitivity": [r3(red.model.sensitivity(z)) for z in range(3)],
            "recent_caught": r3(red.model.recent_caught), "p_hunt": r3(red.model.p_hunt()),
            "p_block": r3(red.model.p_block()), "fails": {net.label[u]: n for u, n in red.model.fails.items()},
        },
        "lambda": {"lam_base": r3(w["lam_base"]), "lam_caught": r3(w["lam_caught"]), "lam_late": r3(w["lam_late"]),
                   "recent_caught": r3(red.model.recent_caught), "late": r3(late), "value": r3(red.lam)},
        "astar": trace_astar(red_obs, red.model, red.lam, net),
        "route": [net.label[u] for u in rd["route"]], "route_cost": r3(rd["route_cost"]),
        "astar_next": act_str(net, rd["astar_next"]),
        "mcts": {
            "iterations": rd["iterations"], "samples_per_move": red.mcts.samples,
            "root": [{"action": act_str(net, a), "n": n, "mean": r3(v)} for a, n, v in rd["mcts"]],
            "tree": red_tree(net, red.mcts.root),
            "margin": r3(w["margin"]), "z": r3(w["z"]),
        },
        "chosen": act_str(net, red_act),
    }
    best = rd["mcts"][0][0] if rd["mcts"] else None
    if best is not None:
        gain, se = red.mcts.paired_gain(best, rd["astar_next"])
        red_out["mcts"]["test"] = {"best": act_str(net, best), "gain": r3(gain), "se": r3(se),
                                   "needs_gain_over": r3(w["margin"]), "needs_over_z_se": r3(w["z"] * se),
                                   "override": best != rd["astar_next"] and gain > w["margin"] and gain > w["z"] * se}

    # ------------------------------------------------ Blue
    bw = blue.weights
    belief = bd["belief"]
    order = list(np.argsort(-belief))
    lik = blue.pf.last_likelihood
    prior = grab.get("prior", belief)
    pf_rows = []
    for v in order[:6]:
        v = int(v)
        pf_rows.append({"node": net.label[v], "prior": r3(prior[v]), "likelihood": r3(lik[v]),
                        "posterior": r3(belief[v]), "held_prob": r3(blue.pf.held_prob[v]),
                        "truth": v == g.red_pos})
    fz_rows = []
    for v, t, lvl in bd["threat_top"][:3]:
        neigh = max([blue.alert_mem[v]] + [0.6 * blue.alert_mem[a] for a in net.adj[v]])
        conf = min(1.0, 3.0 * (belief[v] + 0.4 * sum(belief[a] for a in net.adj[v])))
        row = trace_fuzzy(blue.fuzzy, neigh, net.value[v], conf)
        row["node"] = net.label[v]
        assert abs(row["centroid"] - t) < 1e-3, (row["centroid"], t)
        fz_rows.append(row)
    mm_rows, mm_stats = trace_minimax(blue.planner, grab["base"], grab["positions"], grab["root_allocs"],
                                      grab["depth"], net)
    assert abs(mm_rows[0]["expected"] - bd["score"]) < 1e-3, (mm_rows[0]["expected"], bd["score"])
    best_alloc = [tuple(a) for a in mm_rows[0]["raw"]]
    parts = []
    for p_, _ in grab["positions"]:
        st = blue.planner.apply(grab["base"], best_alloc, p_)
        if st.hit:
            parts.append({"pos": net.label[p_], "hit": True,
                          "catch": r3(bw["catch"]), "path": r3(bw["path"])})
            continue
        parts.append({"pos": net.label[p_], "replies": [utility_parts(blue.planner, st, p_, r)
                                                       for r in blue.planner.replies(st, p_) if r[0] == "move"]})
    lik_rows = [trace_likelihood(blue.pf, net, blue_obs.alerts, prev_monitored, int(v)) for v in order[:3]]
    joint = prior * lik
    bayes = joint / joint.sum()
    for row in pf_rows:
        row["bayes"] = r3(bayes[net.label.index(row["node"])])
    blue_out = {
        "observation": {
            "alerts": [{"node": net.label[v], "strength": s} for v, s in blue_obs.alerts],
            "feedback": [{"action": k, "node": net.label[t], "found": f} for k, t, f in blue_obs.feedback],
            "isolate_ready_round": blue_obs.isolate_ready,
        },
        "filter": {"particles": blue.pf.n, "entropy_bits": r3(bd["entropy"]), "top": pf_rows},
        "fuzzy": {"thresholds": {"watch": r3(bw["watch"]), "act": r3(bw["act"])}, "nodes": fz_rows},
        "positions": [{"node": net.label[p], "prob": r3(bp)} for p, bp in grab["positions"]],
        "root_allocs": len(grab["root_allocs"]),
        "minimax": mm_rows,
        "utility_parts": parts,
        "likelihood_parts": lik_rows,
        "search": mm_stats,
        "weights": {k: r3(bw[k]) for k in ("path", "detect", "catch", "value", "decoy")},
        "chosen": alloc_str(net, blue_acts),
    }

    m.apply(red_act, blue_acts)
    rec = g.history[-1]
    outcome = {"red_result": rec.red_result, "events": rec.events,
               "alerts": [{"node": net.label[u], "strength": s, "real": real} for u, s, real in rec.alerts],
               "red_pos_after": net.label[g.red_pos]}
    history = [{"round": h.round, "red": act_str(net, h.red_action), "result": h.red_result,
                "blue": alloc_str(net, h.blue_actions), "alerts": len(h.alerts)} for h in g.history]
    return {"seed": seed, "round": rnd, "truth": truth, "history": history, "red": red_out, "blue": blue_out, "outcome": outcome}


def print_trace(t):
    R, B = t["red"], t["blue"]
    p = print
    p(f"== Map {t['seed']}, round {t['round']} ==")
    p(f"Truth (hidden from both): Red on {t['truth']['red_pos']}, holds {', '.join(t['truth']['red_held'])}; "
      f"decoys {t['truth']['decoys'] or 'none'}; patched {t['truth']['patched'] or 'none'}")
    p("\n-- RED --")
    o = R["observation"]
    p(f"Red stands on {o['pos']}, holds {', '.join(o['held'])}, knows {o['known_nodes']} nodes. "
      f"Last round: {o['events_last_round'] or 'nothing'}")
    for n in o["neighbours"]:
        p(f"  neighbour {n['node']:8s} {n['zone']:11s} weakness {n['weakness']}  gate {n['gate']}  h {n['h']}")
    md = R["model"]
    p(f"Opponent model: P(monitor) per zone {md['p_monitor']}, sensitivity {md['sensitivity']}, "
      f"recent_caught {md['recent_caught']}, failed tries {md['fails']}")
    L = R["lambda"]
    p(f"lambda = max(0.1, {L['lam_base']} + {L['lam_caught']} * min(1, {L['recent_caught']}) - {L['lam_late']} * {L['late']}) = {L['value']}")
    p("A* expansions:")
    for e in R["astar"]:
        if e.get("goal"):
            p(f"  pop {e['pop']}  g={e['g']}  -> goal reached")
            continue
        p(f"  pop {e['pop']}  g={e['g']} h={e['h']} f={e['f']}")
        for r in e["relax"]:
            p(f"     -> {r['to']:8s} w={r['est_weakness']} risk={r['risk']} step={r['step']} g={r['g_new']} "
              f"f={r['f_new']} {'(better)' if r['improves'] else ''}")
        if "fog_link" in e:
            p(f"     -> fog link cost {e['fog_link']['cost']}  g(goal)={e['fog_link']['g_goal']}")
    p(f"Route {' > '.join(R['route'])} (cost {R['route_cost']}); A* step: {R['astar_next']}")
    mc = R["mcts"]
    p(f"IS-MCTS: {mc['iterations']} iterations, {mc['samples_per_move']} paired samples per first move")
    for r in mc["root"]:
        p(f"  {r['action']:14s} n={r['n']} mean reward={r['mean']}")
    if "test" in mc:
        te = mc["test"]
        p(f"Paired test {te['best']} vs A*: gain {te['gain']} (se {te['se']}); needs > {te['needs_gain_over']} "
          f"and > {te['needs_over_z_se']} -> override {te['override']}")
    p(f"Red plays: {R['chosen']}")

    p("\n-- BLUE --")
    o = B["observation"]
    p(f"Alerts last round: {o['alerts'] or 'none'}; feedback {o['feedback'] or 'none'}")
    p(f"Particle filter ({B['filter']['particles']} particles, entropy {B['filter']['entropy_bits']} bits):")
    for r in B["filter"]["top"]:
        p(f"  {r['node']:8s} prior {r['prior']}  likelihood {r['likelihood']}  posterior {r['posterior']}"
          f"  P(held) {r['held_prob']}{'  <- Red is here' if r['truth'] else ''}")
    for f in B["fuzzy"]["nodes"]:
        p(f"Fuzzy {f['node']}: inputs {f['inputs']} -> {f['centroid']} ({f['level']})")
        for r in f["fired"]:
            p(f"   {r['rule']}  [{r['strength']}]")
    p(f"Positions searched: {B['positions']}; {B['root_allocs']} root allocations")
    for r in B["minimax"][:5]:
        p(f"  {r['alloc']:40s} E[value] = {r['expected']}   " +
          ", ".join(f"{x['pos']}:{x['value']}" for x in r["per_pos"]))
    s = B["search"]
    p(f"Leaf evaluations {s['evaluated_with_pruning']} with alpha-beta vs {s['evaluated_without']} without "
      f"({s['cutoffs']} cut-offs)")
    p(f"Blue plays: {B['chosen']}")
    p("\n-- WHAT HAPPENED --")
    oc = t["outcome"]
    p(f"Red's action: {oc['red_result']}; events: {oc['events']}; Red now on {oc['red_pos_after']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--round", type=int, default=5)
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args()
    t = run(a.seed, a.round)
    print_trace(t)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(t, f, indent=1)


if __name__ == "__main__":
    main()
