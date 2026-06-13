from __future__ import annotations

from pathlib import Path

from metriplane.assistant import retrieval
from metriplane.assistant.intents import classify, supported_questions
from metriplane.assistant.models import AssistantAnswer, AssistantQuery


def answer_question(question: str, run_dir: str | Path) -> AssistantAnswer:
    intent = classify(question)
    q = AssistantQuery(question=question, run_dir=str(run_dir), intent=intent)
    handler = _HANDLERS.get(intent, _unknown)
    return handler(q, Path(run_dir))


def _incident_search(q, run) -> AssistantAnswer:
    incidents, cites, lims = retrieval.retrieve_incidents(run)
    if not incidents:
        return AssistantAnswer(
            question=q.question, intent=q.intent,
            answer="No incidents were found for this run.",
            citations=cites, confidence=0.6 if not lims else 0.2, limitations=lims)
    parts = [f"{len(incidents)} incident(s) found."]
    for inc in incidents:
        dur = inc.get("duration_s")
        parts.append(
            f"- {inc.get('incident_id')}: rule {inc.get('rule_id')} "
            f"({inc.get('severity')}), objects {', '.join(inc.get('object_ids', []))}, "
            f"duration {dur}s.")
    return AssistantAnswer(question=q.question, intent=q.intent,
                           answer="\n".join(parts), citations=cites,
                           confidence=0.9, limitations=lims)


def _object_history(q, run) -> AssistantAnswer:
    known = retrieval.known_object_ids(run)
    target = next((oid for oid in known if oid.lower() in q.question.lower()), None)
    if target is None:
        return AssistantAnswer(
            question=q.question, intent=q.intent,
            answer="Specify an object. Known objects: " + (", ".join(known) or "none"),
            confidence=0.3,
            limitations=["no object id matched in the question"])
    rows, cites, lims = retrieval.retrieve_traces(run, object_id=target)
    if not rows:
        return AssistantAnswer(question=q.question, intent=q.intent,
                               answer=f"No trace found for {target}.",
                               citations=cites, confidence=0.3, limitations=lims)
    r = rows[0]
    ans = (f"{target} was tracked for {r['duration_s']}s, traveling "
           f"{r['total_distance_m']} m across zones "
           f"{', '.join(r['zones_visited']) or '—'} (gaps: {r['gap_count']}).")
    return AssistantAnswer(question=q.question, intent=q.intent, answer=ans,
                           citations=cites, confidence=0.85, limitations=lims)


def _zone_occupancy(q, run) -> AssistantAnswer:
    incidents, inc_cites, inc_lims = retrieval.retrieve_incidents(run)
    rows, tr_cites, tr_lims = retrieval.retrieve_traces(run)
    zone_incidents = [i for i in incidents if i.get("zones")]
    parts = []
    if zone_incidents:
        for i in zone_incidents:
            parts.append(
                f"Zone {', '.join(i.get('zones', []))} had incident "
                f"{i.get('incident_id')} ({i.get('rule_id')}) lasting "
                f"{i.get('duration_s')}s, involving "
                f"{', '.join(i.get('object_ids', []))}.")
    dwell_facts = []
    for r in rows:
        for zone, secs in (r.get("dwell_by_zone") or {}).items():
            dwell_facts.append(f"{r['object_id']} dwelled {secs}s in {zone}")
    if dwell_facts:
        parts.append("Dwell: " + "; ".join(dwell_facts) + ".")
    if not parts:
        parts.append("No zone occupancy incidents or dwell records found.")
    return AssistantAnswer(question=q.question, intent=q.intent,
                           answer="\n".join(parts),
                           citations=inc_cites + tr_cites,
                           confidence=0.8 if zone_incidents else 0.5,
                           limitations=inc_lims + tr_lims)


def _rule_explanation(q, run) -> AssistantAnswer:
    # prefer a rule id named in the question; else use the incident's rule
    rules_obj, _, _ = retrieval.retrieve_rule(run, None)
    candidates = (rules_obj or {}).get("rules", []) if rules_obj else []
    target = next((rid for rid in candidates if rid and rid.lower() in q.question.lower()),
                  None)
    if target is None:
        incidents, _, _ = retrieval.retrieve_incidents(run)
        if incidents:
            target = incidents[0].get("rule_id")
    rule, cites, lims = retrieval.retrieve_rule(run, target)
    if rule is None:
        return AssistantAnswer(
            question=q.question, intent=q.intent,
            answer=f"Could not find rule '{target}'. Known rules: "
                   + (", ".join(candidates) or "none"),
            citations=cites, confidence=0.3, limitations=lims)
    ans = (f"Rule {rule.get('id')} is a {rule.get('type')} rule "
           f"(severity {rule.get('severity', 'warning')}).")
    if rule.get("zone"):
        ans += f" Zone: {rule['zone']}."
    if rule.get("min_distance_m") is not None:
        ans += f" Minimum distance: {rule['min_distance_m']} m."
    if rule.get("max_duration_s") is not None:
        ans += f" Max dwell: {rule['max_duration_s']} s."
    return AssistantAnswer(question=q.question, intent=q.intent, answer=ans,
                           citations=cites, confidence=0.85, limitations=lims)


def _camera_health(q, run) -> AssistantAnswer:
    report, cites, lims = retrieval.retrieve_camera_trust(run)
    if report is None:
        return AssistantAnswer(
            question=q.question, intent=q.intent,
            answer="No camera trust data is available for this run.",
            citations=cites, confidence=0.2, limitations=lims)
    scores = report.get("camera_scores", {})
    bad = [cid for cid, s in scores.items() if s.get("status") != "OK"]
    if bad:
        details = "; ".join(
            f"{cid} is {scores[cid]['status']} (score {scores[cid]['score']}, "
            f"dropout {scores[cid].get('dropout_rate')})" for cid in bad)
        ans = f"Unreliable camera(s): {details}."
    else:
        ans = "All cameras are OK."
    if report.get("recommendations"):
        ans += " Recommendations: " + " ".join(report["recommendations"])
    return AssistantAnswer(question=q.question, intent=q.intent, answer=ans,
                           citations=cites, confidence=0.85, limitations=lims)


def _unknown(q, run) -> AssistantAnswer:
    return AssistantAnswer(
        question=q.question, intent="unknown",
        answer="I can answer these question types:\n- "
               + "\n- ".join(supported_questions()),
        confidence=0.0,
        limitations=["question intent not recognized"])


_HANDLERS = {
    "incident_search": _incident_search,
    "object_history": _object_history,
    "zone_occupancy": _zone_occupancy,
    "rule_explanation": _rule_explanation,
    "camera_health": _camera_health,
}
