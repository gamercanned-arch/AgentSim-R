from __future__ import annotations

import random
from typing import Dict, List, Optional

# Scenario pools for work/study.
# Each scenario has: id, pick (prop), obj (target), q, choices{A,B,C}, ans


def _mk_mcq(q: str, a: str, b: str, c: str, ans: str) -> Dict:
    ans = str(ans).strip().upper()
    if ans not in ("A", "B", "C"):
        ans = "B"
    return {"q": q, "choices": {"A": a, "B": b, "C": c}, "ans": ans}


def _scenario(role: str, idx: int, pick: str, obj: str, mcq: Dict) -> Dict:
    return {
        "id": f"{role}_{idx:02d}",
        "pick": pick,
        "obj": obj,
        "q": mcq["q"],
        "choices": mcq["choices"],
        "ans": mcq["ans"],
    }


def _expand_to_30(base: List[Dict], templates: List[tuple], role: str, pick: str, obj: str) -> List[Dict]:
    mcqs = base[:]
    # Deterministic-ish expansion; occasional non-B answers to prevent farming.
    while len(mcqs) < 30:
        t = templates[(len(mcqs) - len(base)) % len(templates)]
        # occasional different correct answer
        if len(mcqs) % 9 == 0:
            mcqs.append(_mk_mcq(t[0], "Collect evidence and mitigate safely.", "Panic and change random things.", "Ignore it.", "A"))
        else:
            mcqs.append(_mk_mcq(*t))
    return [_scenario(role, i + 1, pick, obj, mcqs[i]) for i in range(30)]


