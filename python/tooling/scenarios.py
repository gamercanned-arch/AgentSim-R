from __future__ import annotations

import random
from typing import Dict, List


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


def _pool(role: str, pick: str, obj: str, tuples: List[tuple]) -> List[Dict]:
    mcqs = [_mk_mcq(*t) for t in tuples]
    if len(mcqs) < 30:
        raise ValueError(f"Scenario pool '{role}' must contain at least 30 unique scenarios.")
    return [_scenario(role, i + 1, pick, obj, mcqs[i]) for i in range(len(mcqs))]


def build_scenario_pools() -> Dict[str, List[Dict]]:
    pools: Dict[str, List[Dict]] = {}

    nurse_items = [
        ("Patient BP is 180/120 with headache. What do you do first?", "Ignore and chart later.", "Assess and escalate; follow hypertensive emergency protocol.", "Give coffee for alertness.", "B"),
        ("Medication label is unclear. What is safest?", "Guess based on color.", "Hold and verify with pharmacy or doctor.", "Double the dose to be safe.", "B"),
        ("Patient reports sudden chest pain. First step?", "Assume it is anxiety and delay.", "Assess ABCs and vitals, alert physician, begin chest pain protocol.", "Give spicy food to distract them.", "B"),
        ("Possible allergic reaction with swelling and hives appears. Best response?", "Wait two hours and observe casually.", "Stop exposure, escalate, and prepare emergency response.", "Offer a sandwich only.", "B"),
        ("An IV line is infiltrated. What should you do?", "Keep fluids running to push through.", "Stop the infusion and re-site per protocol.", "Tape it harder and ignore swelling.", "B"),
        ("A patient with fever 39.5C has chills and confusion. Best response?", "Hand them a blanket and leave.", "Assess promptly, check sepsis risk, and follow protocol.", "Tell them to sleep it off with no follow-up.", "B"),
        ("A patient feels dizzy after standing. What is the safest first action?", "Tell them to jog in place.", "Help them sit or lie down and check vitals and hydration.", "Discharge them immediately.", "B"),
        ("You are behind schedule and rushed. Which action is correct?", "Skip hand hygiene to save time.", "Maintain safety checks and hand hygiene.", "Let a visitor take the vitals instead.", "B"),
        ("A patient is anxious before MRI. Best nursing response?", "Yell at them to calm down.", "Explain the procedure and offer coping support.", "Lie and say it is always easy.", "B"),
        ("A diabetic patient is shaky and sweating. First priority?", "Wait for lunch service.", "Check blood sugar and follow hypoglycemia protocol.", "Send them to walk it off.", "B"),
        ("A post-op patient reports severe new pain. Best action?", "Tell them pain is normal and leave.", "Assess pain, vitals, and notify the appropriate provider.", "Increase medication without orders.", "B"),
        ("A patient tries to get out of bed and is unstable. Best response?", "Ignore them unless they fall.", "Assist safely and use fall precautions.", "Tell them to be more careful.", "B"),
        ("You notice a mismatch between wristband and chart. What next?", "Assume the chart is right.", "Stop and verify identity before proceeding.", "Ask another patient if the name seems correct.", "B"),
        ("Oxygen saturation drops to 84%. What is most appropriate?", "Document it for later.", "Assess airway and breathing and escalate immediately.", "Turn off the monitor alarm only.", "B"),
        ("A patient says they do not understand discharge meds. Best move?", "Rush through to save time.", "Explain clearly and confirm understanding.", "Tell them to search online later.", "B"),
        ("A wound dressing is soaked through unexpectedly. What do you do?", "Leave it until rounds.", "Assess the wound and bleeding, then escalate as needed.", "Place another blanket over it.", "B"),
        ("A confused patient pulls at lines repeatedly. Safest approach?", "Scold them loudly.", "Reorient, secure safety, and seek team support.", "Tie things down without documentation.", "B"),
        ("A family member demands protected medical info without clearance. Best action?", "Share it to calm them down.", "Follow privacy rules and verify authorization.", "Read the whole chart aloud.", "B"),
        ("A patient complains of shortness of breath after medication. Best response?", "Assume it will pass.", "Assess immediately for adverse reaction and escalate.", "Offer dessert first.", "B"),
        ("You find an empty narcotic count slot. What is correct?", "Ignore it because shift is busy.", "Report discrepancy and follow controlled-substance procedure.", "Replace it with a guess.", "B"),
        ("A patient refuses a procedure. Best nursing action?", "Force compliance for efficiency.", "Respect refusal, assess understanding, and notify provider.", "Mark it completed anyway.", "B"),
        ("Urine output has fallen sharply over several hours. Best response?", "Do nothing until tomorrow.", "Assess intake/output and notify appropriate staff.", "Tell the patient to drink soda only.", "B"),
        ("A patient with stroke signs arrives. Best first move?", "Send them to the waiting room.", "Activate urgent stroke response and assess rapidly.", "Ask them to return later.", "B"),
        ("An elderly patient has new confusion at night. Best step?", "Dismiss it as normal aging.", "Assess for delirium, meds, infection, and safety risks.", "Turn off the lights and leave.", "B"),
        ("A patient says they cannot afford medication after discharge. Best response?", "Say that is not your problem.", "Notify the team and connect support resources.", "Advise them to stop all meds.", "B"),
        ("You see a visitor collapse in the hallway. Best response?", "Wait for someone else.", "Assess responsiveness and start emergency response protocol.", "Drag them outside quietly.", "B"),
        ("A patient’s potassium result is critically high. Best action?", "File it for the next shift.", "Escalate promptly because it may be life-threatening.", "Offer a banana immediately.", "B"),
        ("A patient reports suicidal thoughts. Best response?", "Assume they are exaggerating.", "Take it seriously, ensure safety, and escalate immediately.", "Tell them to stay positive.", "B"),
        ("You accidentally contaminate a sterile field. Correct action?", "Continue quickly before anyone notices.", "Stop and re-establish sterility.", "Ask the patient not to mention it.", "B"),
        ("A child patient is crying and frightened before a procedure. Best approach?", "Use threats to gain compliance.", "Use calm reassurance and age-appropriate explanation.", "Leave without any explanation.", "B"),
    ]
    pools["nurse"] = _pool("nurse", "Stethoscope", "Patient", nurse_items)

    teacher_items = [
        ("A student struggles with fractions. Best response?", "Ignore them.", "Explain visually and check understanding.", "Give detention immediately.", "B"),
        ("The class is noisy during instruction. Best first step?", "Throw something for attention.", "Use calm classroom management and reset expectations.", "Walk out and lock the door.", "B"),
        ("A student submits suspiciously perfect homework. Best response?", "Accuse them publicly.", "Ask privately about their process and verify understanding fairly.", "Give zero without discussion.", "B"),
        ("A parent emails angrily about grades. Best move?", "Insult them back.", "Respond professionally, explain the rubric, and offer a meeting.", "Ignore them forever.", "B"),
        ("Two students argue loudly mid-lesson. Best action?", "Escalate by shouting louder.", "De-escalate, separate them, and address it safely.", "Record them and post it online.", "B"),
        ("A student seems disengaged and exhausted. Best response?", "Punish immediately.", "Check in and consider support or adjustment.", "Force them to stand all class.", "B"),
        ("A student gives a clearly wrong answer in front of peers. Best response?", "Humiliate them so they remember.", "Correct respectfully and keep them engaged.", "Tell them never to answer again.", "B"),
        ("A class finishes early. Best use of time?", "Let chaos take over.", "Use a meaningful review or extension activity.", "Dismiss everyone randomly.", "B"),
        ("A student repeatedly arrives without supplies. Best response?", "Publicly shame them.", "Address the issue privately and support problem-solving.", "Bar them from class indefinitely.", "B"),
        ("A student with anxiety asks for a brief pause. Best action?", "Tell them to stop being dramatic.", "Respond calmly within policy and support regulation.", "Send them home without record.", "B"),
        ("A student dominates every discussion. Best teaching move?", "Let it continue every time.", "Balance participation so others can contribute.", "Ban them from speaking all week.", "B"),
        ("A group project has one student doing all the work. Best response?", "Ignore the imbalance.", "Reassess roles and hold students individually accountable.", "Cancel grades for everyone.", "B"),
        ("A student appears to be bullied by peers. Best action?", "Say it builds character.", "Intervene appropriately and follow safeguarding policy.", "Tell them to handle it alone.", "B"),
        ("A test question turns out ambiguous. Best response?", "Pretend nothing happened.", "Review it fairly and adjust scoring if needed.", "Blame the class.", "B"),
        ("A student asks why the topic matters. Best teaching move?", "Say because you said so.", "Connect it to real-life relevance.", "Tell them curiosity is disrespectful.", "B"),
        ("A parent requests extra support for a child falling behind. Best response?", "Say there is no time.", "Collaborate on realistic support steps.", "Promise impossible results overnight.", "B"),
        ("A student keeps using their phone during class. Best first step?", "Throw the phone away.", "Apply classroom policy consistently and calmly.", "Ignore it every time.", "B"),
        ("A student with a language barrier is confused. Best response?", "Call them lazy.", "Use scaffolds and clearer supports.", "Skip them and move on forever.", "B"),
        ("The lesson is clearly too easy for half the class. Best action?", "Repeat the same worksheet silently.", "Differentiate with extension or challenge tasks.", "Punish advanced students with extra busywork.", "B"),
        ("The lesson is too hard for many students. Best response?", "Say they should already know it.", "Reteach and break the concept down.", "Continue at the same pace no matter what.", "B"),
        ("A student makes a thoughtful but controversial comment. Best move?", "Shut them down instantly.", "Guide respectful discussion and maintain boundaries.", "Encourage personal attacks.", "B"),
        ("A student is absent often and falling behind. Best action?", "Lower expectations and ignore them.", "Reach out and make a catch-up plan.", "Remove them from grading entirely.", "B"),
        ("A student cries after receiving a poor grade. Best response?", "Tell them failure is permanent.", "Acknowledge feelings and discuss improvement steps.", "Read the grade aloud to the class again.", "B"),
        ("A fire drill interrupts testing. Best action?", "Keep testing through the alarm.", "Follow safety procedures first.", "Let students wander off unsupervised.", "B"),
        ("A student asks for feedback on an essay draft. Best response?", "Refuse because grading is later.", "Give constructive, actionable feedback.", "Rewrite it for them completely.", "B"),
        ("Students are memorizing but not understanding. Best adjustment?", "Assign more memorization only.", "Use examples, questioning, and application.", "Make the test harder without teaching differently.", "B"),
        ("One student mocks another’s answer. Best response?", "Laugh along to fit in.", "Address respect immediately and protect classroom climate.", "Tell the mocked student to toughen up.", "B"),
        ("A substitute reported poor behavior yesterday. Best action today?", "Start angry and threatening.", "Reset expectations clearly and calmly.", "Pretend nothing happened and hope.", "B"),
        ("A student asks for help right before the bell. Best response?", "Say time is up, too bad.", "Offer a quick step and a follow-up plan.", "Mark them absent for asking late.", "B"),
        ("A lesson objective is not being met halfway through class. Best move?", "Push ahead regardless.", "Adjust in real time and reteach what matters most.", "Blame the students and stop teaching.", "B"),
    ]
    pools["teacher"] = _pool("teacher", "Marker", "Student", teacher_items)

    delivery_items = [
        ("A package label is torn. What is correct?", "Guess the address and deliver anyway.", "Return to depot for relabeling.", "Throw it away.", "B"),
        ("Customer not home and signature is required. Best action?", "Leave it in the road.", "Follow protocol: attempt contact and reschedule or hold.", "Forge the signature.", "B"),
        ("A package seems damaged before delivery. Best response?", "Hide the damage and deliver it.", "Report damage and follow handling policy.", "Kick it to test durability.", "B"),
        ("Your route becomes inefficient mid-shift. Best move?", "Ignore it and take random turns.", "Re-optimize stops responsibly and follow route policy.", "Deliver only to friends first.", "B"),
        ("A customer asks you to leave a signature-required package with a neighbor. Best action?", "Do it without checking any policy.", "Follow delivery policy and authorization rules.", "Leave it on the roof instead.", "B"),
        ("Scanner battery is low with many stops left. Best response?", "Hope it lasts and stop scanning.", "Get a proper charge or replacement per procedure.", "Invent deliveries from memory later.", "B"),
        ("Traffic causes a major delay. Best response?", "Mark stops delivered before arrival.", "Update status honestly and continue safely.", "Speed dangerously through side roads.", "B"),
        ("A package belongs on a refrigerated route but is on your normal truck. Best move?", "Deliver it anyway and hope.", "Report the handling issue immediately.", "Leave it in the sun at the depot.", "B"),
        ("A dog is loose at the delivery address. Best action?", "Approach anyway and risk a bite.", "Prioritize safety and follow unsafe-location policy.", "Throw the package over the fence blindly.", "B"),
        ("A customer claims a package was never received but tracking says delivered. Best response?", "Accuse them of lying.", "Follow missing-package protocol and document facts.", "Delete the delivery record.", "B"),
        ("You discover the wrong package in your hand at the door. Best action?", "Hand it over anyway to save time.", "Correct the mistake before completing delivery.", "Ask the customer to sort it out.", "B"),
        ("Weather becomes severe during route. Best response?", "Ignore safety and continue recklessly.", "Adjust safely and follow severe-weather policy.", "Abandon the truck unlocked.", "B"),
        ("A box is marked fragile. Best handling?", "Stack heavy parcels on top.", "Handle and position it carefully.", "Toss it to save time.", "B"),
        ("A customer asks you to change the address verbally. Best response?", "Change it without verification.", "Follow official reroute procedure only.", "Write it on the box and guess.", "B"),
        ("The scanner shows a mismatch between stop and parcel. Best action?", "Override it randomly.", "Pause and verify before delivery.", "Deliver both to the same place.", "B"),
        ("A package leaks unknown liquid. Best response?", "Wipe it and continue.", "Isolate it and report a hazardous issue.", "Sniff it to identify the contents.", "B"),
        ("You are missing one parcel after loading. Best action?", "Pretend it was loaded.", "Report and reconcile before falsifying anything.", "Mark it delivered early.", "B"),
        ("A customer becomes verbally aggressive at the door. Best response?", "Argue back aggressively.", "Stay professional, stay safe, and follow escalation policy.", "Threaten to blacklist them personally.", "B"),
        ("The loading dock is crowded and unsafe. Best move?", "Rush through and hope.", "Use safe loading and movement procedures.", "Push through people with the cart.", "B"),
        ("A stop requires ID verification. Best response?", "Skip the check if they seem honest.", "Verify ID properly before release.", "Leave the parcel and text them later.", "B"),
        ("A package is too large for the porch and rain is starting. Best move?", "Leave it outside in the rain.", "Follow safe placement or failed-delivery policy.", "Hide it in the street bushes.", "B"),
        ("Another driver asks you to scan their deliveries under your route. Best response?", "Do it as a favor.", "Refuse and follow accountability rules.", "Scan them all as damaged.", "B"),
        ("Your truck fuel is critically low during route. Best action?", "Ignore the warning light completely.", "Refuel according to route procedure.", "Keep driving until it stops.", "B"),
        ("A customer asks where a delayed parcel is and you do not know. Best response?", "Make up an answer.", "Give accurate status and direct them appropriately.", "Blame another driver by name.", "B"),
        ("You notice a parcel addressed to the same building but wrong apartment. Best action?", "Leave it in the lobby for anyone.", "Deliver only to the verified destination.", "Give it to the first resident you see.", "B"),
        ("A return package lacks one barcode. Best response?", "Guess which code to use.", "Follow return exception procedure.", "Throw away the label and continue.", "B"),
        ("A parcel falls from the cart during loading. Best action?", "Ignore the fall and continue.", "Inspect it and report if needed.", "Kick it back onto the cart.", "B"),
        ("A stop is marked unsafe after dark. Best response?", "Go anyway without caution.", "Follow the unsafe-stop protocol.", "Leave the entire truck unattended nearby.", "B"),
        ("The app crashes mid-route. Best action?", "Invent stop completions later.", "Use approved fallback procedure and report the issue.", "Call every customer from your personal phone randomly.", "B"),
        ("A parcel requires cold-chain compliance and the timer is almost up. Best move?", "Delay it for easier stops first.", "Prioritize according to handling requirements.", "Set it aside and hope.", "B"),
    ]
    pools["delivery"] = _pool("delivery", "Scanner", "Package", delivery_items)

    developer_items = [
        ("Production memory usage spikes sharply. Best response?", "Restart blindly with no data.", "Inspect metrics and logs, mitigate, then fix root cause.", "Delete the database to save memory.", "B"),
        ("A client wants ten new features today. Best response?", "Agree blindly to everything.", "Negotiate scope and timeline and document tradeoffs.", "Block the client permanently.", "B"),
        ("CI build is failing. Best move?", "Disable tests forever.", "Reproduce, isolate the failure, and fix it deterministically.", "Ship without a build.", "B"),
        ("A possible credential leak is reported. Best response?", "Ignore it and hope.", "Rotate secrets, audit logs, and patch exposure.", "Post the secrets publicly to crowdsource help.", "B"),
        ("A teammate proposes a risky hotfix to production. Best action?", "Approve it without review.", "Require the smallest safe change and a rollback plan.", "Debate forever without deciding.", "B"),
        ("Tech debt is slowing the team. Best response?", "Pretend it does not exist.", "Schedule incremental refactoring to reduce risk.", "Rewrite everything overnight.", "B"),
        ("An alert fires intermittently. Best response?", "Disable alerting altogether.", "Investigate whether it is noise or a real incident and tune responsibly.", "Ignore it until there is an outage.", "B"),
        ("A database migration may lock a busy table. Best action?", "Run it at peak traffic with no plan.", "Assess risk, plan rollout, and reduce impact safely.", "Drop the table and rebuild later.", "B"),
        ("A bug report lacks reproduction steps. Best response?", "Close it instantly.", "Gather details and reproduce before changing code.", "Guess a random fix and merge it.", "B"),
        ("Latency doubles after a deploy. Best response?", "Assume users will adapt.", "Compare before and after metrics and narrow the regression.", "Scale all hardware with no diagnosis.", "B"),
        ("A teammate asks you to approve code you did not review. Best action?", "Approve to be nice.", "Review it properly before approval.", "Reject it without reading every time.", "B"),
        ("The product owner changes requirements mid-sprint. Best move?", "Pretend nothing changed.", "Reassess scope and communicate impact.", "Promise no schedule effect automatically.", "B"),
        ("A flaky test blocks merges. Best response?", "Delete the test permanently.", "Stabilize or quarantine it while investigating root cause.", "Ignore it and merge failures.", "B"),
        ("A service is timing out under load. Best action?", "Increase timeout and stop investigating.", "Profile bottlenecks and address the real cause.", "Randomly rewrite the frontend.", "B"),
        ("Logs contain personal user data. Best response?", "Leave it because logs are internal.", "Reduce exposure and sanitize sensitive logging.", "Email the logs to everyone.", "B"),
        ("An API contract changed unexpectedly. Best response?", "Blame users for relying on it.", "Version, document, and coordinate the change safely.", "Hotpatch clients silently without review.", "B"),
        ("Two engineers disagree on architecture. Best move?", "Pick whoever is loudest.", "Compare tradeoffs against requirements and constraints.", "Let them each build half differently.", "B"),
        ("A cron job silently failed for days. Best response?", "Backfill without checking impact.", "Assess data integrity and recover carefully.", "Delete the job history.", "B"),
        ("A cache improves speed but serves stale data. Best action?", "Ignore consistency concerns.", "Define freshness rules and invalidate correctly.", "Remove persistence from the app.", "B"),
        ("A user reports they cannot log in after password reset. Best response?", "Tell them to try harder.", "Trace the auth flow and verify reset logic.", "Reset every user password at once.", "B"),
        ("A package update introduces a security advisory. Best move?", "Ignore the advisory indefinitely.", "Assess impact and patch responsibly.", "Update every dependency blindly in production.", "B"),
        ("A dashboard number looks wrong. Best response?", "Trust it because it is on the dashboard.", "Verify the source query and assumptions.", "Hide the widget temporarily and move on.", "B"),
        ("An intern suggests a fix that seems odd but plausible. Best action?", "Reject it because they are junior.", "Evaluate the idea on its merits and test it.", "Merge it directly to production with no review.", "B"),
        ("The staging environment differs from production. Best response?", "Assume that is fine forever.", "Reduce the gap and test under realistic conditions.", "Stop using staging entirely.", "B"),
        ("A service dependency is rate-limiting you. Best action?", "Spam retries as fast as possible.", "Respect limits and design resilient backoff.", "Fork bomb your own workers.", "B"),
        ("A customer wants a manual data fix. Best response?", "Edit production rows casually.", "Validate the request and use a safe audited process.", "Tell them to change the database themselves.", "B"),
        ("A feature flag exists for a risky launch. Best use?", "Deploy without it because flags are messy.", "Use staged rollout and monitor results.", "Enable it for everyone at once with no tracking.", "B"),
        ("A teammate says, 'it works on my machine.' Best response?", "Accept that as sufficient proof.", "Compare environments and reproduce systematically.", "Ban local development entirely.", "B"),
        ("A monitoring page is green but users report failure. Best action?", "Dismiss the reports because the dashboard is green.", "Investigate real user impact and missing signals.", "Turn the page red manually and stop.", "B"),
        ("A postmortem is being written after an outage. Best approach?", "Assign blame publicly.", "Document causes, mitigations, and prevention steps.", "Skip the postmortem to save time.", "B"),
    ]
    pools["developer"] = _pool("developer", "Laptop", "Task Board", developer_items)

    education_items = [
        ("What is the powerhouse of the cell?", "Nucleus", "Mitochondria", "Ribosome", "B"),
        ("2 + 2 * 2 = ?", "6", "8", "4", "A"),
        ("Best way to retain information over time?", "Cram once without sleep.", "Spaced repetition and practice.", "Never review anything.", "B"),
        ("Which is a primary emotion?", "Jealousy", "Happiness", "Nostalgia", "B"),
        ("What helps reduce anxiety long-term?", "Avoid everything forever.", "Gradual exposure plus coping skills.", "Never sleep.", "B"),
        ("What is photosynthesis mainly used for?", "Making rocks heavier", "Converting light into stored chemical energy", "Cooling the moon", "B"),
        ("Which writing choice is strongest for clarity?", "Use vague words everywhere.", "Choose precise words and structure ideas logically.", "Avoid punctuation entirely.", "B"),
        ("What does a hypothesis do in science?", "Proves a result before testing", "Makes a testable prediction", "Replaces all data collection", "B"),
        ("Which number is prime?", "21", "29", "39", "B"),
        ("What is the main role of the heart?", "Digest food", "Pump blood through the body", "Store memories", "B"),
        ("Which study habit is least effective?", "Distributed practice", "Passive rereading only", "Self-testing", "B"),
        ("What is the capital of France?", "Paris", "Rome", "Lisbon", "A"),
        ("What does inflation usually mean?", "Prices generally rise over time", "All wages double overnight", "Money disappears physically", "A"),
        ("Which sentence is grammatically complete?", "Because the rain.", "The rain stopped by noon.", "Running through the.", "B"),
        ("What does 'correlation' mean?", "One thing always causes the other", "Two variables change together", "A guaranteed law of nature", "B"),
        ("Which organ helps filter blood?", "Kidney", "Lung", "Skin", "A"),
        ("What is 15% of 200?", "20", "35", "30", "C"),
        ("Why do historians compare multiple sources?", "To make stories longer", "To improve accuracy and reduce bias", "To avoid evidence", "B"),
        ("What is a responsible way to use online information?", "Trust any viral post", "Check credible sources and evidence", "Pick the first result only", "B"),
        ("What is one benefit of sleep for learning?", "It makes facts disappear", "It supports memory consolidation", "It removes all stress permanently", "B"),
        ("What does the water cycle include?", "Evaporation and precipitation", "Only freezing", "Only ocean currents", "A"),
        ("Which is an example of renewable energy?", "Coal", "Solar", "Diesel", "B"),
        ("What is the purpose of a topic sentence?", "To confuse the reader", "To state the main idea of a paragraph", "To end the essay", "B"),
        ("If supply rises and demand stays the same, price often?", "Rises", "Falls", "Becomes impossible", "B"),
        ("What is empathy?", "Ignoring others' feelings", "Understanding another person's perspective", "Winning every argument", "B"),
        ("Which graph is best for showing change over time?", "Line graph", "Random doodle", "Word cloud", "A"),
        ("What is the function of punctuation?", "To remove meaning", "To clarify structure and meaning", "To make reading slower only", "B"),
        ("Why is exercise often recommended for wellbeing?", "It always solves every problem instantly", "It can support mood, health, and stress regulation", "It replaces sleep", "B"),
        ("Which is a reliable revision strategy?", "Practice questions with feedback", "Reading notes once while distracted", "Skipping difficult topics", "A"),
        ("What does an ecosystem include?", "Only animals", "Living things and their environment", "Only weather", "B"),
    ]
    pools["education"] = _pool("education", "Notebook", "Exam", education_items)

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


def pick_scenario(agent, pool_key: str, avoid_last: int = 8) -> Dict:
    pool = SCENARIO_POOLS.get(pool_key) or SCENARIO_POOLS["generic"]
    recent = list(getattr(agent, "recent_scenarios", {}).get(pool_key, []))

    avoid = set(recent[-avoid_last:]) if avoid_last > 0 else set()
    candidates = [s for s in pool if s["id"] not in avoid] or pool[:]
    chosen = random.choice(candidates)

    if not hasattr(agent, "recent_scenarios") or agent.recent_scenarios is None:
        agent.recent_scenarios = {}
    recent.append(chosen["id"])
    agent.recent_scenarios[pool_key] = recent[-30:]

    return chosen