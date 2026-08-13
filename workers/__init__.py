"""
workers — long-running and scheduled SYSTEM processes.

WHAT BELONGS HERE. Work the product performs on its own schedule, with no human
actor: no GM, no commissioner, no HTTP request. Anything reachable from a route
belongs in `api/`; anything a commissioner triggers belongs on the lifecycle
surface. A module lands here precisely when its governing spec names the actor as
a machine.

The first inhabitant is `workers.final_lock`, whose actor class
SIMULATION_ENGINE_MODULE_SPEC_Rev9 §5.5 fixes as "the same scheduled system
worker/process class that acquires fresh claims. Not an end user, not a GM, not a
commissioner, not reachable from any HTTP route."
"""