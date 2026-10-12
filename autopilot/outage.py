"""Q22: four rules for a build that is running. Pure helpers; `Orchestrator._run_backend` and `execute_task` call them.

1. A vendor outage: three 5xx or timeouts within one minute: one sentence, no retry loop, no login prompt.
2. An expired login in the middle of a run: the task is parked (no try is spent), the login check runs again, the login
   command is printed, the next start continues.
3. A model that is not on this plan or in this region: one sentence with the alias that works.
4. The same parsed error three times across tasks: the run stops with the checklist before the window is spent."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .install_errors import explain

OUTAGE_COUNT, OUTAGE_WINDOW = 3, 60.0     # rule 1: three 5xx or timeouts inside one minute
REPEAT_COUNT = 3                           # rule 4: the same parsed error from this many tasks
OUTAGE_SENTENCE = "The service is down, try again in 15 minutes."

_5XX = re.compile(r"API Error:? (?:50[0234]|529)\b|overloaded_error|Service Unavailable|Bad Gateway|"
                  r"Request timed out|\b50[0234]\b", re.IGNORECASE)
_MODEL = re.compile(r"model.{0,60}(?:not found|not available|does not exist|unknown|not supported)|"
                    r"(?:unknown|invalid) model|model_not_found|invalid_model", re.IGNORECASE)
# alias ladder, the cheapest name that every plan has first; the sentence names the first one that is not the failing one
ALIASES = ("sonnet", "haiku", "opus")


def is_outage(text: str) -> bool:
    """A 5xx or a timeout from the vendor host (the text of one failed session)."""
    return bool(_5XX.search(text or ""))


_EXPIRED = re.compile(r"OAuth token (?:has )?expired|token_expired|API Error:? 401\b|invalid_api_key|session (?:has )?expired",
                      re.IGNORECASE)


def is_expired_login(text: str) -> bool:
    """A login that ran out (a first-time 'please run /login' is not this: that one keeps the old wait-and-retry)."""
    return bool(_EXPIRED.search(text or ""))


def is_model_problem(text: str) -> bool:
    return bool(_MODEL.search(text or ""))


def model_sentence(failing: str) -> str:
    """Rule 3: one sentence with the alias that works."""
    alias = next((a for a in ALIASES if a not in (failing or "").lower()), ALIASES[0])
    return (f"The model {failing or 'you named'} is not available on this plan or in this region: "
            f"use the alias {alias} in models.ladder.")


@dataclass
class Tracker:
    """Rule 1 and rule 4 counters for one run. `now` is replaced by a test."""
    now: object = time.time
    hits: list = field(default_factory=list)                 # times of 5xx / timeout answers
    seen: dict = field(default_factory=dict)                 # parsed error id -> set of task ids

    def outage(self, text: str) -> bool:
        """Record one failed session; True when it is the third outage answer inside one minute."""
        if not is_outage(text):
            return False
        t = self.now()
        self.hits = [h for h in self.hits if t - h <= OUTAGE_WINDOW] + [t]
        return len(self.hits) >= OUTAGE_COUNT

    def ok(self) -> None:
        self.hits.clear()

    def repeat(self, task_id: str, text: str) -> str:
        """Rule 4: the parsed error id when the same one has now come from REPEAT_COUNT different tasks, else ''."""
        eid, _, _ = explain(text)
        if not eid:
            return ""
        self.seen.setdefault(eid, set()).add(task_id or "-")
        return eid if len(self.seen[eid]) >= REPEAT_COUNT else ""


def checklist(error_id: str, text: str) -> list[str]:
    """The checklist of rule 4: what repeats, what is done, what is not, and the next command."""
    _, sentence, fix = explain(text)
    return [f"The same error stopped three tasks: {sentence}",
            "Done: the tasks that finished before it are merged; nothing is lost.",
            "Not done: the tasks that failed with it are parked, and the usage window was not spent on retries.",
            f"Next: {fix or 'ap doctor --runner'}, then ap start"]
