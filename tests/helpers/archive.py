"""Typed archive extraction assertions shared by backup/diagnostic tests."""

from tarfile import TarFile, TarInfo


def read_tar_member(archive: TarFile, member: str | TarInfo) -> bytes:
    stream = archive.extractfile(member)
    assert stream is not None, f"Expected a regular archive file: {member}"
    with stream:
        return stream.read()
