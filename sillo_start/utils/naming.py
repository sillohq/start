"""Name conversions and validation.

Generators receive one name from the user and need it in several shapes at
once: ``BlogPost`` the class, ``blog_post`` the module, ``blog-post`` the
directory, ``blog_posts`` the table. Centralising the conversions keeps those
consistent across every generator and template.
"""

from __future__ import annotations

import keyword
import re

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")

#: Irregular plurals worth getting right; everything else follows the rules below.
_IRREGULAR_PLURALS = {
    "person": "people",
    "child": "children",
    "man": "men",
    "woman": "women",
    "tooth": "teeth",
    "foot": "feet",
    "mouse": "mice",
    "goose": "geese",
}

_UNCOUNTABLE = {"equipment", "information", "money", "series", "species", "data"}


def split_words(value: str) -> list[str]:
    """Split an identifier written in any common style into lowercase words.

    Handles camelCase, PascalCase, snake_case, kebab-case and space-separated
    text, including acronym runs such as ``APIKey`` -> ``["api", "key"]``.
    """
    spaced = _CAMEL_BOUNDARY.sub(" ", value)
    parts = _NON_ALNUM.sub(" ", spaced).split()
    return [part.lower() for part in parts if part]


def to_snake(value: str) -> str:
    """``BlogPost`` -> ``blog_post``."""
    return "_".join(split_words(value))


def to_pascal(value: str) -> str:
    """``blog_post`` -> ``BlogPost``."""
    return "".join(word.capitalize() for word in split_words(value))


def to_camel(value: str) -> str:
    """``blog_post`` -> ``blogPost``."""
    pascal = to_pascal(value)
    return pascal[:1].lower() + pascal[1:] if pascal else ""


def to_kebab(value: str) -> str:
    """``BlogPost`` -> ``blog-post``."""
    return "-".join(split_words(value))


def to_title(value: str) -> str:
    """``blog_post`` -> ``Blog Post``."""
    return " ".join(word.capitalize() for word in split_words(value))


def to_human(value: str) -> str:
    """``blog_post`` -> ``Blog post`` — sentence case, for labels and prose."""
    words = split_words(value)
    if not words:
        return ""
    return " ".join([words[0].capitalize(), *words[1:]])


def pluralize(word: str) -> str:
    """Pluralise a single English word well enough for table names.

    This is deliberately a small rule set rather than a dependency: it covers
    the shapes that appear in model names, and a developer can always override
    the table name in the generated model.
    """
    lowered = word.lower()
    if not lowered or lowered in _UNCOUNTABLE:
        return word
    if lowered in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[lowered]
    if lowered.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lowered.endswith("y") and len(word) > 1 and word[-2].lower() not in "aeiou":
        return word[:-1] + "ies"
    if lowered.endswith("f"):
        return word[:-1] + "ves"
    if lowered.endswith("fe"):
        return word[:-2] + "ves"
    return word + "s"


def table_name(model_name: str) -> str:
    """Derive a table name from a model name: ``BlogPost`` -> ``blog_posts``."""
    words = split_words(model_name)
    if not words:
        return ""
    return "_".join([*words[:-1], pluralize(words[-1])])


def is_valid_python_identifier(value: str) -> bool:
    """Report whether *value* can be used as a Python module or class name."""
    return value.isidentifier() and not keyword.iskeyword(value)


def is_valid_project_name(value: str) -> bool:
    """Report whether *value* is usable as both a directory and a package name.

    Project names are permitted to contain dashes because that is the
    convention for distribution names; :func:`package_name_for` converts to the
    importable form.
    """
    if not value or len(value) > 100:
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", value):
        return False
    return is_valid_python_identifier(package_name_for(value))


def package_name_for(project_name: str) -> str:
    """Derive the importable package name from a project name.

    ``my-cool-app`` -> ``my_cool_app``.
    """
    return re.sub(r"[.-]+", "_", project_name).strip("_").lower()


def distribution_name_for(project_name: str) -> str:
    """Derive the PyPI-style distribution name: ``my_cool_app`` -> ``my-cool-app``."""
    return re.sub(r"[_.]+", "-", project_name).strip("-").lower()


def ensure_suffix(value: str, suffix: str) -> str:
    """Append *suffix* unless *value* already ends with it, case-insensitively.

    Lets ``generate controller User`` and ``generate controller UserController``
    both produce ``UserController``.
    """
    if value.lower().endswith(suffix.lower()):
        return value
    return value + suffix
