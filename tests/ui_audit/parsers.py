"""HTML template + JS string-literal parsers for the UI handler audit.

Intentionally uses only the standard library — no new dependency on
``beautifulsoup4``. The scanning needs are narrow (locate clickable elements
and their ``data-*-action`` attributes, pull ``id`` attributes, find ``href``
values starting with ``#``) so ``html.parser`` is sufficient and keeps the
audit cheap to run in CI.

The JS side is equally pragmatic: extract every single-quoted, double-quoted
or backtick-quoted string literal from a file, plus enumerate the dataset
families any JS source mentions. We then check whether each action value
referenced in a template appears as a literal inside a JS file that also
references the matching family (via ``dataset.Xaction`` or
``[data-x-action]``). This is a deliberately loose reachability test — false
positives are cheap to allowlist, while false negatives would defeat the
point of the audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# --- Template parsing --------------------------------------------------------


@dataclass(frozen=True)
class Clickable:
    """A single clickable element discovered in a template."""

    template: str  # file path relative to repo root
    line: int
    tag: str  # "button" | "a" | other
    attrs: tuple[tuple[str, str | None], ...]

    def attr(self, name: str) -> str | None:
        for key, value in self.attrs:
            if key == name:
                return value
        return None

    def has_attr(self, name: str) -> bool:
        return any(key == name for key, _ in self.attrs)

    def data_action_family(self) -> tuple[str, str] | None:
        """Return (family, action_value) if this element has data-X-action.

        ``family`` is the dataset-style name (``plugin`` for
        ``data-plugin-action``). Returns ``None`` otherwise.
        """

        for key, value in self.attrs:
            if not key.startswith("data-") or not key.endswith("-action"):
                continue
            # Ignore generic "data-action" (no family) — no template uses it today.
            mid = key[len("data-") : -len("-action")]
            if not mid:
                continue
            if value is None:
                continue
            return mid, value
        return None


@dataclass
class TemplateScan:
    """Everything the audit needs from a single template."""

    path: Path
    clickables: list[Clickable] = field(default_factory=list)
    element_ids: set[str] = field(default_factory=set)


class _TemplateParser(HTMLParser):
    """Extract clickable elements + every ``id`` attribute."""

    CLICKABLE_TAGS = frozenset({"button", "a"})

    def __init__(self, template_rel: str) -> None:
        super().__init__(convert_charrefs=True)
        self.template_rel = template_rel
        self.clickables: list[Clickable] = []
        self.element_ids: set[str] = set()

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Stash every id we see, not just clickables, so anchor-href lookups
        # can succeed against <section id="...">, etc.
        for key, value in attrs:
            if key == "id" and value:
                # Jinja placeholders inside ids (``id="btn-{{ img.filename }}"``)
                # still count for orphan detection: strip any ``{{ ... }}`` so
                # we have a canonical form to compare anchor hrefs against.
                self.element_ids.add(_strip_jinja(value))

        if tag not in self.CLICKABLE_TAGS:
            # Non-<button>/<a> can still carry data-*-action attributes
            # (e.g. playlist toggle <button> yes, but also sometimes <div>). We
            # flag anything carrying any data-*-action attribute.
            has_action = any(
                key.startswith("data-") and key.endswith("-action") for key, _ in attrs
            )
            if not has_action:
                return

        line = self.getpos()[0]
        self.clickables.append(
            Clickable(
                template=self.template_rel,
                line=line,
                tag=tag,
                attrs=tuple(attrs),
            )
        )

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:  # noqa: D401 - HTMLParser override
        self._record(tag, attrs)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:  # noqa: D401 - HTMLParser override
        self._record(tag, attrs)


_JINJA_EXPR = re.compile(r"\{\{.*?\}\}")


def _strip_jinja(value: str) -> str:
    return _JINJA_EXPR.sub("", value).strip()


def parse_template(path: Path, repo_root: Path) -> TemplateScan:
    rel = path.relative_to(repo_root).as_posix()
    parser = _TemplateParser(rel)
    try:
        parser.feed(path.read_text(encoding="utf-8"))
    finally:
        parser.close()
    return TemplateScan(
        path=path,
        clickables=parser.clickables,
        element_ids=parser.element_ids,
    )


# --- JS parsing --------------------------------------------------------------


# Matches dataset reads of the form ``foo.dataset.pluginAction`` and captures
# ``pluginAction`` so we can map back to the kebab family ``plugin``.
_DATASET_READ = re.compile(r"dataset\.([a-zA-Z][a-zA-Z0-9]*)")

# Matches explicit selector strings like ``[data-plugin-action]``.
_SELECTOR = re.compile(r"\[data-([a-z0-9-]+)-action(?:[=\]~])")

# Match any single/double/backtick string literal. We deliberately do not try
# to parse template-literal interpolations — ``${action}`` stays inside the
# captured text and we just check ``in`` membership, so it does not matter.
_STRING_LITERAL = re.compile(
    r"""
    '(?P<sq>(?:\\.|[^'\\\n])*)' |
    "(?P<dq>(?:\\.|[^"\\\n])*)" |
    `(?P<bt>(?:\\.|[^`\\])*)`
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass
class ScriptScan:
    path: Path
    text: str
    literals: frozenset[str]
    dataset_families: frozenset[str]  # kebab form, e.g. "plugin", "history"
    selector_families: frozenset[str]
    getelementbyid_args: frozenset[str]
    literal_calls_to: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def action_families(self) -> frozenset[str]:
        return self.dataset_families | self.selector_families


def _camel_to_kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def parse_script(path: Path) -> ScriptScan:
    text = path.read_text(encoding="utf-8")

    literals: set[str] = set()
    for match in _STRING_LITERAL.finditer(text):
        literals.add(match.group("sq") or match.group("dq") or match.group("bt") or "")

    dataset_fams: set[str] = set()
    for match in _DATASET_READ.finditer(text):
        camel = match.group(1)
        if not camel.endswith("Action"):
            continue
        family_camel = camel[: -len("Action")]
        if not family_camel:
            continue
        dataset_fams.add(_camel_to_kebab(family_camel))

    selector_fams: set[str] = {m.group(1) for m in _SELECTOR.finditer(text)}

    # getElementById("foo") arguments — used for orphan-button detection.
    getid_args: set[str] = set()
    for match in re.finditer(r"""getElementById\(\s*["'`]([^"'`]+)["'`]\s*\)""", text):
        getid_args.add(match.group(1))
    # querySelector("#foo") / querySelectorAll("#foo") — same idea.
    for match in re.finditer(
        r"""querySelector(?:All)?\(\s*["'`]#([A-Za-z_][\w-]*)["'`]\s*\)""", text
    ):
        getid_args.add(match.group(1))

    return ScriptScan(
        path=path,
        text=text,
        literals=frozenset(literals),
        dataset_families=frozenset(dataset_fams),
        selector_families=frozenset(selector_fams),
        getelementbyid_args=frozenset(getid_args),
    )


# --- High-level audit helpers ------------------------------------------------


def collect_scripts(scripts_dir: Path) -> list[ScriptScan]:
    return [parse_script(p) for p in sorted(scripts_dir.rglob("*.js"))]


def collect_templates(templates_dir: Path, repo_root: Path) -> list[TemplateScan]:
    return [parse_template(p, repo_root) for p in sorted(templates_dir.rglob("*.html"))]


def script_handles_family(script: ScriptScan, family: str) -> bool:
    return family in script.action_families


def family_handlers(scripts: list[ScriptScan], family: str) -> list[ScriptScan]:
    return [s for s in scripts if script_handles_family(s, family)]


def id_is_referenced(scripts: list[ScriptScan], element_id: str) -> bool:
    if not element_id:
        return False
    return any(element_id in s.getelementbyid_args for s in scripts) or any(
        element_id in s.literals for s in scripts
    )
