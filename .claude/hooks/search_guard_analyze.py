#!/usr/bin/env python3
import sys, os, re, json, shlex, glob

root = os.path.realpath(os.environ.get("BP_ROOT", "."))
try:
    data = json.load(sys.stdin)
except Exception:
    print("0"); print(""); print("0"); print("bm25"); print(""); sys.exit(0)
tool = data.get("tool_name") or ""
ti = data.get("tool_input") or {}

# D2/D3: classify a pattern by CONSTRUCT, not "has metacharacters". A
# character-class shorthand, bracket expression, quantifier, or anchor is a
# regex feature the BM25 \w+ tokenizer cannot honor (metachars vanish as
# delimiters; letters inside them survive as phantom tokens) -> grep is
# authoritative. Alternation (foo\|bar) and escaped literals are faithful
# in BM25 (measured) and stay routed to bm25. No knob (D3): this is a
# correctness fix.
def classify(pattern):
    if not pattern:
        return "bm25"
    if re.search(r"\\[wWdDsS]", pattern):          # \w \d \s \W \D \S
        return "grep"
    if re.search(r"(?<!\\)\[", pattern):            # [...] bracket expression
        return "grep"
    if re.search(r"(?<!\\)[+*?]", pattern):          # unescaped quantifier
        return "grep"
    if re.search(r"(?<!\\)\{[0-9]*,?[0-9]*\}", pattern):  # {n,m} quantifier
        return "grep"
    if re.search(r"(?<!\\)[\^$]", pattern):          # unescaped anchor
        return "grep"
    return "bm25"

# Ground truth = the persisted folder manifests (the exact set of
# indexed files, absolute paths). A path is "indexed" iff it is an indexed file
# or a directory that contains >=1 indexed file. This authoritatively honors
# every exclusion brainpalace actually applied (excluded subfolders are simply
# absent) with no hardcoded heuristics or config parsing that can drift.
def _load_index():
    files = set()
    for mp in glob.glob(os.path.join(root, ".brainpalace", "manifests", "*.json")):
        try:
            d = json.load(open(mp, encoding="utf-8"))
        except Exception:
            continue
        for k in (d.get("files") or {}):
            files.add(os.path.realpath(k))
    dirs = set()
    for f in files:                        # every ancestor dir of an indexed file
        d = os.path.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
    return files, dirs

_FILES, _DIRS = _load_index()

# A1: resolve() is the realpath ap that indexed() already computed internally
# and threw away, returning only a bool. D4 needs that exact absolute value to
# build the --file-paths scope glob -- deriving it a second time from the raw
# (possibly relative) grep operand is how the scope silently goes wrong.
def resolve(path):
    if not path:
        return root                        # no path -> search cwd == project root
    p = os.path.expanduser(path)
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p))

def indexed(ap):
    if _FILES or _DIRS:                     # manifest present -> authoritative
        return ap in _FILES or ap in _DIRS
    # fallback (manifest missing/unreadable): enforce inside root, allow outside
    return ap == root or ap.startswith(root + os.sep)

# D4/D5/D10: build the --file-paths scope. D4 -- patterns MUST be
# absolute-anchored (a relative pattern returns 0 hits, which trips the
# zero-hit->ALLOW branch and silently disables the guard). D5 -- scope and
# include-type combine into ONE glob per (path x include) pair, because comma
# is OR not AND (`<a>/*,*.tsx` matches either set, not their intersection);
# multiple paths/includes join as the comma-OR cross-product. D10 -- a bare
# include with no path (e.g. `--include=*.tsx` alone) needs no root anchor:
# it is a pure extension filter over the whole indexed set, verified
# equivalent to `--file-paths "*.tsx"` directly.
def build_scope(resolved_paths, includes):
    if resolved_paths:
        incs = includes or [""]
        globs = [ap + (inc if inc else "*") for ap in resolved_paths for inc in incs]
    elif includes:
        globs = list(includes)
    else:
        globs = []
    seen = set(); out = []
    for g in globs:
        if g not in seen:
            seen.add(g); out.append(g)
    return out

