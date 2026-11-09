"""Interfața comună a strategiilor de comunicare cu modelele VLM."""

from abc import ABC, abstractmethod

from ..contracts import VLMRequest, VLMResponse


class VLMStrategy(ABC):
    """Contract implementat de fiecare furnizor VLM."""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Identificatorul furnizorului API."""
        raise NotImplementedError

    @property
    @abstractmethod
    def model(self) -> str:
        """Identificatorul modelului configurat."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: VLMRequest) -> VLMResponse:
        """Execută cererea și returnează răspunsul normalizat."""


        raise NotImplementedError