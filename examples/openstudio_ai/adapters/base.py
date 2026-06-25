from __future__ import annotations

from abc import ABC, abstractmethod

from examples.openstudio_ai.adapters.contracts import HostAdapterConfig, HostLaunchPlan


class OpenStudioAiHostAdapter(ABC):
    """Thin interface implemented by each supported agent host."""

    def __init__(self, config: HostAdapterConfig):
        self.config = config

    @abstractmethod
    def build_launch_plan(self) -> HostLaunchPlan:
        """Return the files and entrypoints the host should load."""

