#!/usr/bin/env python3
"""Resumable, size/hash-checked download and safe extraction for public datasets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, *, expected_size: int,
                  expected_sha256: str | None = None, timeout: int = 60) -> dict:
    """Download to .part, resume with HTTP Range, verify, then atomically publish."""
    if expected_size <= 0:
        raise ValueError("expected_size must be a positive preflight size")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    if destination.exists():
        if destination.stat().st_size != expected_size:
            raise ValueError(f"existing destination size mismatch: {destination}")
        digest = sha256_file(destination)
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ValueError(f"existing destination checksum mismatch: {destination}")
        return {"path": str(destination), "size_bytes": expected_size, "sha256": digest,
                "status": "ALREADY_VERIFIED"}
    offset = part.stat().st_size if part.exists() else 0
    if offset > expected_size:
        raise ValueError(f"partial download is larger than expected: {part}")
    free = shutil.disk_usage(destination.parent).free
    if free < expected_size - offset:
        raise OSError(f"insufficient disk space: need {expected_size-offset}, have {free}")
    headers = {"User-Agent": "CircuitCare-ComponentDataset/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", response.getcode())
        append = bool(offset and status == 206)
        if offset and status == 200:
            offset = 0  # Server ignored Range; restart the partial file safely.
        elif offset and status != 206:
            raise OSError(f"server rejected resume with HTTP {status}")
        mode = "ab" if append else "wb"
        with part.open(mode) as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    if part.stat().st_size != expected_size:
        raise OSError(f"download incomplete: {part.stat().st_size}/{expected_size}; rerun to resume")
    digest = sha256_file(part)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError(f"download checksum mismatch: expected {expected_sha256}, got {digest}")
    os.replace(part, destination)
    return {"path": str(destination), "size_bytes": expected_size, "sha256": digest,
            "status": "DOWNLOADED_AND_VERIFIED"}


def inspect_tar(path: Path, *, max_members: int = 100_000,
                max_uncompressed_bytes: int = 100_000_000_000) -> dict:
    """Preflight archive paths/types/expanded size; reject links and traversal."""
    with tarfile.open(path, "r:*") as archive:
        members = archive.getmembers()
    if len(members) > max_members:
        raise ValueError(f"archive member count exceeds limit: {len(members)}")
    total = 0
    for member in members:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts:
            raise ValueError(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise ValueError(f"unsupported archive member type: {member.name}")
        total += member.size if member.isfile() else 0
        if total > max_uncompressed_bytes:
            raise ValueError(f"archive expanded bytes exceed limit: {total}")
    return {"member_count": len(members), "file_count": sum(m.isfile() for m in members),
            "uncompressed_bytes": total}


def safe_extract_tar(path: Path, output_dir: Path, *, max_members: int = 100_000,
                     max_uncompressed_bytes: int = 100_000_000_000) -> dict:
    """Extract only regular files/directories after validating all member paths."""
    summary = inspect_tar(path, max_members=max_members,
                          max_uncompressed_bytes=max_uncompressed_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir.resolve()
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            target = (root / member.name).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"archive path escapes extraction root: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(target)
            source = archive.extractfile(member)
            if source is None:
                raise OSError(f"cannot read archive member: {member.name}")
            with source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="download a single public file with resume and integrity checks")
    fetch.add_argument("--url", required=True)
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--expected-size", type=int, required=True)
    fetch.add_argument("--sha256")
    inspect = sub.add_parser("inspect-tar", help="preflight archive expansion before extracting")
    inspect.add_argument("archive", type=Path)
    extract = sub.add_parser("extract-tar", help="safely extract a preflighted tar archive")
    extract.add_argument("archive", type=Path)
    extract.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        result = download_file(args.url, args.output, expected_size=args.expected_size,
                               expected_sha256=args.sha256)
    elif args.command == "inspect-tar":
        result = inspect_tar(args.archive)
    else:
        result = safe_extract_tar(args.archive, args.output_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
