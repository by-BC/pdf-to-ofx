"""Página e API REST do conversor PDF -> OFX (conversão em memória, sem login e sem banco)."""

from __future__ import annotations

import logging

# pyrefly: ignore [missing-import]
from django.conf import settings
# pyrefly: ignore [missing-import]
from django.http import HttpResponse, JsonResponse
# pyrefly: ignore [missing-import]
from django.shortcuts import render
# pyrefly: ignore [missing-import]
from django.views.decorators.http import require_GET, require_http_methods

from .common import NOME_POR_BANCO, PdfParseError
from .ofx_writer import build_ofx
from .parsers import parse_statement
from .store import get_ofx, store_ofx

logger = logging.getLogger('converter')

PDF_OFX_UPLOAD_MAX_BYTES = getattr(settings, 'PDF_OFX_UPLOAD_MAX_BYTES', 20 * 1024 * 1024)
BANCOS_SUPORTADOS = ('bradesco', 'safra', 'caixa', 'bb', 'sicredi', 'bnb')
PREVIEW_SAMPLE_SIZE = 5


def index_view(request):
    return render(request, 'converter/index.html')


def _validate_upload(upload) -> str | None:
    if upload is None:
        return 'Envie um arquivo PDF no campo "arquivo".'
    if upload.size > PDF_OFX_UPLOAD_MAX_BYTES:
        return f'Arquivo excede o limite de {PDF_OFX_UPLOAD_MAX_BYTES // (1024 * 1024)} MB.'
    name_lower = (upload.name or '').lower()
    if not name_lower.endswith('.pdf'):
        return 'Extensão inválida. Envie um arquivo .pdf.'
    return None


def _txn_preview_dict(txn) -> dict:
    return {
        'data': txn.data.isoformat(),
        'descricao': txn.descricao,
        'valor': float(txn.valor),
        'tipo': txn.tipo,
        'documento': txn.documento,
    }


@require_http_methods(['POST'])
def api_pdf_ofx_converter(request):
    banco = (request.POST.get('banco') or '').strip().lower()
    if banco not in BANCOS_SUPORTADOS:
        return JsonResponse(
            {'error': f'Banco inválido. Valores aceitos: {", ".join(BANCOS_SUPORTADOS)}.'},
            status=400,
        )

    upload = request.FILES.get('arquivo') or request.FILES.get('file')
    err = _validate_upload(upload)
    if err:
        return JsonResponse({'error': err}, status=400)

    content = upload.read()

    try:
        statement = parse_statement(banco, content)
    except PdfParseError as exc:
        logger.info('Falha ao converter PDF (%s, %s): %s', banco, upload.name, exc)
        return JsonResponse({'error': str(exc)}, status=422)
    except Exception as exc:
        logger.exception('Erro inesperado ao converter PDF (%s, %s)', banco, upload.name)
        return JsonResponse(
            {'error': 'Erro inesperado ao processar o PDF. Verifique se o arquivo corresponde ao banco selecionado.'},
            status=422,
        )

    try:
        ofx_text = build_ofx(statement)
    except Exception:
        logger.exception('Falha ao gerar OFX (%s, %s)', banco, upload.name)
        return JsonResponse({'error': 'Falha ao gerar o arquivo OFX.'}, status=500)

    filename = f'extrato_{banco}_{statement.data_fim:%Y%m%d}.ofx'
    download_id = store_ofx(banco, filename, ofx_text)

    total_creditos = sum((t.valor for t in statement.transacoes if t.valor >= 0), start=0)
    total_debitos = sum((-t.valor for t in statement.transacoes if t.valor < 0), start=0)

    logger.info(
        'PDF convertido para OFX: %s (%s, %d lançamentos)',
        upload.name, NOME_POR_BANCO[banco], len(statement.transacoes),
    )

    return JsonResponse(
        {
            'downloadId': download_id,
            'filename': filename,
            'banco': banco,
            'bancoNome': NOME_POR_BANCO[banco],
            'conta': statement.acctid,
            'periodo': {
                'inicio': statement.data_inicio.isoformat(),
                'fim': statement.data_fim.isoformat(),
            },
            'totais': {
                'transacoes': len(statement.transacoes),
                'creditos': float(total_creditos),
                'debitos': float(total_debitos),
                'saldo': float(total_creditos - total_debitos),
            },
            'amostraInicio': [_txn_preview_dict(t) for t in statement.transacoes[:PREVIEW_SAMPLE_SIZE]],
            'amostraFim': [_txn_preview_dict(t) for t in statement.transacoes[-PREVIEW_SAMPLE_SIZE:]],
        },
        status=200,
    )


@require_GET
def api_pdf_ofx_download(request, download_id):
    entry = get_ofx(str(download_id))
    if not entry:
        return JsonResponse(
            {'error': 'Arquivo não encontrado ou expirado. Converta o PDF novamente.'},
            status=404,
        )

    response = HttpResponse(entry['ofx'].encode('utf-8'), content_type='application/x-ofx; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{entry["filename"]}"'
    return response
