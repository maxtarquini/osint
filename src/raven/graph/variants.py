"""Semantic A/B alignment with explicit identity ambiguity, never UUID matching."""

from collections import Counter, defaultdict

from raven.graph.predicates import canonical_predicate, name, qualifiers_scope, type_family


def compare_variants(first, second):
    if first.investigation_id != second.investigation_id:
        raise ValueError("Cannot compare variants from different investigations")

    def identity(entity):
        return (
            type_family(entity.entity_type),
            name(entity.canonical_name),
            tuple(sorted(entity.external_identifiers)),
        )

    def claims(graph):
        by_id = {e.entity_id: e for e in graph.entities}
        rows = defaultdict(list)
        for claim in graph.claims:
            subject = by_id.get(claim.subject_entity_id)
            target = by_id.get(claim.object_entity_id)
            key = (
                identity(subject) if subject else ("missing", claim.subject_entity_id),
                identity(target) if target else ("literal", ""),
                canonical_predicate(claim.predicate),
                qualifiers_scope(claim.qualifiers),
                claim.polarity,
                claim.epistemic_status,
                claim.modality,
                claim.claim_kind,
                claim.valid_from,
                claim.valid_until,
                (claim.literal.value, claim.literal.datatype, claim.literal.unit)
                if claim.literal
                else None,
                name(claim.source.source_id or claim.attribution),
                tuple(sorted((s.evidence_id, s.page_number) for s in claim.support)),
            )
            rows[key].append(claim.claim_id)
        return rows

    a, b = claims(first), claims(second)
    lost, gained = [key for key in a if key not in b], [key for key in b if key not in a]
    classifications = []
    ea, eb = defaultdict(set), defaultdict(set)
    for graph, output in ((first, ea), (second, eb)):
        for entity in graph.entities:
            output[name(entity.canonical_name)].add(
                (entity.entity_type, entity.subtype, entity.semantic_support)
            )
    for label in sorted(ea.keys() & eb.keys()):
        if ea[label] != eb[label]:
            classifications.append(
                {"name": label, "a": sorted(ea[label], key=str), "b": sorted(eb[label], key=str)}
            )

    def metrics(graph):
        labels = Counter(identity(e) for e in graph.entities)
        linked = {i for r in graph.relationships for i in (r.source_entity_id, r.target_entity_id)}
        return {
            "claims": len(graph.claims),
            "supported_claims": sum(c.semantic_support == "supported" for c in graph.claims),
            "denials": sum(c.polarity == "denied" for c in graph.claims),
            "evidence_gaps": sum(c.epistemic_status == "not_documented" for c in graph.claims),
            "operations": sum(
                c.claim_kind in {"corrects", "retracts", "withdraws_certainty", "ceases"}
                for c in graph.claims
            ),
            "fragmented_names": sum(count > 1 for count in labels.values()),
            "isolated_entities": sum(e.entity_id not in linked for e in graph.entities),
            "coverage": dict(Counter(p.state for p in graph.pages)),
            "source_designations": sorted(
                {c.source.source_id for c in graph.claims if c.source.source_id}
            ),
            "comparisons": len(graph.claim_links),
        }

    return {
        "a": first.run_id,
        "b": second.run_id,
        "same_input": bool(
            first.manifest
            and second.manifest
            and first.manifest.documents == second.manifest.documents
        ),
        "same_dictionary": bool(
            first.manifest and second.manifest
            and first.manifest.dictionary_hash == second.manifest.dictionary_hash
            and first.manifest.dictionary_versions == second.manifest.dictionary_versions
        ),
        "dictionary_a": {
            "hash": first.manifest.dictionary_hash,
            "versions": first.manifest.dictionary_versions,
        } if first.manifest else None,
        "dictionary_b": {
            "hash": second.manifest.dictionary_hash,
            "versions": second.manifest.dictionary_versions,
        } if second.manifest else None,
        "matched": len(a.keys() & b.keys()),
        "lost": [{"proposition": key, "claim_ids": a[key]} for key in lost],
        "gained": [{"proposition": key, "claim_ids": b[key]} for key in gained],
        "classification_differences": classifications,
        "metrics_a": metrics(first),
        "metrics_b": metrics(second),
        "alignment": (
            "Candidate name/type-family alignment, not an identity merge or accuracy score."
        ),
    }


def comparison_text(report):
    lines = [
        f"A {report['a'][:8]} → B {report['b'][:8]}",
        "Input identici"
        if report["same_input"]
        else "Manifest/input diversi o legacy: verificare comparabilità",
        "Dizionario identico" if report.get("same_dictionary") else
        "Dizionari diversi o legacy: i codici di classificazione richiedono confronto delle definizioni",
        f"Proposizioni allineate: {report['matched']} · recuperate in B: "
        f"{len(report['gained'])} · assenti in B: {len(report['lost'])}",
        "Allineamento candidato per nomi e tipi compatibili; identità da revisionare.",
    ]
    if not report.get("same_dictionary"):
        for label, key in (("A", "dictionary_a"), ("B", "dictionary_b")):
            dictionary = report.get(key) or {}
            lines.append(f"Dizionario {label}: {dictionary.get('versions', '?')} · hash {dictionary.get('hash', '?')}")
    labels = {
        "claims": "Affermazioni",
        "supported_claims": "Supporto semantico",
        "denials": "Smentite",
        "evidence_gaps": "Assenza di riscontri",
        "operations": "Rettifiche/ritiri/cessazioni",
        "fragmented_names": "Nomi frammentati",
        "isolated_entities": "Entità isolate",
        "comparisons": "Confronti",
    }
    for key, label in labels.items():
        lines.append(f"{label}: {report['metrics_a'][key]} → {report['metrics_b'][key]}")
    lines.append(
        f"Copertura A: {report['metrics_a']['coverage']}\nCopertura B: "
        f"{report['metrics_b']['coverage']}"
    )
    for title, key in (("RECUPERATE IN B", "gained"), ("ASSENTI IN B", "lost")):
        lines.append("\n" + title)
        for row in report[key]:
            p = row["proposition"]
            lines.append(
                f"{p[0][1]} · {p[2]} · {p[1][1] or p[10]} | {p[4]}/{p[5]}/{p[6]} | "
                f"{p[7]} | {p[8]} → {p[9]} | {p[3]} | fonte {p[11]} | pagine "
                f"{p[12]} | claim {', '.join(row['claim_ids'])}"
            )
    lines.append("\nCLASSIFICAZIONI DISCORDANTI")
    for row in report["classification_differences"]:
        lines.append(f"{row['name']}: {row['a']} → {row['b']}")
    lines.append(
        "\nConteggi descrittivi, non misure di accuratezza. Una citazione "
        "verificata non certifica la verità della fonte."
    )
    return "\n".join(lines)
