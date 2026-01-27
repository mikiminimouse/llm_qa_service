"""Prompt manager for loading and formatting prompts."""

import logging
from pathlib import Path
from string import Template
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Manager for loading and formatting prompts from files.

    Supports:
    - System prompts (text files)
    - User prompt templates (text files with $variable substitution)
    - Validation rules (YAML files)
    """

    def __init__(self, prompts_dir: str = "prompts"):
        """
        Initialize prompt manager.

        Args:
            prompts_dir: Directory containing prompts.
        """
        self.prompts_dir = Path(prompts_dir)
        self._cache: dict[str, str] = {}

    def _load_file(self, relative_path: str) -> str:
        """
        Load file content with caching.

        Args:
            relative_path: Path relative to prompts_dir.

        Returns:
            File content.

        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        if relative_path in self._cache:
            return self._cache[relative_path]

        file_path = self.prompts_dir / relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        self._cache[relative_path] = content
        return content

    def get_system_prompt(self, name: str = "winner_extractor_v4") -> str:
        """
        Get system prompt by name.

        Args:
            name: Prompt name (without extension).

        Returns:
            System prompt content.
        """
        return self._load_file(f"system/{name}.txt")

    def get_user_prompt_template(self, name: str = "extract_winner_v4") -> str:
        """
        Get user prompt template by name.

        Args:
            name: Template name (without extension).

        Returns:
            User prompt template content.
        """
        return self._load_file(f"user/{name}.txt")

    def format_user_prompt(
        self,
        template_name: str = "extract_winner_v4",
        document_content: str = "",
        **kwargs,
    ) -> str:
        """
        Format user prompt with document content.

        Args:
            template_name: Template name (without extension).
            document_content: Document content to insert.
            **kwargs: Additional template variables.

        Returns:
            Formatted user prompt.
        """
        template_content = self.get_user_prompt_template(template_name)

        # Use Template for safe substitution
        template = Template(template_content)

        return template.safe_substitute(
            document_content=document_content,
            **kwargs,
        )

    def get_validation_rules(self, name: str = "rules_v2") -> dict:
        """
        Get validation rules from YAML file.

        Args:
            name: Rules file name (without extension).

        Returns:
            Validation rules dictionary.
        """
        content = self._load_file(f"validation/{name}.yaml")
        return yaml.safe_load(content)

    def clear_cache(self) -> None:
        """Clear the prompt cache."""
        self._cache.clear()
