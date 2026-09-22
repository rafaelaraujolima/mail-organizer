import json
from dataclasses import dataclass

from mail_organizer.providers.base import Message


class OllamaUnavailableError(Exception):
    """Raised when the local Ollama server is unreachable or the model isn't available."""


@dataclass
class ClassificationResult:
    folder: str | None
    suspicious: bool
    reason: str


class OllamaClient:
    def __init__(self, session, base_url: str = "http://localhost:11434", model: str = "llama3.2:3b"):
        self._session = session
        self._base_url = base_url
        self._model = model

    def check_available(self) -> None:
        try:
            response = self._session.get(f"{self._base_url}/api/tags", timeout=5)
        except Exception as exc:
            raise OllamaUnavailableError(
                f"Ollama não está acessível em {self._base_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise OllamaUnavailableError(f"Ollama retornou status {response.status_code}")

        models = [m.get("name", "") for m in response.json().get("models", [])]
        if not any(self._model in name for name in models):
            raise OllamaUnavailableError(
                f"Modelo {self._model} não encontrado no Ollama (disponíveis: {models})"
            )

    def classify(
        self, message: Message, existing_folders: list[str], heuristic_flags: list[str]
    ) -> ClassificationResult:
        prompt = self._build_prompt(message, existing_folders, heuristic_flags)
        response = self._session.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "format": "json", "stream": False},
            timeout=60,
        )
        response.raise_for_status()
        data = json.loads(response.json()["response"])
        return ClassificationResult(
            folder=data.get("folder"),
            suspicious=bool(data.get("suspicious", False)),
            reason=data.get("reason", ""),
        )

    def _build_prompt(
        self, message: Message, existing_folders: list[str], heuristic_flags: list[str]
    ) -> str:
        return (
            "Você é um assistente que organiza emails. "
            f"Pastas existentes: {', '.join(existing_folders) if existing_folders else '(nenhuma)'}. "
            f"Sinais técnicos de suspeita já detectados: "
            f"{', '.join(heuristic_flags) if heuristic_flags else 'nenhum'}. "
            f"Remetente: {message.sender}\nAssunto: {message.subject}\n"
            f"Conteúdo: {(message.body_text or '')[:2000]}\n\n"
            "Responda em JSON com as chaves 'folder' (nome de pasta sugerida ou null), "
            "'suspicious' (true/false) e 'reason' (justificativa curta em português)."
        )
