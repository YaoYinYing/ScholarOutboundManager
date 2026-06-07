"""Effect definitions and runner helpers for the store-driven TUI runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoadArtifacts:
    reason: str


@dataclass(frozen=True, slots=True)
class SaveRouteDraft:
    pass


@dataclass(frozen=True, slots=True)
class RunFetch:
    pass


@dataclass(frozen=True, slots=True)
class RunProbe:
    pass


@dataclass(frozen=True, slots=True)
class RunPortCheck:
    route_id: str


@dataclass(frozen=True, slots=True)
class RunAction:
    action_key: str


@dataclass(frozen=True, slots=True)
class CreateSnapshot:
    reason: str


Effect = LoadArtifacts | SaveRouteDraft | RunFetch | RunProbe | RunPortCheck | RunAction | CreateSnapshot


__all__ = [
    "CreateSnapshot",
    "Effect",
    "LoadArtifacts",
    "RunAction",
    "RunFetch",
    "RunPortCheck",
    "RunProbe",
    "SaveRouteDraft",
]
