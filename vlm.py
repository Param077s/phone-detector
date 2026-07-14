"""
Vigil's optional AI "second look".

After the YOLO detector flags an alert, this asks a local vision model (via Ollama)
to LOOK at the cropped photo and:
  1. describe the scene in one plain-English sentence  (#1 richer alerts)
  2. confirm the target is really there                (#3 false-alarm filtering)

Design rules:
  * Fail OPEN. If the model is off, missing, slow, or errors, we return None and
    the caller keeps the alert exactly as before. We NEVER lose a real alert
    because the AI hiccuped.
  * No extra pip dependencies — talks to Ollama's HTTP API with urllib.
  * Everything runs locally; nothing leaves the machine.

Enable it from Settings (or VLM_ENABLED=true). Needs Ollama running with a vision
model pulled, e.g.:  ollama pull llava   (or moondream / qwen2.5vl)
"""

import base64
import json
import time
import urllib.request
import urllib.error

# --- config (set by configure() from app.py's settings) ---------------------
_ENABLED = False
_MODEL = "llava"
_VERIFY = True                 # drop alerts the model says are NOT the target
_HOST = "http://localhost:11434"
_TIMEOUT = 25                  # seconds; a whole alert waits at most this long

# --- availability cache: don't wait on a full timeout every alert when Ollama
#     isn't even running. Re-probe at most every 30s. -------------------------
_avail = None                  # None = unknown, True/False = last probe result
_avail_checked_at = 0.0
_AVAIL_TTL = 30.0


def configure(enabled=None, model=None, verify=None, host=None, timeout=None):
    """Called at startup and whenever settings are saved."""
    global _ENABLED, _MODEL, _VERIFY, _HOST, _TIMEOUT, _avail
    if enabled is not None: _ENABLED = bool(enabled)
    if model is not None:   _MODEL = (model or "llava").strip()
    if verify is not None:  _VERIFY = bool(verify)
    if host is not None:    _HOST = host.rstrip("/")
    if timeout is not None: _TIMEOUT = int(timeout)
    _avail = None              # force a fresh probe after any config change


def is_enabled():
    return _ENABLED


def _probe_available():
    """Quick check that Ollama is up and the model exists. Cached for 30s."""
    global _avail, _avail_checked_at
    now = time.time()
    if _avail is not None and (now - _avail_checked_at) < _AVAIL_TTL:
        return _avail
    _avail_checked_at = now
    try:
        req = urllib.request.Request(f"{_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            tags = json.load(r)
        names = [m.get("name", "") for m in tags.get("models", [])]
        # match "llava" against "llava:latest", "llava:7b", etc.
        base = _MODEL.split(":")[0]
        _avail = any(n.split(":")[0] == base for n in names)
        if not _avail:
            print(f"[vlm] Ollama is running but model '{_MODEL}' isn't pulled "
                  f"(have: {', '.join(names) or 'none'}). Run: ollama pull {base}")
    except Exception:
        _avail = False
        print(f"[vlm] Ollama not reachable at {_HOST} — AI second look is idle. "
              f"Start Ollama and `ollama pull {_MODEL.split(':')[0]}` to enable it.")
    return _avail


# Small vision models (moondream) describe a scene accurately but are unreliable
# at a strict yes/no ("is a phone present?" -> they tend to always say yes). Their
# DESCRIPTION, though, is trustworthy. So for the veto we judge presence from the
# description text: if the model described the scene and never mentioned the target
# (or a synonym), we treat it as absent. Words per common target: -------------
_SYNONYMS = {
    "phone":    ["phone", "cellphone", "cell phone", "smartphone", "smart phone",
                 "mobile", "iphone", "telephone", "handset"],
    "laptop":   ["laptop", "notebook computer", "computer"],
    "knife":    ["knife", "blade"],
    "scissors": ["scissors", "shears"],
    "bottle":   ["bottle", "flask"],
    "backpack": ["backpack", "rucksack", "bag"],
    "handbag":  ["handbag", "purse", "bag"],
    "book":     ["book"],
    "umbrella": ["umbrella", "parasol"],
    "person":   ["person", "man", "woman", "people", "someone", "individual", "boy", "girl"],
}


def _mentions_target(description, target):
    d = (description or "").lower()
    words = _SYNONYMS.get(target.lower(), [target.lower()])
    return any(w in d for w in words)


_PROMPT = (
    "You are reviewing a cropped still frame from a security camera. "
    "The automated detector thinks it contains a {target}. "
    "Look carefully and reply with ONLY a JSON object, no other text:\n"
    '{{"present": true or false, "description": "..."}}\n'
    "Rules:\n"
    '- "present": true only if a {target} is clearly visible; false if it is '
    "actually something else (a remote, wallet, book, hand, etc.) or nothing.\n"
    '- "description": one short factual sentence about the person and what they '
    "are doing, including clothing colours and rough position if visible. "
    "Keep it under 20 words."
)


def describe_and_verify(jpg_bytes, target):
    """
    Returns a dict {"present": bool, "description": str} when the model ran,
    or None when the AI is disabled/unavailable/errored (caller proceeds as before).

    When verification is turned off, "present" is always True (describe-only mode),
    so the caller never drops an alert on it.
    """
    if not _ENABLED or not jpg_bytes:
        return None
    if not _probe_available():
        return None

    b64 = base64.b64encode(jpg_bytes).decode("ascii")
    payload = {
        "model": _MODEL,
        "prompt": _PROMPT.format(target=target),
        "images": [b64],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    try:
        req = urllib.request.Request(
            f"{_HOST}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            out = json.load(r)
        raw = (out.get("response") or "").strip()
        data = json.loads(raw)
        model_flag = bool(data.get("present", True))
        desc = str(data.get("description", "")).strip()

        # Decide whether the target is really present:
        if not _VERIFY:
            present = True                       # describe-only: never veto
        elif not model_flag:
            present = False                      # a model that says "no" is trusted
        elif not desc:
            present = True                       # no description to judge -> keep (safe)
        else:
            # Trust the description over the weak yes/no: veto only when the target
            # (or a synonym) is absent from an otherwise-detailed description.
            present = _mentions_target(desc, target)

        print(f"[vlm] {_MODEL} reviewed alert in {time.time()-t0:.1f}s "
              f"-> present={present} (model_flag={model_flag}) :: {desc[:60]}")
        return {"present": present, "description": desc}
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        # timeout / connection drop / unparseable reply -> fail open (keep the alert)
        print(f"[vlm] review skipped ({type(e).__name__}) — keeping alert as-is")
        return None
    except Exception as e:
        print(f"[vlm] unexpected error ({type(e).__name__}) — keeping alert as-is")
        return None
