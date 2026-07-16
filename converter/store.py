"""Armazenamento temporário (cache do Django) do conteúdo OFX gerado a partir de um PDF.

Nada é gravado em banco de dados: o OFX gerado fica no cache por um tempo curto (TTL),
associado a um id (uuid4), só para permitir o download logo em seguida.
"""

from __future__ import annotations

import uuid
from typing import Any

# pyrefly: ignore [missing-import]
from django.conf import settings
# pyrefly: ignore [missing-import]
from django.core.cache import cache

PDF_OFX_TTL = getattr(settings, 'PDF_OFX_DOWNLOAD_TTL', 10 * 60)


def _cache_key(download_id: str) -> str:
    return f'pdf_ofx:v1:{download_id}'


def store_ofx(banco: str, filename: str, ofx_content: str) -> str:
    download_id = str(uuid.uuid4())
    cache.set(
        _cache_key(download_id),
        {
            'banco': banco,
            'filename': filename,
            'ofx': ofx_content,
        },
        PDF_OFX_TTL,
    )
    return download_id


def get_ofx(download_id: str) -> dict[str, Any] | None:
    return cache.get(_cache_key(download_id))
