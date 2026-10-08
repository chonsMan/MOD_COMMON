#######################################################################################################################
# Title:   network.py
# Author:  Jesse Harris
# Version: v1 (shared)
# Purpose: Find the tie-lines between the POC and the slack bus (Vreg Step sets them to R/X/B from the form)
# Notes:   Simulator-free (shared by the PSLF and PSS(R)E Test Runners): each app reads its in-service lines (no
#          transformers) and changes the ones returned here. Plan: MOD_PSLF\06_MARKDOWN\Grid_Playback_Plan.md.
#######################################################################################################################
from collections import deque


def _hops(adj, start):
    dist, todo = {start: 0}, deque([start])
    while todo:
        bus = todo.popleft()
        for nxt in adj.get(bus, ()):
            if nxt not in dist:
                dist[nxt] = dist[bus] + 1
                todo.append(nxt)
    return dist


def tie_lines(lines, poc_bus, slack_bus):
    """Lines on the shortest route(s) from poc_bus to slack_bus, every parallel circuit included.

    lines = [(from_bus, to_bus, ck), ...], in-service lines only. Returns the matching items of `lines`.
    Raises ValueError if the slack can't be reached from the POC through lines alone.
    """
    if poc_bus == slack_bus:
        raise ValueError(f"the POC bus {poc_bus} is the slack bus; there is no tie-line to change")
    adj = {}
    for i, j, _ in lines:
        adj.setdefault(i, set()).add(j)
        adj.setdefault(j, set()).add(i)
    from_poc, from_slack = _hops(adj, poc_bus), _hops(adj, slack_bus)
    if slack_bus not in from_poc:
        raise ValueError(f"the slack bus {slack_bus} can't be reached from the POC bus {poc_bus} through lines alone "
                         f"(a transformer or open branch is in the way)")
    n = from_poc[slack_bus]

    def on_route(a, b):
        return a in from_poc and b in from_slack and from_poc[a] + 1 + from_slack[b] == n

    return [ln for ln in lines if on_route(ln[0], ln[1]) or on_route(ln[1], ln[0])]
