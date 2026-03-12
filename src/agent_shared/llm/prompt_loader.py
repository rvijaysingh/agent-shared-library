"""
Prompt template loader.

Loads markdown template files from a caller-specified directory and performs
variable substitution using Python's {placeholder} format syntax via str.format_map().
This library ships no prompt files — the consuming agent owns its prompts/ directory.

Template syntax: {variable_name} in the template file is replaced with the
corresponding value from the variables dict passed to load().

Note on migration from gmail-to-trello: that agent used {{subject}} double-brace
syntax with str.replace(). New templates for this library should use {subject}
single-brace format_map() syntax instead.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptLoader:
    """Loads and renders markdown prompt templates from a directory."""

    def __init__(self, prompts_dir: str) -> None:
        """
        Args:
            prompts_dir: Absolute path to the consuming agent's prompts/ directory.
                This library ships no prompts — the caller provides the path.
        """
        self.prompts_dir = Path(prompts_dir)

    def load(
        self,
        template_name: str,
        variables: dict[str, str] | None = None,
    ) -> str:
        """
        Load a markdown template file and substitute {placeholder} variables.

        Args:
            template_name: Filename relative to prompts_dir (e.g. "card_name.md").
            variables: Dict mapping placeholder names to substitution values.
                If None, the template is returned as-is with no substitution.

        Returns:
            The rendered prompt string with all {placeholder} values replaced.

        Raises:
            FileNotFoundError: If the template file does not exist.
            KeyError: If the template contains a {placeholder} with no matching
                key in the variables dict.
        """
        path = self.prompts_dir / template_name
        if not path.exists():
            raise FileNotFoundError(
                f"Prompt template not found: {path}"
            )

        content = path.read_text(encoding="utf-8")
        logger.debug("Loaded template %s (%d chars)", template_name, len(content))

        if variables is None:
            return content

        # str.format_map raises KeyError naturally for missing placeholders.
        rendered = content.format_map(variables)
        logger.debug("Rendered template %s with %d variables", template_name, len(variables))
        return rendered
