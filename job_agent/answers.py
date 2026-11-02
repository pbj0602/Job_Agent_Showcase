"""Answer an application form's questions from the vault, before anyone opens the form.

Each question is answered from the vault's answers.yml (pattern -> answer) or the
country's work-authorisation rule, or marked NEEDS_HUMAN — it never invents an answer.
prepare.py turns the result into answers.md, the copy-ready sheet the person applies with;
a required NEEDS_HUMAN item is flagged for the person to answer.

answers.yml:
    profile: {first_name: Alex, last_name: Morgan, email: ..., phone: ..., linkedin: ...}
    rules:
      - {match: "referred by", answer: "No"}
      - {match: "currently .*employee|previously employed", answer: "No"}
      - {match: "gender|race|ethnic|veteran|disability", answer: "Decline to self-identify"}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import fold

NEEDS_HUMAN = "NEEDS_HUMAN"

_PROFILE_FIELDS = [
    (r"^first name|^given name|^preferred first", "first_name"),
    (r"^last name|^surname|^family name", "last_name"),
    (r"^full name|^name$", "full_name"),
    (r"e-?mail", "email"),
    (r"^(?!.*(extension|device type|phone type|country code|phone code))(.*phone|mobile|contact number)", "phone"),
    (r"linkedin", "linkedin"),
    (r"github|portfolio|website", "github"),
    (r"^(current )?(city|location)|place of residence|city of residence|where (do|are) you (live|based)", "city"),
]
_SPONSOR_Q = re.compile(r"sponsor|visa|work authori[sz]ation|immigration")
_AUTHORISED_Q = re.compile(r"(legally |presently |currently )?(authori[sz]ed|eligible|right) to work")


@dataclass
class Step:
    label: str
    type: str
    required: bool
    value: str
    source: str  # profile | rule | visa | cv | NEEDS_HUMAN


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)

    @property
    def blockers(self) -> list[Step]:
        return [s for s in self.steps if s.required and s.value == NEEDS_HUMAN]

    @property
    def auto_ok(self) -> bool:
        return not self.blockers


def plan(questions: list[dict], answers: dict, visa_rule: dict | None, cv_path: str = "") -> Plan:
    prof = answers.get("profile", {})
    if "full_name" not in prof and prof.get("first_name"):
        prof = {**prof, "full_name": f"{prof['first_name']} {prof.get('last_name', '')}".strip()}
    rules = [(re.compile(r["match"], re.I), r["answer"]) for r in answers.get("rules", [])]
    needs_sponsor = (visa_rule or {}).get("sponsor_needed", True)
    out = Plan()
    for q in questions or []:
        label, typ, req = q.get("label", ""), q.get("type", ""), bool(q.get("required"))
        l = fold(label).strip()
        value, src = NEEDS_HUMAN, NEEDS_HUMAN
        if typ == "input_file" and re.search(r"resume|cv", l):
            value, src = cv_path or NEEDS_HUMAN, "cv" if cv_path else NEEDS_HUMAN
        elif typ == "input_file":
            value, src = NEEDS_HUMAN, NEEDS_HUMAN  # cover letters etc. are written by a human
        else:
            for rx, ans in rules:  # explicit rules beat built-ins
                if rx.search(label):
                    value, src = ans, "rule"
                    break
            else:
                if _SPONSOR_Q.search(l) and visa_rule is not None and (
                        re.search(r"\b(will|do|would)\b.*\b(require|need)", l)
                        or (len(l.split()) <= 4 and "sponsor" in l)):  # e.g. a bare "Visa Sponsorship"
                    value, src = ("Yes" if needs_sponsor else "No"), "visa"
                elif _AUTHORISED_Q.search(l) and visa_rule is not None:
                    # "Presently authorised" is not the same as "needs no sponsor": in IE or DE the
                    # candidate applies for their own permit, so they are not authorised *yet*.
                    authorised = visa_rule.get("presently_authorised", not needs_sponsor)
                    value, src = ("Yes" if authorised else "No"), "visa"
                elif re.search(r"if (you )?(replied|answered) yes|please explain|if applicable", l) and not req:
                    value, src = "", "rule"  # optional follow-ups stay empty
                else:
                    for rx, key in _PROFILE_FIELDS:
                        if re.search(rx, l) and prof.get(key):
                            value, src = prof[key], "profile"
                            break
        out.steps.append(Step(label, typ, req, value, src))
    return out
