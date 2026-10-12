"""
Deduce hidden grades from subject averages.

Some schools set ``affichageNote: false``: Ecole Directe then sends every
grade with an empty value, while the subject averages (student and class)
are still published. When exactly one new grade appears in a subject between
two refreshes, its value follows from the change of the average:

    new_grade = (n + 1) * new_average - n * previous_average

This is exact for the first grade of a subject (the average *is* the grade).
For later grades it assumes the new grade has the same coefficient as the
previous ones, since coefficients are hidden too: such values are flagged
``note_exacte: False``.

Averages are recomputed by Ecole Directe at ``dateCalcul`` (overnight), so a
grade may appear before the average includes it: a subject is only followed
up once the averages were computed after its latest grade was entered.

The memory (previous averages, list of grades per subject, deduced values)
is persisted by the coordinator in a Store, so deductions survive restarts.
"""

from __future__ import annotations

from typing import Any

MAX_GRADE = 20


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _fmt(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _key(note: dict) -> str:
    return f"{note.get('date')}|{note.get('commentaire')}"


def _hidden(note: dict) -> bool:
    return not str(note.get("note") or "").strip() and not note.get("non_significatif")


def _deduce(n: int, previous: float | None, current: float | None) -> float | None:
    if current is None:
        return None
    if n == 0:
        return current
    if previous is None:
        return None
    value = round((n + 1) * current - n * previous, 1)
    return value if 0 <= value <= MAX_GRADE else None


def deduce_hidden_grades(
    notes: list[dict],
    disciplines: list[dict],
    periode: str | None,
    memory: dict,
    date_calcul: str | None = None,
) -> bool:
    """
    Fill hidden grades in ``notes`` (in place) from ``disciplines`` averages.

    ``memory`` is updated in place; returns True when it changed.
    """
    changed = False
    if memory.get("periode") != periode:
        # New period: averages restart, so does the follow-up per subject.
        memory["periode"] = periode
        memory["matieres"] = {}
        changed = True
    matieres = memory.setdefault("matieres", {})
    deduced = memory.setdefault("notes", {})

    averages = {
        (d.get("nom") or "").lower(): (
            _float(d.get("moyenne")),
            _float(d.get("moyenneClasse")),
        )
        for d in disciplines
    }

    by_subject: dict[str, list[dict]] = {}
    for note in notes:
        if note.get("code_periode") not in (None, periode):
            continue
        if not _hidden(note):
            continue
        by_subject.setdefault((note.get("matiere") or "").lower(), []).append(note)

    for subject, subject_notes in by_subject.items():
        if subject not in averages:
            continue
        average, class_average = averages[subject]
        if average is None:
            continue
        latest = max(str(n.get("date_saisie") or "") for n in subject_notes)
        if not date_calcul or str(date_calcul)[:10] <= latest:
            # The averages do not include the latest grade yet: wait.
            continue
        keys = sorted({_key(n) for n in subject_notes})
        previous = matieres.get(subject)
        new_keys = [k for k in keys if not previous or k not in previous["devoirs"]]
        if previous is None:
            if len(keys) == 1:
                new_keys = keys
                known = 0
            else:
                new_keys = []
                known = len(keys)
        else:
            known = len(previous["devoirs"])
            if not set(previous["devoirs"]) <= set(keys):
                new_keys = []
        if len(new_keys) == 1 and new_keys[0] not in deduced:
            value = _deduce(known, previous and previous.get("moy"), average)
            if value is not None:
                class_value = _deduce(
                    known, previous and previous.get("classe"), class_average
                )
                deduced[new_keys[0]] = {
                    "note": value,
                    "classe": class_value,
                    "exacte": known == 0,
                }
                changed = True
        state = {"devoirs": keys, "moy": average, "classe": class_average}
        if matieres.get(subject) != state:
            matieres[subject] = state
            changed = True

    for note in notes:
        found = deduced.get(_key(note))
        if found and _hidden(note):
            note["note"] = _fmt(found["note"])
            note["sur"] = "20"
            note["note_sur"] = note["note"] + "/20"
            if found.get("classe") is not None:
                note["moyenne_classe"] = _fmt(found["classe"])
            note["note_deduite"] = True
            note["note_exacte"] = bool(found.get("exacte"))
    return changed