# --- spec D1/D2: segment a Bash command on shell operators before analyzing --
# The bug this file exists to fix: the old operand loop ran to the end of the
# WHOLE command line, so `;`/`|`/redirections/a second `grep` all got read as
# operands of the FIRST grep. shlex.split() (no punctuation_chars) glues an
# operator straight onto an adjacent word when there's no surrounding
# whitespace (`head -20;` tokenizes as one token `-20;`, not `-20` + `;`) --
# real shell input routinely looks like that, so a naive split on token=="; "
# would still miss it. shlex.shlex(..., punctuation_chars=True) tokenizes
# shell metacharacters (`;|&<>`) as their own tokens regardless of adjacent
# whitespace, and groups a run of them into one token (`&&`, `||`, `>>`,
# `2>&1`'s `>&`) the same way a shell would -- verified empirically this
# session. Literal newlines (multi-line Bash-tool commands are common) don't
# survive punctuation-mode shlex as a token at all (they're plain whitespace),
# so each physical line is tokenized separately and a "\n" sentinel is spliced
# between them to give segmentation something to split on.
_OPERATORS = {";", "|", "||", "&&", "&", "\n"}
_REDIR = re.compile(r"^\d*[<>]")  # D2: a redirection token (optionally fd-prefixed)


def _tokenize_line(line):
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except Exception:
        return line.split()


def tokenize(cmdline):
    toks = []
    lines = (cmdline or "").split("\n")
    for idx, line in enumerate(lines):
        toks.extend(_tokenize_line(line))
        if idx != len(lines) - 1:
            toks.append("\n")
    return toks


def split_segments(toks):
    segments = []
    current = []
    for t in toks:
        if t in _OPERATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(t)
    if current:
        segments.append(current)
    return segments


def strip_redirections(seg):
    """D2: drop a redirection token and the operand it targets. Under
    punctuation-mode shlex a redirection is ALWAYS split from its target
    (`2>/dev/null` -> "2", ">", "/dev/null"; `> out.txt` -> ">", "out.txt"),
    so eating the token right after any `_REDIR` match is uniformly correct
    -- there is no remaining single-token glued form to special-case. A bare
    leading fd digit (the "2" in "2" ">" "/dev/null") is only dropped when
    the NEXT token is itself a redirection operator, so an ordinary numeric
    operand/path token is never mistaken for one.
    """
    out = []
    i = 0
    n = len(seg)
    while i < n:
        t = seg[i]
        if t.isdigit() and i + 1 < n and _REDIR.match(seg[i + 1]):
            i += 1
            continue
        if _REDIR.match(t):
            i += 1
            if i < n:
                i += 1  # drop the redirect's target operand too
            continue
        out.append(t)
        i += 1
    return out


def analyze_segment(seg):
    """Scan ONE already-redirection-stripped segment for a grep/rg-class
    invocation. Mirrors the original single-command operand loop, scoped to
    a segment instead of the whole line (A1/A2 of the spec) -- so a second
    `grep` in a later segment is never read as an operand of the first, and
    is independently classified rather than silently dropped.
    """
    n = len(seg)
    i = 0
    while i < n:
        base = seg[i].split("/")[-1]
        if base in ("rg", "ag"):
            term = ""; paths = []; got = False
            j = i + 1
            while j < n:
                t = seg[j]
                if t.startswith("-"): j += 1; continue
                if not got: term = t; got = True
                else: paths.append(t)
                j += 1
            return {"term": term, "paths": paths, "includes": []}
        if base in ("grep", "egrep", "fgrep"):
            recursive = False; got = False; term = ""; paths = []; includes = []
            j = i + 1
            while j < n:
                t = seg[j]
                if t == "--": j += 1; continue
                # A3: capture the VALUE of --include (both `--include=V` and
                # `--include V` forms), not just the fact it was passed.
                if t.startswith("--include="):
                    recursive = True
                    includes.append(t.split("=", 1)[1])
                    j += 1; continue
                if t == "--include":
                    recursive = True
                    j += 1
                    if j < n:
                        includes.append(seg[j]); j += 1
                    continue
                if t == "--recursive":
                    recursive = True
                    j += 1; continue
                if t.startswith("--"):
                    j += 1; continue
                if t.startswith("-") and len(t) > 1:
                    if "r" in t or "R" in t: recursive = True
                    j += 1; continue
                if not got: term = t; got = True
                else: paths.append(t)
                j += 1
            if recursive:
                return {"term": term, "paths": paths, "includes": includes}
            return None
        i += 1
    return None


