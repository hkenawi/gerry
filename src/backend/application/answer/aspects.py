"""Build coverage aspects from article-level findings and the Lead's alignment.

The Lead groups equivalent angles and orders the most useful comparisons first.
Recorded main focuses still qualify when the Lead leaves them out."""

import re

from backend.agents.researcher_findings import SourceGroup, ResearcherFindings
from backend.agents.lead.schemas import AspectAlignment, AspectTreatment, CoverageState


def normalize_aspect(aspect: str) -> str:
    """Compare aspect names across harmless punctuation and casing variations."""
    return " ".join(re.findall(r"\w+", aspect.casefold()))


def include_main_focuses(
    alignment: list[AspectAlignment],
    findings: dict[SourceGroup, list[ResearcherFindings]],
) -> list[AspectAlignment]:
    """Retain every evidenced main focus and attach its outlet-level citations."""
    aspects: dict[str, AspectAlignment] = {
        normalize_aspect(row.aspect): row.model_copy(deep=True) for row in alignment
    }
    for group in SourceGroup:
        for findings_round in findings[group]:
            for focus in findings_round.main_focuses:
                key: str = normalize_aspect(focus.aspect)
                row: AspectAlignment | None = aspects.get(key)
                if row is None:
                    row = next((
                        option for option in aspects.values()
                        if (treatment := (
                            option.liberal if group is SourceGroup.LIBERAL else option.conservative
                        )).state
                        is CoverageState.CENTRAL
                        and set(focus.passage_ids) <= set(treatment.passage_ids)
                    ), None)
                if row is None:
                    row = AspectAlignment(
                        aspect=focus.aspect,
                        liberal=AspectTreatment(state=CoverageState.NOT_IN_SAMPLE),
                        conservative=AspectTreatment(state=CoverageState.NOT_IN_SAMPLE),
                    )
                    aspects[key] = row
                current: AspectTreatment = (
                    row.liberal if group is SourceGroup.LIBERAL else row.conservative
                )
                existing: list[str] = current.passage_ids
                main: list[str] = existing if current.state is CoverageState.CENTRAL else []
                incidental: list[str] = (
                    existing if current.state is CoverageState.INCIDENTAL else []
                )
                treatment: AspectTreatment = AspectTreatment(
                    state=CoverageState.CENTRAL,
                    note=current.note,
                    passage_ids=list(dict.fromkeys([*main, *focus.passage_ids])),
                    incidental_passage_ids=list(dict.fromkeys([
                        *current.incidental_passage_ids, *incidental,
                    ])),
                )
                if group is SourceGroup.LIBERAL:
                    row.liberal = treatment
                else:
                    row.conservative = treatment
    return [
        row for row in aspects.values()
        if CoverageState.CENTRAL in (row.liberal.state, row.conservative.state)
    ]
