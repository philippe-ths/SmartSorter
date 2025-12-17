from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _norm_keyword(k: str) -> str:
    k = (k or "").strip().lower()
    k = " ".join(_WORD_RE.findall(k))
    return k.strip()


_STOP = {
    "the",
    "and",
    "or",
    "a",
    "an",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "from",
    "at",
    "by",
    "is",
    "are",
    "as",
    "be",
    "this",
    "that",
}


@dataclass(frozen=True)
class FileForClustering:
    file_path: str  # target-relative
    folder_path: str  # "(root)" or folder path relative to target
    keywords: list[str]
    subject_label: str


@dataclass(frozen=True)
class Cluster:
    folder_path: str
    label: str
    size: int
    members: list[str]  # file_path values


def _keywords_for_file(file: FileForClustering) -> set[str]:
    raw = list(file.keywords or [])
    if file.subject_label:
        raw.append(file.subject_label)
    out: set[str] = set()
    for k in raw:
        nk = _norm_keyword(str(k))
        if not nk or nk in _STOP:
            continue
        if len(nk) < 3:
            continue
        out.add(nk)
    return out


def detect_keyword_clusters(
    files: Iterable[FileForClustering],
    *,
    min_cluster_size: int,
) -> list[Cluster]:
    """
    Deterministic cluster pre-pass: within each folder, treat each (normalized) keyword
    as a candidate cluster label; a cluster's members are files containing that keyword.
    """
    min_cluster_size = int(min_cluster_size)
    if min_cluster_size < 2:
        min_cluster_size = 2

    by_folder: dict[str, list[FileForClustering]] = {}
    for f in files:
        by_folder.setdefault(f.folder_path, []).append(f)

    clusters: list[Cluster] = []
    for folder_path, folder_files in sorted(by_folder.items(), key=lambda kv: kv[0].lower()):
        keyword_to_members: dict[str, list[str]] = {}
        for f in sorted(folder_files, key=lambda x: x.file_path.lower()):
            for kw in _keywords_for_file(f):
                keyword_to_members.setdefault(kw, []).append(f.file_path)

        for kw, members in keyword_to_members.items():
            uniq = sorted(set(members), key=str.lower)
            if len(uniq) < min_cluster_size:
                continue
            clusters.append(Cluster(folder_path=folder_path, label=kw, size=len(uniq), members=uniq))

    clusters.sort(key=lambda c: (-c.size, c.folder_path.lower(), c.label.lower()))
    return clusters