is_search = False; term = ""; paths = []; includes = []
bash_classify_override = None  # D3/D4: set only by the Bash branch below

if tool == "Grep":
    is_search = True
    term = ti.get("pattern") or ""
    if ti.get("path"):
        paths.append(ti["path"])
    # A14: glob/type are the Grep tool --include equivalent -- the same gap
    # as A3, different input keys. Note the Grep tool pattern is ALWAYS a
    # ripgrep regex, so classify() (D2) is load-bearing on this path, not
    # optional.
    if ti.get("glob"):
        includes.append(ti["glob"])
    if ti.get("type"):
        # ripgrep --type shortcuts (e.g. "ts") have no canonical
        # type->extension table here (same drift risk D10 rejects for
        # --languages) -- mirror it as a plain extension glob. Exact for the
        # common single-extension case; for a type spanning >1 extension it
        # only narrows recall (never silently wrong: a miss just falls
        # through the zero-hit->ALLOW branch to native Grep).
        includes.append("*." + ti["type"])
elif tool == "Glob":
    # A15: Glob is a category error as a BM25 input -- a glob is a filename
    # matcher, BM25 is a content index, and a glob pattern contains no query
    # term at all (verified: Glob("**/*.tsx") -> bm25 "tsx" -> files that
    # merely MENTION "tsx", zero of which are .tsx files). There is no
    # correct BM25 mapping, so stop intercepting it: is_search stays False
    # and Glob passes straight through to the filesystem, which is where
    # filename matching belongs.
    pass
elif tool == "Bash":
    toks = tokenize(ti.get("command") or "")
    hits = []  # one dict per search-class segment: {term, paths, includes}
    for seg in split_segments(toks):
        seg = strip_redirections(seg)
        hit = analyze_segment(seg)
        if hit is not None:
            hits.append(hit)

    if hits:
        is_search = True
        # D3: classify EVERY search segment, not just the first -- a \d+ in
        # segment 2 must never be silently routed to bm25 just because
        # segment 1 was a plain literal.
        grep_hits = [h for h in hits if classify(h["term"]) == "grep"]
        bm25_hits = [h for h in hits if classify(h["term"]) != "grep"]
        if grep_hits:
            # D3: any grep-class pattern anywhere in the call -> allow the
            # WHOLE call (the hook denies/allows per call, not per segment).
            chosen = grep_hits[0]
            bash_classify_override = "grep"
        elif len(bm25_hits) > 1:
            # D4: more than one bm25-routable search segment survives -- a
            # denial can only carry the hits of ONE query, so answering just
            # one and denying the rest would leave the call half-answered.
            # Allow, with a systemMessage (wired in the bash caller).
            chosen = bm25_hits[0]
            bash_classify_override = "multi"
        else:
            chosen = bm25_hits[0]
            bash_classify_override = "bm25"
        term = chosen["term"]; paths = chosen["paths"]; includes = chosen["includes"]

if not is_search:
    print("0"); print(""); print("0"); print("bm25"); print(""); sys.exit(0)

resolved_paths = [resolve(p) for p in paths] if paths else []
enforce = indexed(root) if not resolved_paths else any(indexed(ap) for ap in resolved_paths)
scope = ",".join(build_scope(resolved_paths, includes))
final_classify = bash_classify_override if bash_classify_override else classify(term)

print("1"); print(term); print("1" if enforce else "0"); print(final_classify); print(scope)