def build_scenario_pools() -> Dict[str, List[Dict]]:
    pools: Dict[str, List[Dict]] = {}

    # Nurse/Doctor
    pools["nurse"] = _expand_to_30(
        base=[
            _mk_mcq(
                "Patient BP is 180/120 with headache. What do you do first?",
                "Ignore and chart later.",
                "Assess and escalate; follow hypertensive emergency protocol.",
                "Give them coffee for alertness.",
                "B",
            ),
            _mk_mcq(
                "Medication label is unclear. What is safest?",
                "Guess based on color.",
                "Hold and verify with pharmacy/doctor.",
                "Double the dose to be safe.",
                "B",
            ),
            _mk_mcq(
                "Patient complains of chest pain. First step?",
                "Tell them it’s anxiety; send them home.",
                "Assess ABCs/vitals; alert physician; initiate chest pain protocol.",
                "Give spicy food to distract.",
                "B",
            ),
            _mk_mcq(
                "Possible allergic reaction (hives, swelling).",
                "Wait and see for 2 hours.",
                "Stop exposure; escalate; prepare emergency response.",
                "Offer a sandwich only.",
                "B",
            ),
            _mk_mcq(
                "IV line is infiltrated.",
                "Keep running fluids to push through.",
                "Stop infusion and re-site IV per protocol.",
                "Tape it harder and ignore swelling.",
                "B",
            ),
        ],
        templates=[
            (
                "Patient has fever 39.5C and chills.",
                "Give antibiotics without assessment.",
                "Assess, check history, and follow fever protocol; consider sepsis.",
                "Send them to gym to sweat it out.",
                "B",
            ),
            (
                "Patient feels dizzy after standing.",
                "Ask them to sprint to restore circulation.",
                "Have them sit/lie down; check vitals and hydration.",
                "Discharge immediately.",
                "B",
            ),
            (
                "You’re behind schedule and feel rushed.",
                "Skip hand hygiene to save time.",
                "Maintain safety steps; hand hygiene and correct checks.",
                "Let a random visitor do vitals.",
                "B",
            ),
            (
                "Patient is anxious before MRI.",
                "Yell at them to calm down.",
                "Explain procedure; offer coping steps; notify staff if meds needed.",
                "Lie and say it’s painless and instant.",
                "B",
            ),
        ],
        role="nurse",
        pick="Stethoscope",
        obj="Patient",
    )

    # Teacher/Tutor
    pools["teacher"] = _expand_to_30(
        base=[
            _mk_mcq(
                "A student struggles with fractions. Best response?",
                "Ignore them.",
                "Explain visually and check understanding.",
                "Give detention.",
                "B",
            ),
            _mk_mcq(
                "Class is noisy during instruction. Best first step?",
                "Throw items to get attention.",
                "Use calm classroom management and reset expectations.",
                "Leave class and lock the door.",
                "B",
            ),
            _mk_mcq(
                "A student submits suspiciously perfect work.",
                "Accuse them publicly.",
                "Ask privately about process; verify understanding fairly.",
                "Automatically give zero.",
                "B",
            ),
        ],
        templates=[
            (
                "A parent emails angry about grades.",
                "Insult them back.",
                "Respond professionally; explain rubric and offer meeting.",
                "Ignore forever.",
                "B",
            ),
            (
                "Two students argue loudly.",
                "Escalate by yelling.",
                "De-escalate and separate; address later with clear steps.",
                "Record and post online.",
                "B",
            ),
            (
                "Student appears disengaged and tired.",
                "Punish immediately.",
                "Check in; adapt approach; consider support resources.",
                "Force them to stand the entire class.",
                "B",
            ),
        ],
        role="teacher",
        pick="Marker",
        obj="Student",
    )

    # Delivery/Driver/FedEx
    # We vary correct answers more often than other roles to reduce farming.
    delivery_templates = [
        (
            "Label is torn. What’s correct?",
            "Guess address and deliver anyway.",
            "Return to depot for relabeling.",
            "Throw it away.",
            "B",
        ),
        (
            "Customer not home; signature required.",
            "Leave package in road.",
            "Follow protocol: attempt contact and reschedule/hold.",
            "Forge signature.",
            "B",
        ),
        (
            "Package seems damaged.",
            "Hide damage and deliver.",
            "Report damage; follow handling policy.",
            "Kick it to test.",
            "B",
        ),
        (
            "Route seems inefficient mid-shift.",
            "Ignore and take random turns.",
            "Batch nearby deliveries; follow route optimization.",
            "Deliver only to friends.",
            "B",
        ),
    ]

    mcqs = []
    for i in range(30):
        t = delivery_templates[i % len(delivery_templates)]
        if i % 6 == 0:
            mcqs.append(
                _mk_mcq(
                    t[0],
                    "Ignore it and mark delivered.",
                    "Guess and hope it works out.",
                    "Report and follow protocol; return/hold as required.",
                    "C",
                )
            )
        else:
            mcqs.append(_mk_mcq(*t))

    pools["delivery"] = [_scenario("delivery", i + 1, "Scanner", "Package", mcqs[i]) for i in range(30)]

    # Developer/Startup/Founder
    pools["developer"] = _expand_to_30(
        base=[
            _mk_mcq(
                "Prod incident: memory spike. Best response?",
                "Restart blindly with no data.",
                "Triage: inspect metrics/logs, mitigate, then fix root cause.",
                "Delete the database to reduce memory.",
                "B",
            ),
            _mk_mcq(
                "Client requests 10 new features today.",
                "Agree blindly.",
                "Negotiate scope and timeline; document tradeoffs.",
                "Block the client.",
                "B",
            ),
            _mk_mcq(
                "Build is failing on CI.",
                "Disable tests forever.",
                "Reproduce; isolate failing test; fix deterministically.",
                "Ship anyway without build.",
                "B",
            ),
            _mk_mcq(
                "Security report: possible credential leak.",
                "Ignore it.",
                "Rotate secrets; audit logs; patch exposure.",
                "Post secrets publicly to crowdsource.",
                "B",
            ),
        ],
        templates=[
            (
                "A teammate proposes a risky hotfix to production.",
                "Approve without review.",
                "Request minimal safe change + rollback plan; validate.",
                "Argue for hours without deciding.",
                "B",
            ),
            (
                "You discover tech debt slowing development.",
                "Pretend it doesn't exist.",
                "Schedule refactor time and reduce future risk incrementally.",
                "Rewrite everything overnight.",
                "B",
            ),
            (
                "An alert is firing intermittently.",
                "Disable alerting.",
                "Investigate thresholds, noise, and actual incidents; tune responsibly.",
                "Ignore until outage.",
                "B",
            ),
        ],
        role="developer",
        pick="Laptop",
        obj="Task Board",
    )

    # Education
    edu_mcqs = []
    edu_templates = [
        ("What is the powerhouse of the cell?", "Nucleus", "Mitochondria", "Ribosome", "B"),
        ("2 + 2 * 2 = ?", "6", "8", "4", "A"),
        ("Best way to retain information?", "Cram without sleep.", "Spaced repetition and practice.", "Never review.", "B"),
        ("Which is a primary emotion?", "Jealousy", "Happiness", "Nostalgia", "B"),
        ("What helps reduce anxiety long-term?", "Avoid everything forever.", "Gradual exposure + coping skills.", "Never sleep.", "B"),
    ]
    for i in range(30):
        t = edu_templates[i % len(edu_templates)]
        edu_mcqs.append(_mk_mcq(*t))
    pools["education"] = [_scenario("education", i + 1, "Notebook", "Exam", edu_mcqs[i]) for i in range(30)]

    # Generic fallback
    pools["generic"] = pools["education"][:]
    return pools


SCENARIO_POOLS: Dict[str, List[Dict]] = build_scenario_pools()


def pool_key_for_job(job_raw: str, mode: str) -> str:
    if mode == "get_education":
        return "education"
    lowered = (job_raw or "").lower()
    if "nurse" in lowered or "doctor" in lowered:
        return "nurse"
    if "teacher" in lowered or "tutor" in lowered:
        return "teacher"
    if "delivery" in lowered or "driver" in lowered or "fedex" in lowered:
        return "delivery"
    if any(k in lowered for k in ("developer", "tech", "startup", "founder")):
        return "developer"
    return "generic"


def pick_scenario(agent, pool_key: str, avoid_last: int = 5) -> Dict:
    """
    agent is expected to have recent_scenarios: Dict[str, List[str]]
    """
    pool = SCENARIO_POOLS.get(pool_key) or SCENARIO_POOLS["generic"]
    recent = list(getattr(agent, "recent_scenarios", {}).get(pool_key, []))

    avoid = set(recent[-avoid_last:]) if avoid_last > 0 else set()
    candidates = [s for s in pool if s["id"] not in avoid] or pool[:]
    chosen = random.choice(candidates)

    # update recency
    if not hasattr(agent, "recent_scenarios") or agent.recent_scenarios is None:
        agent.recent_scenarios = {}
    recent.append(chosen["id"])
    agent.recent_scenarios[pool_key] = recent[-20:]

    return chosen