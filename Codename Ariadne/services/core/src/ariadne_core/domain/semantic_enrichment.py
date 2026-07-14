"""Bounded, explainable semantic rules over already-redacted intake text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

from ariadne_core.domain.identity_compiler import (
    CandidateEntity,
    EntityType,
    Sensitivity,
    SourceSpan,
)

MAX_SEMANTIC_ENTITIES = 128
MAX_RELATIONSHIPS = 256
MAX_SEMANTIC_VALUE_CHARS = 160


class SemanticEntityType(StrEnum):
    PERSON = "PERSON"
    ALIAS = "ALIAS"
    ORGANISATION = "ORGANISATION"
    EDUCATION = "EDUCATION"
    LOCATION = "LOCATION"
    PROJECT = "PROJECT"


class RelationshipType(StrEnum):
    USED = "USED"
    PREVIOUS_USERNAME = "PREVIOUS_USERNAME"
    CURRENT_USERNAME = "CURRENT_USERNAME"
    EMPLOYED_BY = "EMPLOYED_BY"
    STUDIED_AT = "STUDIED_AT"
    LIVED_AT = "LIVED_AT"
    CREATED = "CREATED"
    NOT_SAME_AS = "NOT_SAME_AS"


class SemanticRuleError(ValueError):
    """Stable semantic-rule failure that never includes source text."""


@dataclass(frozen=True, slots=True)
class EntityReference:
    entity_type: str
    canonical_value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SemanticEntity:
    entity_type: SemanticEntityType
    canonical_value: str = field(repr=False)
    display_mask: str = field(repr=False)
    sensitivity: Sensitivity
    span: SourceSpan
    confidence_micros: int
    rule_code: str

    @property
    def reference(self) -> EntityReference:
        return EntityReference(self.entity_type.value, self.canonical_value)


@dataclass(frozen=True, slots=True)
class RelationshipCandidate:
    source: EntityReference
    target: EntityReference
    relationship_type: RelationshipType
    span: SourceSpan
    confidence_micros: int
    explanation_code: str
    contradictory: bool = False


@dataclass(frozen=True, slots=True)
class SemanticEnrichment:
    entities: tuple[SemanticEntity, ...]
    relationships: tuple[RelationshipCandidate, ...]
    exclusion_spans: tuple[SourceSpan, ...]
    engine_name: str = "bounded-semantic-rules"
    engine_version: str = "1"


_NAME = r"[A-Z][\w'-]{1,48}(?:\s+[A-Z][\w'-]{1,48}){1,3}"
_LABEL = r"[^\n.;]{2,160}?"
_PERSON_PATTERNS = (
    ("person.explicit_name", re.compile(rf"(?im)\b(?:my name is|name\s*:)\s*(?P<value>{_NAME})\b")),
    (
        "person.labelled_row",
        re.compile(
            rf"(?im)^\s*(?:name|person)\s*[,;\t]\s*(?P<value>{_NAME})"
            r"(?=\s*(?:[,;\t]|$))"
        ),
    ),
    (
        "person.subject_statement",
        re.compile(
            rf"(?m)(?P<value>{_NAME})\s+(?:uses?|used|works?|worked|studies|studied|"
            r"lives?|lived|is|was)\b"
        ),
    ),
)
_ALIAS_PATTERN = re.compile(
    rf"(?im)\b(?:known as|alias(?:ed)? as|nickname(?: is)?|formerly)\s+"
    rf"[\"']?(?P<value>{_LABEL})[\"']?(?=$|[.,;])"
)
_EMPLOYMENT_PATTERN = re.compile(
    rf"(?im)\b(?:works?|worked|employed)\s+(?:at|for|by)\s+(?P<value>{_LABEL})(?=$|[.,;])"
)
_ASSOCIATED_PATTERN = re.compile(
    rf"(?im)\b(?:previously|formerly|currently)?\s*associated with\s+"
    rf"(?P<value>{_LABEL})(?:\s+in\s+(?P<location>{_LABEL}))?(?=$|[.,;])"
)
_EDUCATION_PATTERN = re.compile(
    rf"(?im)\b(?:studies|studied|educated)\s+(?:at|by)\s+(?P<value>{_LABEL})(?=$|[.,;])"
)
_LOCATION_PATTERN = re.compile(
    rf"(?im)\b(?:lives?|lived|located|based)\s+in\s+(?P<value>{_LABEL})(?=$|[.,;])"
)
_PROJECT_PATTERN = re.compile(
    rf"(?im)\b(?:created|maintains?|maintained|founded)\s+(?:the\s+)?(?:project\s+)?(?P<value>{_LABEL})(?=$|[.,;])"
)
_EXCLUSION_PATTERN = re.compile(r"(?im)\b(?:this|that|it)\s+is\s+not\s+me\b")
_NEGATION_PATTERN = re.compile(r"(?i)\b(?:never|not|no longer|did not|didn't|does not|doesn't)\b")


def _normalise(value: str) -> str:
    canonical = " ".join(unicodedata.normalize("NFKC", value).strip(" \t\"'").split())
    if (
        not canonical
        or len(canonical) > MAX_SEMANTIC_VALUE_CHARS
        or any(ord(character) < 32 for character in canonical)
        or "█" in canonical
    ):
        raise SemanticRuleError("semantic value is invalid")
    return canonical


def _semantic_entity(
    *,
    entity_type: SemanticEntityType,
    match: re.Match[str],
    group: str,
    confidence_micros: int,
    rule_code: str,
) -> SemanticEntity | None:
    try:
        value = _normalise(match.group(group))
    except (IndexError, SemanticRuleError):
        return None
    sensitivity = Sensitivity.SENSITIVE
    if entity_type is SemanticEntityType.PERSON:
        display = " ".join(f"{part[0]}{'•' * min(5, len(part) - 1)}" for part in value.split())
    else:
        display = f"[{entity_type.value.casefold().replace('_', ' ')}]"
    return SemanticEntity(
        entity_type=entity_type,
        canonical_value=value,
        display_mask=display,
        sensitivity=sensitivity,
        span=SourceSpan(match.start(group), match.end(group)),
        confidence_micros=confidence_micros,
        rule_code=rule_code,
    )


def _nearest_person(
    people: tuple[SemanticEntity, ...], position: int, text: str
) -> SemanticEntity | None:
    sentence_start = (
        max(
            text.rfind(".", 0, position),
            text.rfind("!", 0, position),
            text.rfind("?", 0, position),
            text.rfind("\n", 0, position),
        )
        + 1
    )
    preceding = [person for person in people if sentence_start <= person.span.start <= position]
    return max(preceding, key=lambda item: item.span.start, default=None)


def _negation_before(text: str, position: int) -> SourceSpan | None:
    sentence_start = (
        max(
            text.rfind(".", 0, position),
            text.rfind("!", 0, position),
            text.rfind("?", 0, position),
            text.rfind("\n", 0, position),
        )
        + 1
    )
    matches = tuple(_NEGATION_PATTERN.finditer(text, sentence_start, position))
    if not matches:
        return None
    match = matches[-1]
    return SourceSpan(match.start(), match.end())


def _deterministic_reference(
    candidates: tuple[CandidateEntity, ...], span: SourceSpan
) -> EntityReference | None:
    within = [
        candidate
        for candidate in candidates
        if candidate.entity_type is EntityType.USERNAME
        and any(span.start <= origin.start and origin.end <= span.end for origin in candidate.spans)
    ]
    if not within:
        return None
    candidate = min(within, key=lambda item: item.spans[0].start)
    return EntityReference(candidate.entity_type.value, candidate.canonical_value)


def enrich_semantics(
    redacted_text: str,
    deterministic_candidates: tuple[CandidateEntity, ...],
) -> SemanticEnrichment:
    """Apply closed semantic rules without model calls or hidden inference."""

    if len(redacted_text.encode("utf-8")) > 1_048_576:
        raise SemanticRuleError("semantic input limit exceeded")
    entities: list[SemanticEntity] = []
    for rule_code, pattern in _PERSON_PATTERNS:
        for match in pattern.finditer(redacted_text):
            entity = _semantic_entity(
                entity_type=SemanticEntityType.PERSON,
                match=match,
                group="value",
                confidence_micros=(
                    900_000
                    if rule_code in {"person.explicit_name", "person.labelled_row"}
                    else 820_000
                ),
                rule_code=rule_code,
            )
            if entity is not None:
                entities.append(entity)
                if len(entities) > MAX_SEMANTIC_ENTITIES:
                    raise SemanticRuleError("semantic entity limit exceeded")

    person_mentions = tuple(entities)

    pattern_specs = (
        (_ALIAS_PATTERN, SemanticEntityType.ALIAS, "alias.explicit", 880_000),
        (_EMPLOYMENT_PATTERN, SemanticEntityType.ORGANISATION, "employment.explicit", 880_000),
        (_EDUCATION_PATTERN, SemanticEntityType.EDUCATION, "education.explicit", 880_000),
        (_LOCATION_PATTERN, SemanticEntityType.LOCATION, "location.explicit", 850_000),
        (_PROJECT_PATTERN, SemanticEntityType.PROJECT, "project.explicit", 820_000),
    )
    for pattern, entity_type, rule_code, confidence in pattern_specs:
        for match in pattern.finditer(redacted_text):
            entity = _semantic_entity(
                entity_type=entity_type,
                match=match,
                group="value",
                confidence_micros=confidence,
                rule_code=rule_code,
            )
            if entity is not None:
                entities.append(entity)
                if len(entities) > MAX_SEMANTIC_ENTITIES:
                    raise SemanticRuleError("semantic entity limit exceeded")

    for match in _ASSOCIATED_PATTERN.finditer(redacted_text):
        organisation = _semantic_entity(
            entity_type=SemanticEntityType.ORGANISATION,
            match=match,
            group="value",
            confidence_micros=760_000,
            rule_code="association.explicit",
        )
        if organisation is not None:
            entities.append(organisation)
        if match.group("location"):
            location = _semantic_entity(
                entity_type=SemanticEntityType.LOCATION,
                match=match,
                group="location",
                confidence_micros=700_000,
                rule_code="association.location",
            )
            if location is not None:
                entities.append(location)

    if len(entities) > MAX_SEMANTIC_ENTITIES:
        raise SemanticRuleError("semantic entity limit exceeded")
    entity_mentions = tuple(entities)

    deduplicated: dict[tuple[SemanticEntityType, str], SemanticEntity] = {}
    for entity in sorted(entities, key=lambda item: (item.span.start, item.entity_type.value)):
        key = (entity.entity_type, entity.canonical_value.casefold())
        previous = deduplicated.get(key)
        if previous is None or entity.confidence_micros > previous.confidence_micros:
            deduplicated[key] = entity
    final_entities = tuple(
        sorted(deduplicated.values(), key=lambda item: (item.span.start, item.entity_type.value))
    )
    relationships: list[RelationshipCandidate] = []
    exclusions = [
        SourceSpan(match.start(), match.end())
        for pattern in (_EXCLUSION_PATTERN, _NEGATION_PATTERN)
        for match in pattern.finditer(redacted_text)
    ]
    relationship_by_rule = {
        "employment.explicit": RelationshipType.EMPLOYED_BY,
        "association.explicit": RelationshipType.USED,
        "education.explicit": RelationshipType.STUDIED_AT,
        "location.explicit": RelationshipType.LIVED_AT,
        "project.explicit": RelationshipType.CREATED,
        "alias.explicit": RelationshipType.USED,
    }
    for entity in entity_mentions:
        relationship_type = relationship_by_rule.get(entity.rule_code)
        person = _nearest_person(person_mentions, entity.span.start, redacted_text)
        if relationship_type is None or person is None or person.reference == entity.reference:
            continue
        negation = _negation_before(redacted_text, entity.span.start)
        if negation is not None:
            exclusions.append(negation)
            continue
        relationships.append(
            RelationshipCandidate(
                source=person.reference,
                target=entity.reference,
                relationship_type=relationship_type,
                span=SourceSpan(person.span.start, entity.span.end),
                confidence_micros=min(person.confidence_micros, entity.confidence_micros),
                explanation_code=entity.rule_code,
            )
        )

    for sentence in re.finditer(r"[^\n.!?]{1,512}[.!?]?", redacted_text):
        reference = _deterministic_reference(
            deterministic_candidates,
            SourceSpan(sentence.start(), sentence.end()),
        )
        people_in_sentence = tuple(
            person
            for person in person_mentions
            if sentence.start() <= person.span.start < sentence.end()
        )
        person = min(people_in_sentence, key=lambda item: item.span.start, default=None)
        if reference is None or person is None:
            continue
        negation = _negation_before(redacted_text, sentence.end())
        if negation is not None:
            exclusions.append(negation)
            continue
        context = sentence.group().casefold()
        relation = (
            RelationshipType.PREVIOUS_USERNAME
            if any(word in context for word in ("historical", "former", "previous"))
            else RelationshipType.CURRENT_USERNAME
        )
        relationships.append(
            RelationshipCandidate(
                source=person.reference,
                target=reference,
                relationship_type=relation,
                span=SourceSpan(sentence.start(), sentence.end()),
                confidence_micros=800_000,
                explanation_code="username.context",
            )
        )

    if len(relationships) > MAX_RELATIONSHIPS:
        raise SemanticRuleError("semantic relationship limit exceeded")
    return SemanticEnrichment(
        entities=final_entities,
        relationships=tuple(relationships),
        exclusion_spans=tuple(sorted(set(exclusions))),
    )
