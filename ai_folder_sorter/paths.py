"""
Path handling utilities for SmartSorter.

This module consolidates all folder path normalization, validation, and safety
checks into a single source of truth. It provides a FolderPath value object
that encapsulates the invariants for target-relative paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Pattern for valid folder name characters (alphanumeric, spaces, common punctuation)
_SAFE_FOLDER_NAME_PATTERN = re.compile(r"^[^/\\\0]+$")


@dataclass(frozen=True)
class FolderPath:
    """
    Immutable value object representing a target-relative folder path.
    
    Invariants:
    - Always uses POSIX-style forward slashes
    - Never starts with a leading slash
    - "(root)" is a special sentinel value for the target root
    - No ".." or "." components
    - Path components are sanitized (no path separators in names)
    """
    
    _value: str
    
    # Sentinel value for the target root folder
    ROOT = "(root)"
    
    @classmethod
    def root(cls) -> "FolderPath":
        """Return a FolderPath representing the target root."""
        return cls(_value=cls.ROOT)
    
    @classmethod
    def from_string(cls, raw: str) -> "FolderPath":
        """
        Create a FolderPath from a raw string, applying normalization.
        
        - Strips whitespace
        - Normalizes path separators to forward slashes
        - Removes leading slashes
        - Handles empty/dot paths as root
        - Removes "." and ".." components
        - Sanitizes each path component
        
        Args:
            raw: The raw path string to normalize
            
        Returns:
            A normalized FolderPath instance
        """
        normalized = normalize_folder_path(raw)
        return cls(_value=normalized)
    
    @classmethod
    def from_rel_file_path(cls, rel_path: str) -> "FolderPath":
        """
        Extract the folder portion from a target-relative file path.
        
        Args:
            rel_path: A target-relative file path (e.g., "Documents/file.txt")
            
        Returns:
            The folder path portion, or root if the file is at root level
        """
        rel_path = rel_path.replace("\\", "/").lstrip("/")
        if "/" not in rel_path:
            return cls.root()
        folder_part = rel_path.rsplit("/", 1)[0]
        return cls.from_string(folder_part)
    
    @property
    def value(self) -> str:
        """Return the normalized path string."""
        return self._value
    
    @property
    def is_root(self) -> bool:
        """Return True if this represents the target root."""
        return self._value == self.ROOT
    
    @property
    def name(self) -> str:
        """Return the final component of the path (folder name)."""
        if self.is_root:
            return ""
        if "/" in self._value:
            return self._value.rsplit("/", 1)[1]
        return self._value
    
    @property
    def parent(self) -> "FolderPath":
        """Return the parent folder path, or root if already at root."""
        if self.is_root:
            return self
        if "/" not in self._value:
            return FolderPath.root()
        parent_part = self._value.rsplit("/", 1)[0]
        return FolderPath(_value=parent_part)
    
    def join(self, child: str) -> "FolderPath":
        """
        Join a child folder name to this path.
        
        Args:
            child: The child folder name (not a path with separators)
            
        Returns:
            A new FolderPath with the child appended
            
        Raises:
            ValueError: If child contains path separators
        """
        child = sanitize_folder_name(child)
        if self.is_root:
            return FolderPath(_value=child)
        return FolderPath(_value=f"{self._value}/{child}")
    
    def resolve_under(self, target: Path) -> Path:
        """
        Resolve this folder path to an absolute Path under the target.
        
        Args:
            target: The target root directory
            
        Returns:
            The absolute Path for this folder
            
        Raises:
            ValueError: If the resolved path escapes the target
        """
        if self.is_root:
            return target.resolve()
        return safe_join_under_target(target, self._value)
    
    def __str__(self) -> str:
        return self._value
    
    def __repr__(self) -> str:
        return f"FolderPath({self._value!r})"
    
    def __eq__(self, other: object) -> bool:
        if isinstance(other, FolderPath):
            return self._value == other._value
        return False
    
    def __hash__(self) -> int:
        return hash(self._value)


def sanitize_folder_name(name: str) -> str:
    """
    Sanitize a single folder name component.
    
    - Strips whitespace
    - Collapses multiple spaces
    - Removes leading/trailing dots and spaces
    - Validates no path separators
    
    Args:
        name: The folder name to sanitize
        
    Returns:
        The sanitized folder name
        
    Raises:
        ValueError: If the name is empty or contains invalid characters
    """
    name = (name or "").strip()
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    
    if not name:
        raise ValueError("Folder name is empty.")
    
    if any(sep in name for sep in ("/", "\\", "\0")):
        raise ValueError(f"Invalid folder name: {name!r}")
    
    return name


def normalize_folder_path(raw: str) -> str:
    """
    Normalize a raw folder path string.
    
    - Strips whitespace
    - Handles empty/dot paths as root
    - Normalizes separators to forward slashes
    - Removes leading slashes
    - Filters out "." and ".." components
    - Sanitizes each component
    
    Args:
        raw: The raw path string
        
    Returns:
        The normalized path string, or "(root)" for empty/root paths
    """
    raw = (raw or "").strip()
    
    if raw in {"", ".", "(root)"}:
        return FolderPath.ROOT
    
    # Normalize separators and split
    parts = raw.replace("\\", "/").split("/")
    
    # Filter out empty, ".", and ".." components
    filtered = [p for p in parts if p and p not in {".", ".."}]
    
    if not filtered:
        return FolderPath.ROOT
    
    # Sanitize each component
    sanitized = [sanitize_folder_name(p) for p in filtered]
    
    return "/".join(sanitized)


def normalize_rel_file_path(rel_path: str) -> str:
    """
    Normalize a target-relative file path.
    
    - Strips whitespace
    - Normalizes separators to forward slashes
    - Removes leading slashes
    
    Args:
        rel_path: The relative file path
        
    Returns:
        The normalized path
        
    Raises:
        ValueError: If the path is empty
    """
    rel_path = (rel_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel_path:
        raise ValueError("Empty relative path.")
    return rel_path


def safe_join_under_target(target: Path, rel_path: str) -> Path:
    """
    Safely join a relative path under a target directory.
    
    This function ensures the resulting path does not escape the target
    directory (e.g., via ".." traversal).
    
    Args:
        target: The target root directory
        rel_path: The relative path to join
        
    Returns:
        The resolved absolute path
        
    Raises:
        ValueError: If the resulting path escapes the target
    """
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    resolved = (target / rel_path).resolve()
    target_resolved = target.resolve()
    
    if target_resolved == resolved or target_resolved in resolved.parents:
        return resolved
    
    raise ValueError(f"Path escapes target: {rel_path}")


def rel_posix(target: Path, path: Path) -> str:
    """
    Get the POSIX-style relative path from target to path.
    
    Args:
        target: The target root directory
        path: The absolute path
        
    Returns:
        The relative path as a POSIX string
    """
    return path.relative_to(target).as_posix()
