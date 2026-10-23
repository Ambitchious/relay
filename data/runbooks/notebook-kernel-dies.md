# Notebook kernel dies on startup

**Symptom.** The kernel restarts immediately, or the notebook shows
"Kernel appears to have died" before any cell runs.

## Triage

1. Check the requested instance size against what the notebook profile allows.
   A profile asking for more memory than its quota fails silently at start.
2. Look for a `requirements.txt` in the workspace with a pinned package that
   conflicts with the base image.
3. Check whether the home volume is full — a full volume prevents the kernel
   writing its connection file.

## Fix

- Clear the workspace cache under `~/.cache` first; a full volume is the most
  common cause and the cheapest to fix.
- Pin packages against the base image version rather than latest.
- If the profile is over quota, pick a smaller profile or request a quota
  increase through the access portal.
