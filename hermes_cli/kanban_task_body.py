"""Admissão de corpos do Kanban: não persistir um recorte de contexto.

Corpo de card e comentário são DADO DURÁVEL, não janela de contexto. O
compressor (``agent/context_compressor.py``) encurta a janela do modelo com um
marcador terminal; quando o modelo IMITA esse marcador (classe #83714) e escreve
o texto imitado no banco, a especificação é destruída de forma irreversível.

Esta é a fronteira de admissão: recusa a escrita ANTES de persistir, para que o
rastro da perda (o texto original, ainda vivo na sessão de quem escreve) não seja
substituído por um recorte.
"""
from __future__ import annotations

# Os dois marcadores terminais conhecidos, ambos emitidos por
# ``agent/context_compressor.py``: o atual (delimitado) e o nu, que o comentário
# de L1416-1420 registra como imitado pelo modelo e gravado em disco.
_COMPRESSION_MARKER_PREFIX = "⟪HERMES-CONTEXT-COMPRESSION:"
_COMPRESSION_MARKER_SUFFIX = "⟫"
_BARE_TRUNCATION_SUFFIX = "[truncated]"


def _truncation_marker(text: str) -> str | None:
    """Nome do marcador terminal em ``text``, ou None quando o texto está íntegro."""
    # Um corpo curto pode ser completo. O marcador TERMINAL, não o tamanho,
    # identifica a perda conhecida; citar o literal no meio da prosa (entre
    # crases, num relatório sobre este próprio defeito) continua válido.
    stripped = text.rstrip()
    if stripped.endswith(_BARE_TRUNCATION_SUFFIX):
        return _BARE_TRUNCATION_SUFFIX
    if _COMPRESSION_MARKER_PREFIX in stripped and stripped.endswith(_COMPRESSION_MARKER_SUFFIX):
        return _COMPRESSION_MARKER_PREFIX
    return None


def _reject(field: str, marker: str) -> None:
    raise ValueError(
        f"{field} ends in a context-compression truncation marker ({marker!r}); "
        "nothing was saved. This text is a shortened view of the model's context, "
        "not durable content: recover the complete text from its source and retry. "
        "Do not just delete the marker — that persists the loss without the trace."
    )


def validate_task_body(body: str | None) -> None:
    """Recusa um corpo de card que termina em marcador de truncagem."""
    if not isinstance(body, str):
        return
    marker = _truncation_marker(body)
    if marker:
        _reject("body", marker)


def validate_comment_body(body: str | None) -> None:
    """Recusa um comentário que termina em marcador de truncagem.

    Mesma fronteira do corpo do card: 12 dos 15 registros destruídos no board
    atlas eram comentários, então cobrir só ``tasks.body`` deixaria o buraco
    aberto justamente onde o dano mais aconteceu.
    """
    if not isinstance(body, str):
        return
    marker = _truncation_marker(body)
    if marker:
        _reject("comment body", marker)
