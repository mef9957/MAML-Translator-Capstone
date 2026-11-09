# Purpose: Translate the small supported MAMLScript subset into browser JavaScript.

from __future__ import annotations

import re


_LISTENER = re.compile(r'^on\("(click|change|keydown|reach|timer)"(?:,\s*"([^"]+)")?(?:,\s*"([^"]+)")?\)\s*\{$')
_ACTION = re.compile(r'^(show|hide|swap)\("([^"]+)"(?:,\s*"([^"]+)")?\);$')


def convert_mamlscript(code: str) -> tuple[str, list[str]]:
    """Convert supported statements and report lines that cannot be translated."""
    output: list[str] = []
    warnings: list[str] = []
    listener_stack: list[str] = []

    for line_number, raw_line in enumerate(code.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        listener = _LISTENER.match(line)
        if listener:
            event, target, key = listener.groups()
            if event == "timer":
                output.append(f"setTimeout(() => {{")
                listener_stack.append(f"}}, {int(target or 0)});")
            elif event == "reach":
                warnings.append(f"Line {line_number}: reach listener is not implemented yet.")
            else:
                key_guard = f"if (event.key !== {key!r}) return;" if event == "keydown" and key else ""
                output.append(
                    f"document.getElementById({target!r})?.addEventListener({event!r}, (event) => {{ {key_guard}"
                )
                listener_stack.append("});")
            continue

        action = _ACTION.match(line)
        if action:
            name, first, second = action.groups()
            if name == "show":
                output.append(f"document.getElementById({first!r}).style.display = 'block';")
            elif name == "hide":
                output.append(f"document.getElementById({first!r}).style.display = 'none';")
            elif name == "swap" and second:
                output.append(f"document.getElementById({second!r}).textContent = {first!r};")
            else:
                warnings.append(f"Line {line_number}: invalid swap action.")
            continue

        if line == "}" and listener_stack:
            output.append(listener_stack.pop())
            continue
        warnings.append(f"Line {line_number}: unsupported MAMLScript statement: {line}")

    while listener_stack:
        output.append(listener_stack.pop())
        warnings.append("A missing closing brace was added to MAMLScript.")
    return "\n".join(output), warnings
