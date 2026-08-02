"""Prompt primitives.

Wrapping questionary here does two things. It keeps every prompt's look and
cancel behaviour consistent, and it gives the wizard a seam that tests can
drive without a terminal: an :class:`Answerer` can be swapped for a scripted
one, so wizard flow is testable without simulating keystrokes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import questionary
from questionary import Choice

from ..exceptions import UsageError

#: Consistent styling for every prompt.
STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:cyan"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("instruction", "fg:#888888"),
        ("text", ""),
    ]
)


@dataclass(frozen=True)
class Option:
    """One selectable answer.

    Args:
        value: What the answer means to the caller.
        label: Text shown to the user.
        description: Short hint rendered after the label.
    """

    value: Any
    label: str
    description: str = ""

    def to_choice(self) -> Choice:
        title = f"{self.label}  —  {self.description}" if self.description else self.label
        return Choice(title=title, value=self.value)


class Answerer:
    """Asks the user questions.

    Every method returns the answer or raises :class:`UsageError` if the user
    cancels, so a Ctrl-C during setup exits cleanly rather than raising a
    ``KeyboardInterrupt`` traceback through the CLI.
    """

    def select(
        self,
        message: str,
        options: Sequence[Option],
        *,
        default: Any = None,
    ) -> Any:
        """Ask the user to pick one option."""
        choices = [option.to_choice() for option in options]
        default_choice = next(
            (choice for choice, option in zip(choices, options, strict=True) if option.value == default),
            None,
        )
        return self._unwrap(
            questionary.select(
                message, choices=choices, default=default_choice, style=STYLE, qmark="?"
            ).ask()
        )

    def multiselect(
        self,
        message: str,
        options: Sequence[Option],
        *,
        default: Sequence[Any] = (),
    ) -> list[Any]:
        """Ask the user to pick any number of options."""
        selected = set(default)
        choices = [
            Choice(
                title=(f"{o.label}  —  {o.description}" if o.description else o.label),
                value=o.value,
                checked=o.value in selected,
            )
            for o in options
        ]
        return self._unwrap(
            questionary.checkbox(
                message,
                choices=choices,
                style=STYLE,
                qmark="?",
                instruction="(space to toggle, enter to confirm)",
            ).ask()
        )

    def confirm(self, message: str, *, default: bool = True) -> bool:
        """Ask a yes/no question."""
        return self._unwrap(
            questionary.confirm(message, default=default, style=STYLE, qmark="?").ask()
        )

    def text(
        self,
        message: str,
        *,
        default: str = "",
        validate: Callable[[str], bool | str] | None = None,
    ) -> str:
        """Ask for a line of text.

        Args:
            message: The prompt.
            default: Pre-filled value.
            validate: Returns True when valid, or an error string to display.
        """
        return self._unwrap(
            questionary.text(
                message, default=default, validate=validate, style=STYLE, qmark="?"
            ).ask()
        ).strip()

    @staticmethod
    def _unwrap(answer: Any) -> Any:
        """Convert questionary's cancel sentinel into a clean exit.

        questionary returns ``None`` when the user presses Ctrl-C.
        """
        if answer is None:
            raise UsageError("Setup cancelled.", exit_code=130)
        return answer


class ScriptedAnswerer(Answerer):
    """An :class:`Answerer` that replays pre-recorded answers.

    Used by the test suite to exercise wizard flow — including the branches
    where one answer changes which questions come next — without a terminal.
    """

    def __init__(self, answers: dict[str, Any]) -> None:
        """
        Args:
            answers: Answers keyed by a distinctive fragment of the prompt.
        """
        self.answers = answers
        self.asked: list[str] = []

    def _lookup(self, message: str, fallback: Any) -> Any:
        self.asked.append(message)
        for key, value in self.answers.items():
            if key.lower() in message.lower():
                return value
        return fallback

    def select(self, message: str, options: Sequence[Option], *, default: Any = None) -> Any:
        return self._lookup(message, default if default is not None else options[0].value)

    def multiselect(
        self, message: str, options: Sequence[Option], *, default: Sequence[Any] = ()
    ) -> list[Any]:
        return list(self._lookup(message, list(default)))

    def confirm(self, message: str, *, default: bool = True) -> bool:
        return bool(self._lookup(message, default))

    def text(
        self,
        message: str,
        *,
        default: str = "",
        validate: Callable[[str], bool | str] | None = None,
    ) -> str:
        return str(self._lookup(message, default))
