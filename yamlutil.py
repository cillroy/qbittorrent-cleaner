# yamlutil.py - Surgical YAML key updates that preserve comments and unrelated keys.

import re

_BOOL_TRUE = {"true", "yes", "on"}
_BOOL_FALSE = {"false", "no", "off"}


def yaml_scalar(value):
    """Format a Python value as a YAML scalar (plain, quoted, or flow list)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(yaml_scalar(item) for item in value) + "]"
    text = str(value)
    needs_quotes = (
        text == ""
        or text.strip() != text
        or text.lstrip("-").isdigit()
        or text.lower() in _BOOL_TRUE | _BOOL_FALSE | {"null", "n", "y", "~"}
        or any(ch in text for ch in ":#\n\r,{}[]&*!|>%@`'\"")
        or text.startswith(("@", "`", "*", "&", "!", "%"))
    )
    if needs_quotes:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def parse_yaml_scalar(raw):
    text = (raw or "").strip()
    if text == "":
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        inner = text[1:-1]
        if text[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    low = text.lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    if low in ("null", "~"):
        return None
    if text.startswith("[") or text.startswith("{"):
        try:
            import yaml
            return yaml.safe_load(text)
        except Exception:
            return text
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def values_equal(left, right):
    if isinstance(left, bool) and isinstance(right, bool):
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    return left == right


def _newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def _split_keep(text):
    nl = _newline_of(text)
    # Keep a trailing newline if the original had one.
    parts = text.split(nl)
    ended = text.endswith(nl)
    if ended and parts and parts[-1] == "":
        parts = parts[:-1]
    return parts, nl, ended


def _join(parts, nl, ended):
    body = nl.join(parts)
    return body + nl if ended or not parts else body


def _indent_and_content(line):
    stripped = line.lstrip(" ")
    return len(line) - len(stripped), stripped


def _split_inline_comment(content):
    """Split 'key: value  # comment' into (code, comment_suffix)."""
    in_single = False
    in_double = False
    escaped = False
    for i, ch in enumerate(content):
        if in_double:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            continue
        if in_single:
            if ch == "'":
                in_single = False
            continue
        if ch == '"':
            in_double = True
        elif ch == "'":
            in_single = True
        elif ch == "#":
            code = content[:i].rstrip()
            suffix = content[i - (len(content[:i]) - len(content[:i].rstrip())):] if False else content[len(content[:i].rstrip()):]
            # suffix includes the spaces before '#'
            suffix = content[len(code):]
            return code, suffix
    return content, ""


def _parse_key_line(content):
    """Return (key, value_text) for a mapping line, or (None, None)."""
    code, _comment = _split_inline_comment(content)
    if not code or code.startswith("-"):
        return None, None
    if ":" not in code:
        return None, None
    key, _, rest = code.partition(":")
    key = key.strip()
    if not key or key.startswith("-"):
        return None, None
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1]
    return key, rest.strip()


def _find_mapping(parts, path):
    """Locate a nested mapping. Returns (header_idx, end_idx, child_indent).

    header_idx is the line of the innermost path key. end_idx is exclusive.
    child_indent is the indent used (or expected) for keys inside the mapping.
    """
    start = 0
    end = len(parts)
    header_idx = -1
    child_indent = 0
    min_indent = 0
    for depth, name in enumerate(path):
        found = None
        i = start
        while i < end:
            raw = parts[i]
            indent, content = _indent_and_content(raw)
            if not content.strip() or content.lstrip().startswith("#"):
                i += 1
                continue
            if indent < min_indent:
                break
            if indent != min_indent:
                i += 1
                continue
            key, _value = _parse_key_line(content)
            if key == name:
                found = i
                header_idx = i
                break
            i += 1
        if found is None:
            return None
        # Determine the block of this mapping (lines after the header until
        # a key at indent <= header indent).
        header_indent, _ = _indent_and_content(parts[found])
        j = found + 1
        seen_child = None
        while j < end:
            raw = parts[j]
            indent, content = _indent_and_content(raw)
            if not content.strip() or content.lstrip().startswith("#"):
                j += 1
                continue
            if indent <= header_indent:
                break
            if seen_child is None:
                seen_child = indent
            j += 1
        start = found + 1
        end = j
        min_indent = seen_child if seen_child is not None else header_indent + 2
        child_indent = min_indent
    return header_idx, end, child_indent


def get_yaml_scalar(text, path):
    """Return (found, value) for a nested scalar key."""
    if not path:
        return False, None
    parts, _nl, _ended = _split_keep(text)
    parent = path[:-1]
    leaf = path[-1]
    if parent:
        located = _find_mapping(parts, parent)
        if located is None:
            return False, None
        _header_idx, end, child_indent = located
        start = _header_idx + 1
    else:
        start = 0
        end = len(parts)
        child_indent = 0
        # top-level keys use the indent of the first mapping key
        for raw in parts:
            indent, content = _indent_and_content(raw)
            if content.strip() and not content.lstrip().startswith("#"):
                child_indent = indent
                break
    i = start
    while i < end:
        raw = parts[i]
        indent, content = _indent_and_content(raw)
        if not content.strip() or content.lstrip().startswith("#"):
            i += 1
            continue
        if indent != child_indent:
            i += 1
            continue
        key, value_text = _parse_key_line(content)
        if key == leaf:
            return True, parse_yaml_scalar(value_text)
        i += 1
    return False, None


def update_yaml_scalar(text, path, value):
    """Set a nested scalar key, preserving comments and other keys.

    If the key exists, only the value is replaced (trailing comments stay).
    If it is missing, it is inserted at the end of the parent mapping.
    Intermediate mappings must already exist.
    """
    if not path:
        raise ValueError("empty YAML path")
    parts, nl, ended = _split_keep(text)
    parent = path[:-1]
    leaf = path[-1]
    rendered = yaml_scalar(value)

    if parent:
        located = _find_mapping(parts, parent)
        if located is None:
            raise ValueError("YAML path not found: %s" % ".".join(parent))
        header_idx, end, child_indent = located
        start = header_idx + 1
    else:
        start = 0
        end = len(parts)
        child_indent = 0
        for raw in parts:
            indent, content = _indent_and_content(raw)
            if content.strip() and not content.lstrip().startswith("#"):
                child_indent = indent
                break

    i = start
    last_child = start - 1
    while i < end:
        raw = parts[i]
        indent, content = _indent_and_content(raw)
        if not content.strip() or content.lstrip().startswith("#"):
            i += 1
            continue
        if indent == child_indent:
            last_child = i
            key, _value_text = _parse_key_line(content)
            if key == leaf:
                code, comment = _split_inline_comment(content)
                key_part, _, _rest = code.partition(":")
                new_content = "%s: %s" % (key_part.rstrip(), rendered)
                if comment.strip().startswith("#") or comment:
                    # Keep original spacing + comment
                    if comment:
                        new_content = new_content + comment
                parts[i] = (" " * indent) + new_content
                return _join(parts, nl, ended)
        i += 1

    new_line = ("%s%s: %s" % (" " * child_indent, leaf, rendered))
    insert_at = last_child + 1 if last_child >= start else end
    # If the block ended by walking past comments, insert before the end index
    # (which is the next sibling). insert_at is already within [start, end].
    if insert_at < start:
        insert_at = end
    parts.insert(insert_at, new_line)
    return _join(parts, nl, ended)



def ensure_yaml_mapping(text, path):
    """Create missing intermediate mappings so path exists as an empty map."""
    if not path:
        return text
    parts, nl, ended = _split_keep(text)
    # If the full path already exists as a mapping or key, do nothing.
    located = _find_mapping(parts, path)
    if located is not None:
        return text
    # Create parents from the top down.
    result = text
    for depth in range(1, len(path) + 1):
        prefix = path[:depth]
        parts, nl, ended = _split_keep(result)
        if _find_mapping(parts, prefix) is not None:
            continue
        parent = prefix[:-1]
        leaf = prefix[-1]
        if parent:
            located = _find_mapping(parts, parent)
            if located is None:
                raise ValueError("YAML path not found: %s" % ".".join(parent))
            header_idx, end, child_indent = located
        else:
            # Insert a new top-level key before 'rules:' if present, else at end.
            child_indent = 0
            end = len(parts)
            for i, raw in enumerate(parts):
                indent, content = _indent_and_content(raw)
                if indent == 0:
                    key, _ = _parse_key_line(content)
                    if key == "rules":
                        end = i
                        break
        new_line = "%s%s:" % (" " * child_indent, leaf)
        parts, nl, ended = _split_keep(result)
        # Recompute end for current text
        if parent:
            _header_idx, end, child_indent = _find_mapping(parts, parent)
        else:
            end = len(parts)
            for i, raw in enumerate(parts):
                indent, content = _indent_and_content(raw)
                if indent == 0:
                    key, _ = _parse_key_line(content)
                    if key == "rules":
                        end = i
                        break
        parts.insert(end, new_line)
        result = _join(parts, nl, ended)
    return result


def apply_yaml_updates(text, updates):
    """Apply (path, value) updates, skipping keys whose value is already equal."""
    changed = []
    result = text
    for path, value in updates:
        found, current = get_yaml_scalar(result, path)
        if found and values_equal(current, value):
            continue
        if len(path) > 1:
            result = ensure_yaml_mapping(result, path[:-1])
        result = update_yaml_scalar(result, path, value)
        changed.append(".".join(path))
    return result, changed
