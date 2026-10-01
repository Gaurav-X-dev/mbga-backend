"""Generate the delivery app's API reference from the live OpenAPI schema.

Written rather than hand-authored for one reason: a hand-written API document starts accurate and
drifts. This one is regenerated from the routes themselves, so a field that is renamed in the code
is renamed in the document, and a document that disagrees with the server cannot be produced.

    python scripts/generate_delivery_api_docs.py

Writes `docs/DELIVERY_APP_API.md`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("FCM_ENABLED", "false")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app

PREFIX = "/api/v1/delivery"
OUT = Path(__file__).resolve().parent.parent / "docs" / "DELIVERY_APP_API.md"

#: Sections, in the order a driver meets them, with the paths that belong to each.
SECTIONS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "Authentication",
        (
            "Sign-in is by OTP on the driver's registered mobile. A token minted here works only "
            "on the delivery channel - it is refused by the merchant and customer APIs, and theirs "
            "are refused here."
        ),
        ("/auth/",),
    ),
    (
        "Deliveries",
        (
            "The driver's work. Every one of these is scoped to the slips addressed to **this** "
            "driver; another driver's delivery returns `404`, never `403`."
        ),
        ("/deliveries",),
    ),
    (
        "Driver",
        "The driver's own record, and what their van is carrying.",
        ("/driver/",),
    ),
    (
        "Notifications",
        (
            "The in-app bell. A driver sees only what is addressed to them personally - never the "
            "merchant's shared notifications."
        ),
        ("/notifications",),
    ),
]


def _deref(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    return components.get(ref.split("/")[-1], {})


def _type_of(field: dict[str, Any]) -> str:
    """A readable type, flattening the `anyOf[X, null]` that Optional produces."""
    if "anyOf" in field:
        inner = [f for f in field["anyOf"] if f.get("type") != "null"]
        nullable = len(inner) != len(field["anyOf"])
        base = _type_of(inner[0]) if inner else "any"
        return f"{base} · nullable" if nullable else base
    if "$ref" in field:
        return field["$ref"].split("/")[-1]
    kind = field.get("type", "any")
    if kind == "array":
        return f"{_type_of(field.get('items', {}))}[]"
    if field.get("enum"):
        return " | ".join(f"`{v}`" for v in field["enum"])
    return {"integer": "int", "number": "float", "boolean": "bool", "string": "string"}.get(
        kind, kind
    )


def _fields_table(schema: dict[str, Any], components: dict[str, Any]) -> list[str]:
    schema = _deref(schema, components)
    props = schema.get("properties")
    if not props:
        return []
    required = set(schema.get("required", []))
    lines = ["", "| Field | Type | Required | Notes |", "|---|---|---|---|"]
    for name, field in props.items():
        note = field.get("description", "")
        if "default" in field and field["default"] is not None:
            note = (note + f" Defaults to `{json.dumps(field['default'])}`.").strip()
        if field.get("maxLength"):
            note = (note + f" Max {field['maxLength']} characters.").strip()
        lines.append(
            f"| `{name}` | {_type_of(field)} | {'yes' if name in required else 'no'} | {note} |"
        )
    return lines


def _body_schema(op: dict[str, Any]) -> dict[str, Any] | None:
    body = op.get("requestBody")
    if not body:
        return None
    for content in body.get("content", {}).values():
        return content.get("schema")
    return None


def _response_schema(op: dict[str, Any]) -> dict[str, Any] | None:
    for code in ("200", "201"):
        content = op.get("responses", {}).get(code, {}).get("content", {})
        for payload in content.values():
            return payload.get("schema")
    return None


def main() -> None:
    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    out: list[str] = []

    out.append("# MBGA Delivery App - Backend API\n")
    out.append(
        "Everything the delivery app can call. Generated from the running server, so this "
        "document and the API cannot disagree.\n"
    )
    out.append(
        "Regenerate with `python scripts/generate_delivery_api_docs.py`. "
        "Live, browsable version: **`{BASE_URL}/docs/delivery`**.\n"
    )

    out.append("\n## Base URL\n")
    out.append("```\n{BASE_URL}" + PREFIX + "\n```\n")
    out.append(
        "The `/delivery` segment is what makes a request a driver request. A token issued on "
        "this channel is rejected on `/merchant`, `/customer` and `/admin`, and theirs are "
        "rejected here.\n"
    )

    out.append("\n## Headers\n")
    out.append("| Header | Value | When |")
    out.append("|---|---|---|")
    out.append("| `Authorization` | `Bearer <accessToken>` | Every endpoint except the OTP ones |")
    out.append("| `Content-Type` | `application/json` | Every request with a body |\n")

    out.append("\n## Errors\n")
    out.append("Every failure comes back in one shape:\n")
    out.append(
        "```json\n"
        "{\n"
        '  "detail": {\n'
        '    "code": "DELIVERY_NOT_READY",\n'
        '    "message": "Order MBGA-R-0007 has not been dispatched yet...",\n'
        '    "fields": [],\n'
        '    "request_id": "0f3c9a1e-..."\n'
        "  }\n"
        "}\n"
        "```\n"
    )
    out.append(
        "Show `message` to the driver and branch on `code` - never on the message text, which "
        "is written for people and will be reworded. Quote `request_id` when reporting a bug; "
        "it finds the exact request in the server logs.\n"
    )
    out.append(
        "\n> **If your HTTP client expects `{ \"success\": ..., \"error\": ... }`** - the shape "
        "in the original integration spec - say so and the server can be switched to it for this "
        "channel. It is one deployment flag (`DELIVERY_RESPONSE_ENVELOPE`). It is **off** today "
        "because turning it on also wraps the auth responses you are already parsing.\n"
    )

    # --- the flow, which an endpoint list cannot express ---------------------------------------
    out.append("\n---\n\n## The delivery flow\n")
    out.append(
        "The order the calls have to happen in. This is the part the endpoint list cannot tell "
        "you, and getting it wrong is the difference between stock that reconciles and stock "
        "that does not.\n"
    )
    out.append(
        "```\n"
        "1.  GET  /deliveries/today                      what am I delivering\n"
        "2.  POST /deliveries/{id}/out-for-delivery      I have set off\n"
        "3.  POST /deliveries/{id}/verify-location       where I am against the delivery site\n"
        "4.  POST /deliveries/{id}/confirm               what I counted at the gate\n"
        "5.  POST /deliveries/{id}/verify-customer-otp   the customer's code -> DONE\n"
        "```\n"
    )
    out.append(
        "**Step 4 does not complete the delivery.** It records the counts and nothing else: no "
        "stock moves, the order does not advance, the customer is not told. It exists so the app "
        "can be backgrounded between counting cylinders and the customer finding their code "
        "without losing what the driver entered. Safe to call again.\n"
    )
    out.append(
        "**Step 5 is the delivery.** Only here do the cylinders come off the merchant's books, "
        "the order become `DELIVERED`, and the customer get their notification. Until it "
        "succeeds, nothing has happened.\n"
    )

    out.append("\n### Where the customer's code comes from\n")
    out.append(
        "It is **not** sent by SMS when the driver confirms. It is generated when the office "
        "dispatches the van, and it reaches the customer inside their own app's "
        '"out for delivery" notification. The customer therefore has it before the driver '
        "arrives, and neither of them needs a signal at the gate.\n"
    )
    out.append(
        "A wrong code returns `422` and costs one attempt out of ten. After ten the slip can "
        "only be closed from the office, so show the driver how many tries are left rather than "
        "letting them exhaust it.\n"
    )

    out.append("\n### Statuses the app will see\n")
    out.append("| `status` | Meaning |")
    out.append("|---|---|")
    out.append(
        "| `pending` | Assigned to this driver - either not dispatched yet, or dispatched and "
        "not started. |"
    )
    out.append(
        "| `out_for_delivery` | The driver has pressed Out for delivery. Derived from the slip's "
        "`started_at`, not a status of its own. |"
    )
    out.append("| `completed` | Handed over and confirmed. |")
    out.append("| `failed` | Closed without delivering. Only the office can set this. |")

    out.append("\n### Errors worth handling by name\n")
    out.append("| `code` | HTTP | What happened |")
    out.append("|---|---|---|")
    out.append(
        "| `DELIVERY_NOT_FOUND` | 404 | Not this driver's delivery. Never 403 - ids are "
        "guessable, so the server will not confirm one exists. |"
    )
    out.append(
        "| `DELIVERY_NOT_READY` | 409 | The office has not dispatched the van. Nothing has left "
        "the godown yet. |"
    )
    out.append("| `DELIVERY_ALREADY_SETTLED` | 409 | Already delivered or failed. |")
    out.append(
        "| `DELIVERY_QUANTITY_EXCEEDS_ALLOCATION` | 422 | More was handed over than the van "
        "carries. A part delivery is fine - only the quantity the slip allocated is not a "
        "ceiling the driver can exceed. |"
    )
    out.append(
        "| `DELIVERY_ITEM_NOT_ON_SLIP` | 422 | A cylinder type that is not on this slip. |"
    )
    out.append(
        "| `DELIVERY_EMPTIES_EXCEED_LOAD` | 422 | More empties than cylinders on the slip. |"
    )
    out.append("| `DELIVERY_CODE_LOCKED` | 409 | Ten wrong codes. The office has to close it. |")
    out.append(
        "| `DRIVER_HAS_ACTIVE_DELIVERIES` | 409 | Cannot go off duty with a van still out. |"
    )
    out.append("")

    # --- endpoints ----------------------------------------------------------------------------
    paths = {p: ops for p, ops in schema["paths"].items() if p.startswith(PREFIX)}
    for title, blurb, markers in SECTIONS:
        selected = sorted(
            (p, verb, op)
            for p, ops in paths.items()
            for verb, op in ops.items()
            if any(m in p.replace(PREFIX, "") for m in markers)
        )
        if not selected:
            continue
        out.append(f"\n---\n\n## {title}\n")
        out.append(blurb + "\n")
        for path, verb, op in selected:
            short = path.replace(PREFIX, "")
            out.append(f"\n### `{verb.upper()} {short}`\n")
            if op.get("summary"):
                out.append(f"**{op['summary']}**\n")
            if op.get("description"):
                out.append(op["description"].strip() + "\n")

            params = [q for q in op.get("parameters", []) if q.get("in") == "query"]
            if params:
                out.append("\n**Query parameters**\n")
                out.append("| Name | Type | Required | Notes |")
                out.append("|---|---|---|---|")
                for q in params:
                    out.append(
                        f"| `{q['name']}` | {_type_of(q.get('schema', {}))} | "
                        f"{'yes' if q.get('required') else 'no'} | {q.get('description', '')} |"
                    )
                out.append("")

            body = _body_schema(op)
            if body is not None:
                rows = _fields_table(body, components)
                out.append("\n**Request body**")
                out.extend(rows or ["", "_No fields - send `{}`._"])
                out.append("")

            response = _response_schema(op)
            if response is not None:
                target = _deref(response, components)
                if target.get("type") == "array":
                    out.append("\n**Response** - an array of:")
                    target = _deref(target.get("items", {}), components)
                else:
                    out.append("\n**Response**")
                rows = _fields_table(target, components)
                out.extend(rows or ["", "_Empty body._"])
                out.append("")

            codes = sorted(c for c in op.get("responses", {}) if c.isdigit() and int(c) >= 400)
            if codes:
                out.append(f"\n**Error statuses**: {', '.join(f'`{c}`' for c in codes)}\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(paths)} paths)")


if __name__ == "__main__":
    main()
