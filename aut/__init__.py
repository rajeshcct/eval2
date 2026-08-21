# EvalMind — aut/
#
# Holds the interface EvalMind uses to call the Agent Under Test (AUT) — a
# plain Python function, NOT a CrewAI Agent. The AUT is an external system
# being tested, called from the Generator/Judge pipeline the same way you'd
# call any function; it is never wired into the Crew as a collaborating agent.
#
# See connector.py for the single entry point: call_aut(task, config).
