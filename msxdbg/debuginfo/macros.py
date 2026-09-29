"""Offline macro-definition contracts used before expression parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional, Sequence, Tuple

from .diagnostics import Diagnostic, Origin, ParseResult
from .model import ImageId, Resolution, ResolutionStatus


@dataclass(frozen=True)
class MacroToken:
    """Lexical replacement token independent of the evaluator."""

    lexeme: str


@dataclass(frozen=True)
class MacroContext:
    """Known image and translation-unit preprocessing context."""

    image: Optional[ImageId] = None
    translation_unit: Optional[str] = None


@dataclass(frozen=True)
class MacroDefinition:
    """Object-like or function-like macro with its source provenance."""

    name: str
    parameters: Optional[Tuple[str, ...]]
    replacement: Tuple[MacroToken, ...]
    origin: Origin
    context: MacroContext

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("macro name must not be empty")
        if self.parameters is not None:
            object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "replacement", tuple(self.replacement))


@dataclass(frozen=True)
class MacroCatalog:
    """Immutable collection that preserves conflicting definitions."""

    definitions: Tuple[MacroDefinition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "definitions", tuple(self.definitions))

    def lookup(
        self,
        name: str,
        context: MacroContext,
    ) -> Resolution[MacroDefinition]:
        """Resolve a macro without collapsing ambiguous definitions."""

        candidates = [definition for definition in self.definitions
                      if definition.name == name
                      and (definition.context.image is None or definition.context.image == context.image)
                      and (definition.context.translation_unit is None
                           or definition.context.translation_unit == context.translation_unit)]
        if candidates:
            specificity = max((item.context.image is not None) +
                              (item.context.translation_unit is not None) for item in candidates)
            candidates = [item for item in candidates if
                          (item.context.image is not None) +
                          (item.context.translation_unit is not None) == specificity]
        status = (ResolutionStatus.MISSING if not candidates else
                  ResolutionStatus.UNIQUE if len(candidates) == 1 else ResolutionStatus.AMBIGUOUS)
        return Resolution(status, tuple(candidates))

    def names(self, context: MacroContext) -> Tuple[str, ...]:
        """Return macro names visible in a known context."""

        names = {definition.name for definition in self.definitions}
        return tuple(sorted(name for name in names
                            if self.lookup(name, context).status == ResolutionStatus.UNIQUE))


def parse_macro_definitions(
    text: str,
    origin: Path,
    context: MacroContext,
) -> ParseResult[Tuple[MacroDefinition, ...]]:
    """Parse supported definitions without invoking a preprocessor."""

    definitions = []
    diagnostics = []
    logical_lines = []
    pending = ""
    pending_line = 1
    for line_number, physical in enumerate(text.splitlines(), 1):
        if not pending:
            pending_line = line_number
        stripped = physical.rstrip()
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
        else:
            logical_lines.append((pending_line, pending + physical))
            pending = ""
    if pending:
        logical_lines.append((pending_line, pending))

    conditional_depth = 0
    token_pattern = re.compile(r"0[xX][0-9A-Fa-f]+|#[0-9A-Fa-f]+|[A-Za-z_]\w*|\d+|<<|>>|[-+*/%&|^~(),\[\]]")
    for line_number, line in logical_lines:
        directive = re.match(r"^\s*#\s*(\w+)", line)
        if directive and directive.group(1) in ("if", "ifdef", "ifndef"):
            conditional_depth += 1
            diagnostics.append(Diagnostic("macro.conditional-unsupported", "warning",
                "conditional macro branch was not collected", (Origin(origin, line_number, "directive"),)))
            continue
        if directive and directive.group(1) == "endif":
            conditional_depth = max(0, conditional_depth - 1); continue
        if conditional_depth:
            continue
        undef = re.match(r"^\s*#\s*undef\s+([A-Za-z_]\w*)\s*$", line)
        if undef:
            definitions = [item for item in definitions if item.name != undef.group(1)]
            continue
        match = re.match(r"^\s*#\s*define\s+([A-Za-z_]\w*)(\(([^)]*)\))?\s*(.*?)\s*$", line)
        if not match:
            continue
        name, function_marker, parameter_text, replacement_text = match.groups()
        parameters = None
        if function_marker is not None:
            parameters = tuple(item.strip() for item in parameter_text.split(",") if item.strip())
            if len(set(parameters)) != len(parameters):
                diagnostics.append(Diagnostic("macro.duplicate-parameter", "warning",
                    f"macro {name} has duplicate parameters", (Origin(origin, line_number, "define"),)))
                continue
        if "##" in replacement_text or "..." in replacement_text or re.search(r"#\s*[G-Zg-z_]", replacement_text):
            diagnostics.append(Diagnostic("macro.operator-unsupported", "warning",
                f"macro {name} uses unsupported preprocessor operators", (Origin(origin, line_number, "define"),)))
            continue
        lexemes = token_pattern.findall(replacement_text)
        compact = re.sub(r"\s+", "", replacement_text)
        if "".join(lexemes) != compact:
            diagnostics.append(Diagnostic("macro.token-unsupported", "warning",
                f"macro {name} contains unsupported tokens", (Origin(origin, line_number, "define"),)))
            continue
        definitions.append(MacroDefinition(name, parameters,
            tuple(MacroToken(item) for item in lexemes),
            Origin(origin, line_number, "define"), context))
    return ParseResult(tuple(definitions), tuple(diagnostics))


__all__ = [
    "MacroCatalog",
    "MacroContext",
    "MacroDefinition",
    "MacroToken",
    "parse_macro_definitions",
]
