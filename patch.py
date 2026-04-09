import difflib
import os
import re
import sys

PATCH_PATH = sys.argv[1] if len(sys.argv) > 1 else "model_patch.txt"

ADD_RE = re.compile(r"^\*\*\* Add File:\s*(.+?)\s*$")
DEL_RE = re.compile(r"^\*\*\* Delete File:\s*(.+?)\s*$")
BEGIN_RE = re.compile(r"^\*\*\* Begin Patch\s*$")
END_RE = re.compile(r"^\*\*\* End Patch\s*$")

def norm(p: str) -> str:
    # normalize patch paths to current OS separator
    p = p.strip().replace("/", os.sep)
    return os.path.normpath(p)

def read_file_lines(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except FileNotFoundError:
        return []

def write_file(path, lines):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(lines))

def diff_line_counts(old_lines, new_lines):
    """
    Returns (added, removed) to transform old -> new.
    Replacements count as removed + added.
    """
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    add = rem = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            add += (j2 - j1)
        elif tag == "delete":
            rem += (i2 - i1)
        elif tag == "replace":
            rem += (i2 - i1)
            add += (j2 - j1)
    return add, rem

with open(PATCH_PATH, "r", encoding="utf-8") as f:
    raw = f.readlines()

i = 0
changed = []
total_add = 0
total_rem = 0

while i < len(raw):
    line = raw[i]
    if not BEGIN_RE.match(line):
        i += 1
        continue

    i += 1
    if i >= len(raw):
        break

    m_add = ADD_RE.match(raw[i])
    m_del = DEL_RE.match(raw[i])

    if m_del:
        path = norm(m_del.group(1))
        old_exists = os.path.exists(path)
        old_lines = read_file_lines(path) if old_exists else []

        # advance to End Patch
        while i < len(raw) and not END_RE.match(raw[i]):
            i += 1

        if old_exists:
            os.remove(path)

        add, rem = 0, len(old_lines)
        total_add += add
        total_rem += rem
        changed.append(("DELETE", path, add, rem))
        i += 1
        continue

    if m_add:
        path = norm(m_add.group(1))
        old_exists = os.path.exists(path)
        old_lines = read_file_lines(path) if old_exists else []

        i += 1
        content_lines = []
        while i < len(raw) and not END_RE.match(raw[i]):
            l = raw[i]
            if l.startswith("+"):
                content_lines.append(l[1:])
            i += 1

        write_file(path, content_lines)

        add, rem = diff_line_counts(old_lines, content_lines)
        total_add += add
        total_rem += rem

        action = "REPLACE" if old_exists else "ADD"
        changed.append((action, path, add, rem))

        i += 1
        continue

    # Unknown block type; skip to end patch
    while i < len(raw) and not END_RE.match(raw[i]):
        i += 1
    i += 1

print("Applied model patch.")
for action, path, add, rem in changed:
    print(f'{action:7} {path} | Changed: +{add} -{rem}')
print(f"\nTOTAL CHANGED: +{total_add} -{total_rem}")