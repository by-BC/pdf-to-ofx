"""Utilitários compartilhados pelos parsers de PDF → OFX (sem dependência de banco de dados)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MESES_PT = {
    'janeiro': 1, 'fevereiro': 2, 'março': 3, 'marco': 3, 'abril': 4,
    'maio': 5, 'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9,
    'outubro': 10, 'novembro': 11, 'dezembro': 12,
}

BANKID_POR_BANCO = {
    'bradesco': '237',
    'safra': '422',
    'caixa': '104',
    'bb': '001',
    'sicredi': '748',
    'bnb': '004',
}

NOME_POR_BANCO = {
    'bradesco': 'Bradesco',
    'safra': 'Banco Safra',
    'caixa': 'Caixa Econômica Federal',
    'bb': 'Banco do Brasil',
    'sicredi': 'Sicredi',
    'bnb': 'Banco do Nordeste (BNB)',
}

MONEY_RE = re.compile(r'^-?\d{1,3}(?:\.\d{3})*,\d{2}$|^-?\d+,\d{2}$')


class PdfParseError(Exception):
    """Erro de leitura/parsing do extrato em PDF, com mensagem já em português para o usuário."""


@dataclass
class PdfTransaction:
    data: date
    descricao: str
    valor: Decimal
    documento: str = ''

    @property
    def tipo(self) -> str:
        return 'credit' if self.valor >= 0 else 'debit'


@dataclass
class PdfStatement:
    banco: str
    bank_name: str
    bankid: str
    acctid: str
    data_inicio: date
    data_fim: date
    transacoes: list[PdfTransaction] = field(default_factory=list)
    moeda: str = 'BRL'


def parse_valor_br(texto: str) -> Decimal:
    """Converte um número no formato brasileiro (1.234,56) para Decimal com sinal."""
    s = (texto or '').strip()
    if not s:
        raise PdfParseError('Valor monetário vazio encontrado no PDF.')
    negativo = s.startswith('-')
    if negativo:
        s = s[1:]
    s = s.replace('.', '').replace(',', '.')
    try:
        valor = Decimal(s)
    except InvalidOperation as exc:
        raise PdfParseError(f'Não foi possível interpretar o valor "{texto}".') from exc
    return -valor if negativo else valor


def cluster_lines(page, tol: float = 2.5) -> list[list[dict]]:
    """Agrupa palavras extraídas (extract_words) em linhas visuais, tolerando pequenas
    diferenças de coordenada 'top' (evita que uma mesma linha vire duas por arredondamento)."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    words.sort(key=lambda w: (w['top'], w['x0']))
    clusters: list[list[dict]] = []
    cur: list[dict] = []
    cur_top: float | None = None
    for w in words:
        if cur_top is None or abs(w['top'] - cur_top) <= tol:
            cur.append(w)
            if cur_top is None:
                cur_top = w['top']
        else:
            clusters.append(cur)
            cur = [w]
            cur_top = w['top']
    if cur:
        clusters.append(cur)
    for cl in clusters:
        cl.sort(key=lambda w: w['x0'])
    return clusters


def line_text(cluster: list[dict]) -> str:
    return ' '.join(w['text'] for w in cluster)


def normalize_ws(text: str) -> str:
    return re.sub(r'\s+', ' ', text or '').strip()


def parse_date_ddmmyyyy(text: str) -> date:
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', text.strip())
    if not m:
        raise PdfParseError(f'Data inválida encontrada no PDF: "{text}".')
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError as exc:
        raise PdfParseError(f'Data inválida encontrada no PDF: "{text}".') from exc


def build_acctid(*parts: str) -> str:
    cleaned = [p.strip() for p in parts if p and p.strip()]
    return '-'.join(cleaned) if cleaned else 'desconhecida'


def strip_accents(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text or '') if not unicodedata.combining(c))


def norm_key(text: str) -> str:
    """Normaliza uma palavra para comparação tolerante a acento/caixa (só para casar cabeçalhos)."""
    return strip_accents(text or '').strip().lower().rstrip('.:')
