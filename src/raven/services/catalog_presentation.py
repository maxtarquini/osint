"""Human-readable catalog details from the same contracts exposed by MCP."""

import json

from raven.models.capabilities import mcp_input_schema
from raven.services.capability_tools import SOURCE_TOOLS


def skill_available(row):
    return bool(
        row["enabled"]
        and row["state"] == "ready"
        and not row["unavailable_tools"]
        and not row["entry"].error
    )


def tool_details(tool, rows, metadata):
    enabled = tool.tool_id not in metadata["disabled_tools"]
    consumers = [
        row["entry"].definition.name
        for row in rows
        if row["entry"].definition and tool.tool_id in row["entry"].definition.tools
    ]
    if tool.tool_id in {item.tool_id for item in SOURCE_TOOLS}:
        execution = (
            "Legge le copie originali e verifica SHA-256; ricerca letterale "
            "o verifica esatta delle citazioni."
        )
    elif tool.tool_id == "retrieve_evidence":
        execution = (
            "Recupera contesto da Qdrant e Neo4j con il modello di embedding. "
            "La risposta conserva provenienza, avvisi e limiti del recupero."
        )
    elif tool.tool_id == "read_dictionary":
        execution = "Legge il dizionario corrente o la copia storica della variante richiesta."
    elif tool.tool_id == "list_graph_methods":
        execution = "Consulta le definizioni dei metodi; non avvia elaborazioni."
    else:
        execution = "Consulta metadati e varianti persistenti dell'indagine autorizzata."
    mcp_schema = mcp_input_schema(tool)
    return (
        f"{tool.name} · {tool.version}\nID: {tool.tool_id}\n"
        f"Stato: {'Abilitato' if enabled else 'Disabilitato'}\n\n{tool.description}\n\n"
        f"ACCESSO E USO\n{execution}\nSola lettura: nessuna modifica a indagini o grafi.\n"
        f"Perimetro: {tool.scope}\nTimeout: {tool.timeout_seconds}s · cancellazione cooperativa\n\n"
        "SKILL CHE LO DICHIARANO\n"
        + ("\n".join(consumers) or "Nessuna skill installata.")
        + "\n\nINPUT MCP · tools/call\n"
        + json.dumps(mcp_schema, ensure_ascii=False, indent=2)
        + "\n\nINPUT LOCALE · contesto indagine passato separatamente\n"
        + json.dumps(tool.parameters, ensure_ascii=False, indent=2)
        + "\n\nOUTPUT\n"
        + json.dumps(tool.result, ensure_ascii=False, indent=2)
    )
