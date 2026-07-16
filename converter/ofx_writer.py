"""Gera um arquivo OFX 1.02 (SGML, com todas as tags devidamente fechadas) a partir de um
`PdfStatement` — sem nenhuma gravação em banco de dados."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from .common import PdfStatement

_ESCAPE_MAP = (
    ('&', '&amp;'),
    ('<', '&lt;'),
    ('>', '&gt;'),
)


def _escape(text: str) -> str:
    text = text or ''
    for old, new in _ESCAPE_MAP:
        text = text.replace(old, new)
    return text


def _fmt_date(d) -> str:
    return f'{d:%Y%m%d}120000'


def _fmt_amount(valor: Decimal) -> str:
    return f'{valor:.2f}'


def build_ofx(statement: PdfStatement) -> str:
    try:
        dtserver = timezone.localtime().strftime('%Y%m%d%H%M%S')
    except Exception:
        dtserver = datetime.now().strftime('%Y%m%d%H%M%S')

    dtstart = _fmt_date(statement.data_inicio)
    dtend = _fmt_date(statement.data_fim)

    saldo_total = Decimal('0.00')
    stmttrn_blocks = []
    for idx, txn in enumerate(statement.transacoes, start=1):
        saldo_total += txn.valor
        fitid = f'{statement.banco}{txn.data:%Y%m%d}{idx:05d}'
        trntype = 'CREDIT' if txn.valor >= 0 else 'DEBIT'
        checknum_tag = f'\n<CHECKNUM>{_escape(txn.documento)}</CHECKNUM>' if txn.documento else ''
        block = (
            '<STMTTRN>'
            f'\n<TRNTYPE>{trntype}</TRNTYPE>'
            f'\n<DTPOSTED>{_fmt_date(txn.data)}</DTPOSTED>'
            f'\n<TRNAMT>{_fmt_amount(txn.valor)}</TRNAMT>'
            f'\n<FITID>{fitid}</FITID>'
            f'{checknum_tag}'
            f'\n<MEMO>{_escape(txn.descricao)}</MEMO>'
            '\n</STMTTRN>'
        )
        stmttrn_blocks.append(block)

    transacoes_txt = '\n'.join(stmttrn_blocks)

    return (
        'OFXHEADER:100\n'
        'DATA:OFXSGML\n'
        'VERSION:102\n'
        'SECURITY:NONE\n'
        'ENCODING:UTF-8\n'
        'CHARSET:UTF-8\n'
        'COMPRESSION:NONE\n'
        'OLDFILEUID:NONE\n'
        'NEWFILEUID:NONE\n'
        '\n'
        '<OFX>\n'
        '<SIGNONMSGSRSV1>\n'
        '<SONRS>\n'
        '<STATUS>\n'
        '<CODE>0</CODE>\n'
        '<SEVERITY>INFO</SEVERITY>\n'
        '</STATUS>\n'
        f'<DTSERVER>{dtserver}</DTSERVER>\n'
        '<LANGUAGE>POR</LANGUAGE>\n'
        '</SONRS>\n'
        '</SIGNONMSGSRSV1>\n'
        '<BANKMSGSRSV1>\n'
        '<STMTTRNRS>\n'
        '<TRNUID>1</TRNUID>\n'
        '<STATUS>\n'
        '<CODE>0</CODE>\n'
        '<SEVERITY>INFO</SEVERITY>\n'
        '</STATUS>\n'
        '<STMTRS>\n'
        f'<CURDEF>{statement.moeda}</CURDEF>\n'
        '<BANKACCTFROM>\n'
        f'<BANKID>{statement.bankid}</BANKID>\n'
        f'<ACCTID>{_escape(statement.acctid)}</ACCTID>\n'
        '<ACCTTYPE>CHECKING</ACCTTYPE>\n'
        '</BANKACCTFROM>\n'
        '<BANKTRANLIST>\n'
        f'<DTSTART>{dtstart}</DTSTART>\n'
        f'<DTEND>{dtend}</DTEND>\n'
        f'{transacoes_txt}\n'
        '</BANKTRANLIST>\n'
        '<LEDGERBAL>\n'
        f'<BALAMT>{_fmt_amount(saldo_total)}</BALAMT>\n'
        f'<DTASOF>{dtend}</DTASOF>\n'
        '</LEDGERBAL>\n'
        '</STMTRS>\n'
        '</STMTTRNRS>\n'
        '</BANKMSGSRSV1>\n'
        '</OFX>\n'
    )
