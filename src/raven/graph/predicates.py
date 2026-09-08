"""Conservative canonical predicates: aliases change wording, never proposition scope."""

import re
from decimal import Decimal, InvalidOperation

PREDICATE_VERSION = "raven-predicates-v1"
PREDICATES = {
    "DEPENDENT_ON": "subject depends organizationally on object; direction matters",
    "TRANSFER": "subject transfers funds to object; retain amount, currency and transaction",
    "AFFILIATED_WITH": "explicit affiliation; missing evidence is not denial",
    "PUBLISHES": "subject publishes object",
    "DISTRIBUTES": "subject distributes object",
    "CITES": "subject cites object",
    "SAME_AS": "source identity hypothesis only, never automatic entity merge",
    "LOCATED_IN": "subject located in object; retain uncertainty and period",
    "RESPONSIBLE_FOR": "attributed responsibility; retain modality and speaker",
    "GRAPHIC_SUPPORT": "subject provides graphic services to object",
    "COLLABORATES_WITH": "explicit collaboration; preserve role and purpose",
    "OCCURRED_ON": "event date stored as typed date literal",
    "HAS_VALUE": "typed value of subject; preserve unit and purpose",
}
ALIASES = {
    "DEPENDENCE": "DEPENDENT_ON",
    "DEPENDS_ON": "DEPENDENT_ON",
    "TRANSFERRED": "TRANSFER",
    "TRANSFERRED_TO": "TRANSFER",
    "TRANSFERS_TO": "TRANSFER",
    "AFFILIATION": "AFFILIATED_WITH",
    "AFFILIATED_TO": "AFFILIATED_WITH",
    "LOCATION": "LOCATED_IN",
    "IS_LOCATED_IN": "LOCATED_IN",
    "PUBLICATION": "PUBLISHES",
    "PUBLISHED": "PUBLISHES",
    "PROVIDES_GRAPHIC_SUPPORT": "GRAPHIC_SUPPORT",
    "PROVIDES_GRAPHIC_SUPPORT_TO": "GRAPHIC_SUPPORT",
    "EVENT_DATE": "OCCURRED_ON",
    "DATE_OF_EVENT": "OCCURRED_ON",
}


def canonical_predicate(value: str) -> str:
    return ALIASES.get(value, value)


def name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def type_family(value: str) -> str:
    # Candidate comparison only. Never use this compatibility family to merge identities.
    return "collective" if value in {"GROUP", "ORGANIZATION", "FACILITY"} else value


def qualifiers_scope(qualifiers):
    result = []
    for key, value in qualifiers:
        key = name(key)
        key = {"importo": "amount", "valuta": "currency"}.get(key, key)
        if key == "amount":
            try:
                number = Decimal(value)
                value = format(number.normalize(), "f") if number.is_finite() else value
            except InvalidOperation:
                pass
        if key == "currency":
            value = {"euro": "EUR", "eur": "EUR", "€": "EUR"}.get(name(value), value.upper())
        result.append((key, value.strip()))
    return tuple(sorted(result))
