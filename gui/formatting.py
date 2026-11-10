"""Formatarea observațiilor pentru afișare."""

from interpretation.observations import FrameObservation

def observation_text(result: FrameObservation) -> str:
    obs = result.observation
    grouped = result.usage.get("scope") == "request"
    usage = result.usage.get("request_usage", {}) if grouped else result.usage
    scope = " (întregul apel, comun cadrelor din grup)" if grouped else ""
    names = {entity.id: entity.name for entity in obs.entities}

    lines = [obs.description, "", "OBIECTE"]

    for entity in obs.entities:
        lines.append(
            f"• {entity.name}: {', '.join(entity.features)}\n"
            f"  Poziție: {entity.location}; "
            f"vizibilitate: {entity.visibility}"
        )

    lines += ["", "RELAȚII"]

    for relation in obs.relations:
        lines.append(
            f"• {names[relation.subject_id]} — "
            f"{relation.predicate} — "
            f"{names[relation.object_id]}"
        )

    lines += ["", "ACTIVITATE"]
    lines += [
        f"• {action.description}"
        + (" (incert)" if action.uncertain else "")
        for action in obs.actions
    ]

    lines += ["", "TEXT VIZIBIL", *obs.visible_text]
    lines += ["", "INCERTITUDINI", *obs.uncertainties]

    lines += [
        "",
        f"Model: {result.resolved_model}",
        f"Durată{scope}: {result.elapsed_seconds:.2f} s",
        f"Tokeni{scope}: {usage.get('total_tokens', 'indisponibil')}",
    ]

    return "\n".join(lines)