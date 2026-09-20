"""Ansible filter that renders a value as a literal Docker Compose dotenv token.

Docker Compose reads ``.env`` files with the compose-go dotenv parser. In
unquoted and double-quoted values that parser performs ``$`` interpolation and
shell-style escape processing, so a raw Vault secret containing ``$``, a
backslash or a double quote would be reinterpreted instead of reaching the
container verbatim. That breaks authentication whenever the database role was
provisioned from the raw Ansible value while the container receives the
dotenv-parsed value.

``dotenv_literal`` wraps the value in double quotes and escapes exactly the
characters the parser would otherwise transform:

* ``\\``  -> ``\\\\``  keeps escape sequences (``\\n``, ``\\\\``, ...) literal
* ``"``   -> ``\\"``    stops the value from terminating the quoted token
* ``$``   -> ``$$``     the interpolation pass resolves ``$$`` to a literal ``$``
* CR/LF   -> ``\\r`` / ``\\n`` keep the generated ``.env`` single-line

The returned string includes the surrounding double quotes because it is meant
to be the whole right-hand side of a ``KEY=...`` line:

    N8N_DB_PASSWORD={{ postgres_n8n_password | dotenv_literal }}

For any input, ``docker compose`` therefore observes the original value
byte-for-byte. This filter never logs or echoes the value; callers keep
``no_log: true`` on the tasks that render it.
"""

from __future__ import annotations


def dotenv_literal(value: object) -> str:
    """Return ``value`` as a dotenv token preserving it literally under Compose."""
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = str(value)
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "$$")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return '"' + escaped + '"'


class FilterModule:
    """Expose the dotenv literal filter to Ansible templates."""

    def filters(self) -> dict:
        return {"dotenv_literal": dotenv_literal}
