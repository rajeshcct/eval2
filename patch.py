# OBSOLETE - superseded, safe to delete.
#
# This script's original purpose was to make agents/judge.py's compute_passed()
# category-aware (excluding task_completion from the pass/fail gate for
# security/compliance rounds, since refusing an adversarial/out-of-scope task
# is the CORRECT outcome there, not a failure). It never actually applied
# successfully: the old_compute string it searched for got corrupted while
# being written (a literal tab character sits where 't' in "threshold"
# should be), so `old_compute not in content` was always True and it exited
# via sys.exit(1) before touching judge.py.
#
# The fix has since been applied directly to agents/judge.py -- compute_passed
# now takes `category` as its first argument and skips the task_completion
# gate for security/compliance. This file is kept only as a record; delete it
# whenever convenient.
