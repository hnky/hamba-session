#!/usr/bin/env python3
"""Block tool calls that would write Azure secrets into the repository."""

import json
import re
import sys
from typing import NoReturn

WRITE_TOOLS = {
    "edit",
    "write",
    "create",
    "create_file",
    "str_replace",
    "str_replace_editor",
    "apply_patch",
    "multi_edit",
    "notebook_edit",
    "bash",
    "shell",
    "run_in_terminal",
}

CONTENT_KEYS = (
    "content",
    "file_text",
    "text",
    "new_str",
    "newString",
    "new_string",
    "newText",
    "code",
    "command",
    "patch",
    "input",
)

PATTERNS = [
    (
        re.compile(r"AccountKey\s*=\s*[A-Za-z0-9+/]{20,}={0,2}"),
        "a storage account key (AccountKey=)",
    ),
    (
        re.compile(
            r"DefaultEndpointsProtocol\s*=\s*https?\s*;.*AccountName\s*=", re.I
        ),
        "an Azure Storage connection string",
    ),
    (re.compile(r"SharedAccessSignature\s*=", re.I), "a shared access signature"),
    (
        re.compile(
            r"\bsv=\d{4}-\d{2}-\d{2}\b.*[?&]sig=[A-Za-z0-9%+/]{10,}", re.I
        ),
        "a SAS token (sv=... sig=...)",
    ),
    (
        re.compile(r"[?&]sig=[A-Za-z0-9%+/]{20,}={0,2}", re.I),
        "a SAS signature (sig=...)",
    ),
    (
        re.compile(
            r"\b(AZURE_STORAGE_KEY|AZURE_STORAGE_ACCOUNT_KEY|AZURE_STORAGE_CONNECTION_STRING"
            r"|AZURE_CLIENT_SECRET|ARM_CLIENT_SECRET)\b\s*[:=]\s*['\"]?[^\s'\"<${}]{8,}",
            re.I,
        ),
        "a hardcoded Azure credential environment value",
    ),
    (
        re.compile(
            r"\b(client_secret|clientSecret)\b\s*[:=]\s*['\"][^'\"<${}]{8,}['\"]"
        ),
        "a hardcoded client secret",
    ),
    (
        re.compile(r"\bInstrumentationKey\s*=\s*[0-9a-f-]{30,}", re.I),
        "an Application Insights instrumentation key",
    ),
]

PLACEHOLDER = re.compile(
    r"(<[^>]{1,60}>|\$\{[^}]{1,60}\}|\$\([^)]{1,60}\)|%[A-Z_]{3,40}%"
    r"|your[-_ ]?(key|secret|account|connection)"
    r"|replace[-_ ]?me|changeme|placeholder|example|dummy|fake|xxx+|\.\.\.)",
    re.I,
)

REASON = (
    "Blocked by the Hamba secrets guard: this write contains {found}.\n\n"
    "Hamba never stores Azure credentials. Storage access uses managed identity "
    "and RBAC, configured in Bicep.\n\n"
    "Use DefaultAzureCredential with the account endpoint instead of a key or "
    "connection string. If a setting really is needed, add the key name to "
    ".env.example with an empty value and wire it through Bicep and azure.yaml. "
    "Do not invent a plausible looking key to make the code run."
)


def allow() -> NoReturn:
    sys.exit(0)


def deny(found: str) -> NoReturn:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REASON.format(found=found),
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def collect_text(value: object, depth: int = 0) -> list[str]:
    """Flatten tool input into searchable text, whatever shape it arrives in."""
    if depth > 6:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        output: list[str] = []
        for key, item in value.items():
            if key in CONTENT_KEYS or isinstance(item, (dict, list)):
                output.extend(collect_text(item, depth + 1))
            elif isinstance(item, str):
                output.append(item)
        return output
    if isinstance(value, list):
        output = []
        for item in value:
            output.extend(collect_text(item, depth + 1))
        return output
    return []


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    tool = (payload.get("tool_name") or payload.get("toolName") or "").lower()
    if tool and not any(name in tool for name in WRITE_TOOLS):
        allow()

    tool_input = payload.get("tool_input", payload.get("toolInput", {}))
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, ValueError):
            tool_input = {"content": tool_input}

    for text in collect_text(tool_input):
        for pattern, description in PATTERNS:
            match = pattern.search(text)
            if match and not PLACEHOLDER.search(match.group(0)):
                deny(description)

    allow()


if __name__ == "__main__":
    main()
