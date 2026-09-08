# Which parser reads a file, and how their results become one project.

from __future__ import annotations

from collections.abc import Iterable

from .ast import AST
from .csv_parser import parse_csv_sources
from .yaml_parser import parse_yaml_sources

# What a suite may be written as, and which of those the yaml reader takes.
# `find_files` gates on exactly these and then classifies by content, so a file's name
# says nothing about whether it is ours.
YAML = (".yaml", ".yml")
SUITE = (".csv", *YAML)


def is_yaml(uri: str) -> bool:
    """Whether a uri or a path names a yaml file, however it is cased."""
    return uri.lower().endswith(YAML)


def _merge(into: AST, other: AST) -> None:
    into.kinds.update(other.kinds)
    into.test_cases += other.test_cases
    into.modules += other.modules
    into.elements += other.elements
    into.error_definitions += other.error_definitions
    into.issues += other.issues


def parse_sources(files: Iterable[tuple[str, str]]) -> AST:
    """One project, whatever its files are written as.

    Names resolve across formats because the runner keys everything by name and picks a
    reader per file, so a module defined in yaml is callable from a csv.

    One file at a time, in the order given, because that order decides which of two
    definitions sharing a name is the one that wins — and so which of them a
    `duplicate-module` points at.
    """
    ast = AST()
    for source in files:
        if source[0].lower().endswith(".csv"):
            _merge(ast, parse_csv_sources([source]))
        elif is_yaml(source[0]):
            _merge(ast, parse_yaml_sources([source]))
    return ast
