"""File-based context loader for testing."""

import os
from pathlib import Path
from typing import Optional

from domain.interfaces.context_loader import DocumentContext, IContextLoader


class FileContextLoader(IContextLoader):
    """
    File-based context loader for testing.

    Loads documents from local files.
    """

    def __init__(self, base_path: str = "."):
        """
        Initialize file context loader.

        Args:
            base_path: Base directory for file lookups.
        """
        self.base_path = Path(base_path)

    async def load(self, unit_id: str) -> Optional[DocumentContext]:
        """
        Load document context from file.

        Args:
            unit_id: Used as filename (with .md or .txt extension).

        Returns:
            DocumentContext if found, None otherwise.
        """
        # Try markdown first
        md_path = self.base_path / f"{unit_id}.md"
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8")
            return DocumentContext(
                unit_id=unit_id,
                content=content,
                source_file=str(md_path),
                content_type="markdown",
                metadata={"file_path": str(md_path)},
            )

        # Try txt
        txt_path = self.base_path / f"{unit_id}.txt"
        if txt_path.exists():
            content = txt_path.read_text(encoding="utf-8")
            return DocumentContext(
                unit_id=unit_id,
                content=content,
                source_file=str(txt_path),
                content_type="plain_text",
                metadata={"file_path": str(txt_path)},
            )

        # Try html
        html_path = self.base_path / f"{unit_id}.html"
        if html_path.exists():
            content = html_path.read_text(encoding="utf-8")
            return DocumentContext(
                unit_id=unit_id,
                content=content,
                source_file=str(html_path),
                content_type="html",
                metadata={"file_path": str(html_path)},
            )

        return None

    async def exists(self, unit_id: str) -> bool:
        """
        Check if file exists.

        Args:
            unit_id: Filename without extension.

        Returns:
            True if any supported file exists.
        """
        for ext in [".md", ".txt", ".html"]:
            if (self.base_path / f"{unit_id}{ext}").exists():
                return True
        return False

    async def close(self) -> None:
        """No-op for file loader."""
        pass
