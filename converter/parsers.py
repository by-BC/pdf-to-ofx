"""Parsers de extrato bancário em PDF (Bradesco, Safra, Caixa, Banco do Brasil).

Cada função recebe os bytes do PDF e devolve um `PdfStatement` (conta + período + transações).
Nenhum dado é gravado em banco — tudo acontece em memória, na requisição.
"""

from __future__ import annotations

import io
import re

import pdfplumber

from .common import (
    BANKID_POR_BANCO,
    MESES_PT,
    MONEY_RE,
    NOME_POR_BANCO,
    PdfParseError,
    PdfStatement,
    PdfTransaction,
    build_acctid,
    cluster_lines,
    line_text,
    norm_key,
    normalize_ws,
    parse_date_ddmmyyyy,
    parse_valor_br,
)

DATE_DDMMYYYY_RE = re.compile(r'^\d{2}/\d{2}/\d{4}$')
DATE_DDMM_RE = re.compile(r'^\d{2}/\d{2}$')


def _full_text(pdf) -> str:
    parts = []
    for page in pdf.pages:
        try:
            parts.append(page.extract_text() or '')
        except Exception:
            continue
    return normalize_ws('\n'.join(parts))


def _open_pdf(content: bytes):
    try:
        return pdfplumber.open(io.BytesIO(content))
    except Exception as exc:
        raise PdfParseError('Não foi possível abrir o arquivo PDF. Verifique se ele não está corrompido.') from exc


# --------------------------------------------------------------------------------------
# BRADESCO
# --------------------------------------------------------------------------------------

def parse_bradesco(content: bytes) -> PdfStatement:
    with _open_pdf(content) as pdf:
        texto = _full_text(pdf)

        m_conta = re.search(r'Ag:\s*(\d+)\s*\|\s*CC:\s*([\d-]+)', texto)
        m_periodo = re.search(
            r'Entre\s+(\d{2}/\d{2}/\d{4})\s+e\s+(\d{2}/\d{2}/\d{4})', texto,
        )
        if not m_conta or not m_periodo:
            raise PdfParseError(
                'Não foi possível identificar conta/período no extrato Bradesco. '
                'Confirme se é um extrato "Por Período" do Bradesco Net Empresa.',
            )
        agencia, conta = m_conta.group(1), m_conta.group(2)
        data_inicio = parse_date_ddmmyyyy(m_periodo.group(1))
        data_fim = parse_date_ddmmyyyy(m_periodo.group(2))

        clusters: list[list[dict]] = []
        for page in pdf.pages:
            clusters.extend(cluster_lines(page))

        transacoes = _parse_bradesco_transactions(clusters)

    if not transacoes:
        raise PdfParseError('Nenhuma transação encontrada no extrato Bradesco enviado.')

    return PdfStatement(
        banco='bradesco',
        bank_name=NOME_POR_BANCO['bradesco'],
        bankid=BANKID_POR_BANCO['bradesco'],
        acctid=build_acctid(agencia, conta),
        data_inicio=data_inicio,
        data_fim=data_fim,
        transacoes=transacoes,
    )


def _is_header_row(cl: list[dict]) -> bool:
    keys = {norm_key(w['text']) for w in cl}
    return 'lancamento' in keys and 'dcto' in keys and ('credito' in keys or 'debito' in keys)


def _is_total_row(cl: list[dict]) -> bool:
    return norm_key(cl[0]['text']) == 'total'


def _is_stop_title(cl: list[dict]) -> bool:
    text = norm_key(line_text(cl))
    return 'ultimos lancamentos' in text or 'saldos invest' in text


def _bradesco_column_bounds(header: list[dict]) -> dict[str, float]:
    pos: dict[str, float] = {}
    for w in header:
        key = norm_key(w['text'])
        if key == 'lancamento':
            pos['desc'] = w['x0']
        elif key == 'dcto':
            pos['doc'] = w['x0']
        elif key == 'credito':
            pos['credito'] = w['x0']
        elif key == 'debito':
            pos['debito'] = w['x0']
        elif key == 'saldo':
            pos['saldo'] = w['x0']
    return pos


def _parse_bradesco_transactions(clusters: list[list[dict]]) -> list[PdfTransaction]:
    header_idx = None
    for i, cl in enumerate(clusters):
        if _is_header_row(cl):
            header_idx = i
            break
    if header_idx is None:
        raise PdfParseError('Não foi possível localizar a tabela de lançamentos no extrato Bradesco.')

    bounds = _bradesco_column_bounds(clusters[header_idx])
    # Buffer: os números de cada coluna começam alguns pontos à esquerda do rótulo do cabeçalho.
    doc_x = bounds.get('doc', 260) - 15
    credito_x = bounds.get('credito', 330)
    debito_x = bounds.get('debito', 420)
    saldo_x = bounds.get('saldo', 500)

    transacoes: list[PdfTransaction] = []
    current_date = None
    pending_prefix: str | None = None

    i = header_idx + 1
    n = len(clusters)
    while i < n:
        cl = clusters[i]

        if _is_stop_title(cl):
            break
        if _is_total_row(cl):
            break
        if _is_header_row(cl):
            # cabeçalho repetido em página seguinte da mesma tabela — ignora e continua
            i += 1
            continue

        desc_full = norm_key(line_text(cl))
        if 'saldo anterior' in desc_full:
            i += 1
            continue

        credito_val = None
        debito_val = None
        doc_num = ''
        desc_words = []
        date_word = None

        for w in cl:
            text = w['text']
            x0 = w['x0']
            if x0 < 100 and DATE_DDMMYYYY_RE.match(text):
                date_word = text
                continue
            if MONEY_RE.match(text):
                # o texto pode já trazer sinal de menos na coluna Débito; sempre normalizamos
                # para magnitude absoluta aqui e aplicamos o sinal correto ao montar a transação.
                if x0 < debito_x:
                    credito_val = abs(parse_valor_br(text))
                elif x0 < saldo_x:
                    debito_val = abs(parse_valor_br(text))
                # valores na coluna Saldo são ignorados (não fazem parte da transação)
                continue
            if doc_x <= x0 < credito_x and text.isdigit():
                doc_num = text
                continue
            if x0 < doc_x:
                desc_words.append(text)

        desc_on_line = normalize_ws(' '.join(desc_words))
        has_value = credito_val is not None or debito_val is not None

        if not has_value:
            # linha de descrição pura (prefixo ou sufixo de uma transação vizinha)
            pending_prefix = ((pending_prefix + ' ') if pending_prefix else '') + desc_on_line
            i += 1
            continue

        if date_word:
            current_date = parse_date_ddmmyyyy(date_word)
        if current_date is None:
            raise PdfParseError('Extrato Bradesco possui lançamento sem data de referência.')

        desc_parts = []
        used_prefix = False
        if desc_on_line:
            desc_parts.append(desc_on_line)
        elif pending_prefix:
            desc_parts.append(pending_prefix)
            used_prefix = True
        pending_prefix = None

        valor = credito_val if credito_val is not None else -debito_val

        # sufixo: só existe quando a descrição desta linha veio inteiramente do prefixo
        # (padrão de transações "quebradas" em 3 linhas: prefixo + dados + sufixo)
        if used_prefix and i + 1 < n:
            nxt = clusters[i + 1]
            if (
                not _is_total_row(nxt)
                and not _is_stop_title(nxt)
                and not _is_header_row(nxt)
                and 'saldo anterior' not in norm_key(line_text(nxt))
            ):
                nxt_has_value = any(MONEY_RE.match(w['text']) for w in nxt)
                nxt_has_date = any(
                    w['x0'] < 100 and DATE_DDMMYYYY_RE.match(w['text']) for w in nxt
                )
                if not nxt_has_value and not nxt_has_date:
                    desc_parts.append(normalize_ws(line_text(nxt)))
                    i += 1

        transacoes.append(
            PdfTransaction(
                data=current_date,
                descricao=normalize_ws(' '.join(desc_parts)) or 'Lançamento',
                valor=valor,
                documento=doc_num,
            ),
        )
        i += 1

    return transacoes


# --------------------------------------------------------------------------------------
# SAFRA
# --------------------------------------------------------------------------------------

def parse_safra(content: bytes) -> PdfStatement:
    with _open_pdf(content) as pdf:
        texto = _full_text(pdf)

        m_conta = re.search(r'AG:\s*(\d+)\s*\|\s*CONTA:\s*([\d-]+)', texto)
        m_periodo = re.search(
            r'Per[ií]odo\s+de\s+(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})', texto,
        )
        if not m_conta or not m_periodo:
            raise PdfParseError(
                'Não foi possível identificar conta/período no extrato do Banco Safra.',
            )
        agencia, conta = m_conta.group(1), m_conta.group(2)
        data_inicio = parse_date_ddmmyyyy(m_periodo.group(1))
        data_fim = parse_date_ddmmyyyy(m_periodo.group(2))

        clusters: list[list[dict]] = []
        for page in pdf.pages:
            clusters.extend(cluster_lines(page))

        transacoes = _parse_safra_transactions(clusters, data_inicio, data_fim)

    if not transacoes:
        raise PdfParseError('Nenhuma transação encontrada no extrato do Banco Safra enviado.')

    return PdfStatement(
        banco='safra',
        bank_name=NOME_POR_BANCO['safra'],
        bankid=BANKID_POR_BANCO['safra'],
        acctid=build_acctid(agencia, conta),
        data_inicio=data_inicio,
        data_fim=data_fim,
        transacoes=transacoes,
    )


def _safra_header_bounds(header: list[dict]) -> dict[str, float]:
    pos: dict[str, float] = {}
    for w in header:
        key = norm_key(w['text'])
        if key == 'lancamento':
            pos['desc'] = w['x0']
        elif key == 'complemento':
            pos['complemento'] = w['x0']
        elif key in ('n', 'no', 'documento'):
            pos['doc'] = min(pos.get('doc', w['x0']), w['x0'])
        elif key == 'valor':
            pos['valor'] = w['x0']
    return pos


def _safra_year_for_month(month: int, data_inicio, data_fim) -> int:
    if month >= data_inicio.month:
        return data_inicio.year
    return data_fim.year


def _parse_safra_transactions(clusters, data_inicio, data_fim) -> list[PdfTransaction]:
    header_idx = None
    for i, cl in enumerate(clusters):
        keys = {norm_key(w['text']) for w in cl}
        if 'lancamento' in keys and 'complemento' in keys and 'valor' in keys:
            header_idx = i
            break
    if header_idx is None:
        raise PdfParseError('Não foi possível localizar a tabela de lançamentos no extrato Safra.')

    bounds = _safra_header_bounds(clusters[header_idx])
    doc_x = bounds.get('doc', 400) - 15

    transacoes: list[PdfTransaction] = []
    i = header_idx + 1
    n = len(clusters)
    while i < n:
        cl = clusters[i]
        keys = {norm_key(w['text']) for w in cl}
        if 'lancamento' in keys and 'complemento' in keys and 'valor' in keys:
            i += 1
            continue
        text_join = norm_key(line_text(cl))
        if 'central de suporte' in text_join or 'ouvidoria' in text_join:
            i += 1
            continue

        first = cl[0]
        if first['x0'] < 60 and DATE_DDMM_RE.match(first['text']):
            valor_word = None
            for w in reversed(cl):
                if MONEY_RE.match(w['text']):
                    valor_word = w
                    break
            if valor_word is not None:
                dia, mes = first['text'].split('/')
                ano = _safra_year_for_month(int(mes), data_inicio, data_fim)
                data_txn = parse_date_ddmmyyyy(f'{dia}/{mes}/{ano}')

                doc_num = ''
                desc_words = []
                for w in cl[1:]:
                    if w is valor_word:
                        continue
                    if MONEY_RE.match(w['text']):
                        continue
                    if w['x0'] >= doc_x and w['text'].isdigit():
                        doc_num = w['text']
                        continue
                    desc_words.append(w['text'])

                valor = parse_valor_br(valor_word['text'])
                desc = normalize_ws(' '.join(desc_words)) or 'Lançamento'

                # linha(s) de continuação: sem data DD/MM no início e sem valor monetário
                j = i + 1
                extra = []
                while j < n:
                    nxt = clusters[j]
                    nxt_first = nxt[0]
                    is_new_txn = nxt_first['x0'] < 60 and DATE_DDMM_RE.match(nxt_first['text'])
                    has_money = any(MONEY_RE.match(w['text']) for w in nxt)
                    nxt_join = norm_key(line_text(nxt))
                    if is_new_txn or has_money or 'central de suporte' in nxt_join:
                        break
                    extra.append(normalize_ws(line_text(nxt)))
                    j += 1

                if extra:
                    desc = normalize_ws(desc + ' ' + ' '.join(extra))

                transacoes.append(
                    PdfTransaction(data=data_txn, descricao=desc, valor=valor, documento=doc_num),
                )
                i = j
                continue

        i += 1

    return transacoes


# --------------------------------------------------------------------------------------
# CAIXA ECONÔMICA FEDERAL
# --------------------------------------------------------------------------------------

def parse_caixa(content: bytes) -> PdfStatement:
    with _open_pdf(content) as pdf:
        texto = _full_text(pdf)

        m_conta = re.search(r'Conta:\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d-]+)', texto)
        m_mes = re.search(r'M[êe]s:\s*([A-Za-zçÇ]+)/(\d{4})', texto)
        m_periodo = re.search(r'Per[ií]odo:\s*(\d{1,2})\s*-\s*(\d{1,2})', texto)
        if not m_conta or not m_mes or not m_periodo:
            raise PdfParseError(
                'Não foi possível identificar conta/período no extrato da Caixa. '
                'Confirme se é um extrato "por período" do Gerenciador Caixa.',
            )
        agencia, operacao, conta = m_conta.group(1), m_conta.group(2), m_conta.group(3)
        mes_nome = m_mes.group(1).strip().lower()
        ano = int(m_mes.group(2))
        mes_num = MESES_PT.get(mes_nome)
        if not mes_num:
            raise PdfParseError(f'Mês do extrato Caixa não reconhecido: "{mes_nome}".')
        dia_ini, dia_fim = int(m_periodo.group(1)), int(m_periodo.group(2))

        from datetime import date as _date
        import calendar
        dia_fim = min(dia_fim, calendar.monthrange(ano, mes_num)[1])
        data_inicio = _date(ano, mes_num, dia_ini)
        data_fim = _date(ano, mes_num, dia_fim)

        clusters: list[list[dict]] = []
        for page in pdf.pages:
            clusters.extend(cluster_lines(page))

        transacoes = _parse_caixa_transactions(clusters)

    if not transacoes:
        raise PdfParseError('Nenhuma transação encontrada no extrato da Caixa enviado.')

    return PdfStatement(
        banco='caixa',
        bank_name=NOME_POR_BANCO['caixa'],
        bankid=BANKID_POR_BANCO['caixa'],
        acctid=build_acctid(agencia, operacao, conta),
        data_inicio=data_inicio,
        data_fim=data_fim,
        transacoes=transacoes,
    )


def _money_cd_pairs(cl: list[dict]) -> list[tuple[dict, str]]:
    """Retorna pares (token_valor, 'C'|'D') na ordem em que aparecem na linha."""
    pairs = []
    for idx, w in enumerate(cl):
        if MONEY_RE.match(w['text']) and idx + 1 < len(cl) and cl[idx + 1]['text'] in ('C', 'D'):
            pairs.append((w, cl[idx + 1]['text']))
    return pairs


def _parse_caixa_transactions(clusters) -> list[PdfTransaction]:
    header_idx = None
    for i, cl in enumerate(clusters):
        keys = {norm_key(w['text']) for w in cl}
        if 'historico' in keys and 'valor' in keys and 'saldo' in keys:
            header_idx = i
            break
    if header_idx is None:
        raise PdfParseError('Não foi possível localizar a tabela de lançamentos no extrato da Caixa.')

    transacoes: list[PdfTransaction] = []
    for cl in clusters[header_idx + 1:]:
        first = cl[0]
        if not (first['x0'] < 80 and DATE_DDMMYYYY_RE.match(first['text'])):
            continue

        pairs = _money_cd_pairs(cl)
        if len(pairs) < 1:
            continue
        valor_tok, valor_sign = pairs[0]

        desc_words = []
        doc_num = ''
        for w in cl[1:]:
            if w is valor_tok or w['text'] in ('C', 'D'):
                continue
            if any(w is p[0] for p in pairs):
                continue
            if not doc_num and w['x0'] < 168 and w['text'].isdigit():
                doc_num = w['text']
                continue
            desc_words.append(w['text'])

        desc = normalize_ws(' '.join(desc_words))
        if norm_key(desc) in ('saldo dia', 'saldo anterior') or not desc:
            continue

        valor = parse_valor_br(valor_tok['text'])
        if valor_sign == 'D':
            valor = -abs(valor)
        else:
            valor = abs(valor)

        transacoes.append(
            PdfTransaction(
                data=parse_date_ddmmyyyy(first['text']),
                descricao=desc,
                valor=valor,
                documento=doc_num,
            ),
        )

    return transacoes


# --------------------------------------------------------------------------------------
# BANCO DO BRASIL
# --------------------------------------------------------------------------------------

def parse_banco_do_brasil(content: bytes) -> PdfStatement:
    with _open_pdf(content) as pdf:
        texto = _full_text(pdf)

        m_conta = re.search(r'Ag[êe]ncia\s+([\d-]+).*?Conta\s+corrente\s+([\d-]+)', texto)
        m_periodo = re.search(
            r'Per[ií]odo\s+do\s+extrato\s+de\s+(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{4})\s+at[ée]\s+'
            r'(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{4})',
            texto,
        )
        if not m_conta or not m_periodo:
            raise PdfParseError(
                'Não foi possível identificar conta/período no extrato do Banco do Brasil.',
            )
        agencia, conta = m_conta.group(1), m_conta.group(2)
        data_inicio = parse_date_ddmmyyyy(f'{m_periodo.group(1)}/{m_periodo.group(2)}/{m_periodo.group(3)}')
        data_fim = parse_date_ddmmyyyy(f'{m_periodo.group(4)}/{m_periodo.group(5)}/{m_periodo.group(6)}')

        clusters: list[list[dict]] = []
        for page in pdf.pages:
            clusters.extend(cluster_lines(page))

        transacoes = _parse_bb_transactions(clusters)

    if not transacoes:
        raise PdfParseError('Nenhuma transação encontrada no extrato do Banco do Brasil enviado.')

    return PdfStatement(
        banco='bb',
        bank_name=NOME_POR_BANCO['bb'],
        bankid=BANKID_POR_BANCO['bb'],
        acctid=build_acctid(agencia, conta),
        data_inicio=data_inicio,
        data_fim=data_fim,
        transacoes=transacoes,
    )


def _bb_header_bounds(header: list[dict]) -> dict[str, float]:
    pos: dict[str, float] = {}
    for w in header:
        key = norm_key(w['text'])
        if key == 'historico':
            pos['hist'] = w['x0']
        elif key == 'documento':
            pos['doc'] = w['x0']
        elif key == 'valor':
            pos['valor'] = w['x0']
        elif key == 'saldo':
            pos['saldo'] = w['x0']
    return pos


FOOTER_MARKERS = ('transacao efetuada com sucesso', 'servico de atendimento ao consumidor', 'sac ')


def _parse_bb_transactions(clusters) -> list[PdfTransaction]:
    header_idx = None
    for i, cl in enumerate(clusters):
        keys = {norm_key(w['text']) for w in cl}
        if 'historico' in keys and 'documento' in keys and 'valor' in keys:
            header_idx = i
            break
    if header_idx is None:
        raise PdfParseError('Não foi possível localizar a tabela de lançamentos no extrato do Banco do Brasil.')

    bounds = _bb_header_bounds(clusters[header_idx])
    hist_x = bounds.get('hist', 250) - 15
    doc_x = bounds.get('doc', 407) - 15
    valor_x = bounds.get('valor', 471) - 15
    saldo_x = bounds.get('saldo', 525) - 15

    transacoes: list[PdfTransaction] = []
    i = header_idx + 1
    n = len(clusters)
    while i < n:
        cl = clusters[i]
        text_join = norm_key(line_text(cl))
        if any(marker in text_join for marker in FOOTER_MARKERS):
            break
        if text_join.startswith('-----'):
            break

        first = cl[0]
        if not DATE_DDMMYYYY_RE.match(first['text']):
            i += 1
            continue

        pairs = _money_cd_pairs(cl)
        valor_pair = None
        for tok, sign in pairs:
            if valor_x <= tok['x0'] < saldo_x:
                valor_pair = (tok, sign)
                break

        if valor_pair is None:
            # linha de saldo (abertura/fechamento), não é transação
            i += 1
            continue

        desc_words = []
        doc_num = ''
        doc_like_re = re.compile(r'^[\d]{1,3}(?:\.[\d]{3}){1,}$|^\d{4,}$')
        for w in cl[1:]:
            x0 = w['x0']
            if any(w is p[0] for p in pairs) or w['text'] in ('C', 'D'):
                continue
            if not (hist_x <= x0 < valor_x):
                continue
            if not doc_num and doc_like_re.match(w['text']):
                doc_num = w['text']
                continue
            desc_words.append(w['text'])

        desc = normalize_ws(' '.join(desc_words))

        valor = parse_valor_br(valor_pair[0]['text'])
        valor = abs(valor) if valor_pair[1] == 'C' else -abs(valor)

        # linha de detalhe (nome do remetente/pagador, horário) sem data completa
        if i + 1 < n:
            nxt = clusters[i + 1]
            nxt_first = nxt[0]
            nxt_join = norm_key(line_text(nxt))
            if not DATE_DDMMYYYY_RE.match(nxt_first['text']) and not any(
                marker in nxt_join for marker in FOOTER_MARKERS
            ) and not nxt_join.startswith('-----'):
                desc = normalize_ws(desc + ' ' + line_text(nxt))
                i += 1

        transacoes.append(
            PdfTransaction(
                data=parse_date_ddmmyyyy(first['text']),
                descricao=desc or 'Lançamento',
                valor=valor,
                documento=doc_num,
            ),
        )
        i += 1

    return transacoes


# --------------------------------------------------------------------------------------
# SICREDI
# --------------------------------------------------------------------------------------

def parse_sicredi(content: bytes) -> PdfStatement:
    with _open_pdf(content) as pdf:
        texto = _full_text(pdf)

        m_coop = re.search(r'Cooperativa:\s*(\d+)', texto)
        m_conta = re.search(r'Conta:\s*([\d-]+)', texto)
        m_periodo = re.search(
            r'Per[ií]odo\s+de\s+(\d{2}/\d{2}/\d{4})\s+a\s+(\d{2}/\d{2}/\d{4})', texto,
        )
        if not m_coop or not m_conta or not m_periodo:
            raise PdfParseError(
                'Não foi possível identificar conta/período no extrato do Sicredi. '
                'Confirme se é um extrato "Por Período" do Sicredi.',
            )
        cooperativa, conta = m_coop.group(1), m_conta.group(1)
        data_inicio = parse_date_ddmmyyyy(m_periodo.group(1))
        data_fim = parse_date_ddmmyyyy(m_periodo.group(2))

        clusters: list[list[dict]] = []
        for page in pdf.pages:
            clusters.extend(cluster_lines(page))

        transacoes = _parse_sicredi_transactions(clusters)

    if not transacoes:
        raise PdfParseError('Nenhuma transação encontrada no extrato do Sicredi enviado.')

    return PdfStatement(
        banco='sicredi',
        bank_name=NOME_POR_BANCO['sicredi'],
        bankid=BANKID_POR_BANCO['sicredi'],
        acctid=build_acctid(cooperativa, conta),
        data_inicio=data_inicio,
        data_fim=data_fim,
        transacoes=transacoes,
    )


def _parse_sicredi_transactions(clusters: list[list[dict]]) -> list[PdfTransaction]:
    header_idx = None
    for i, cl in enumerate(clusters):
        keys = {norm_key(w['text']) for w in cl}
        if 'descricao' in keys and 'documento' in keys and 'valor' in keys:
            header_idx = i
            break
    if header_idx is None:
        raise PdfParseError('Não foi possível localizar a tabela de lançamentos no extrato do Sicredi.')

    doc_x = None
    for w in clusters[header_idx]:
        if norm_key(w['text']) == 'documento':
            doc_x = w['x0']
            break
    doc_x = (doc_x or 381) - 15

    transacoes: list[PdfTransaction] = []
    for cl in clusters[header_idx + 1:]:
        # A seção "Lançamentos Futuros" (próximos 30 dias) fica fora do período do
        # extrato e usa uma tabela diferente (sem coluna Documento/Saldo) — ignorada.
        if 'lancamentos futuros' in norm_key(line_text(cl)):
            break

        first = cl[0]
        if not (first['x0'] < 80 and DATE_DDMMYYYY_RE.match(first['text'])):
            # ex.: linha "SALDO ANTERIOR"
            continue

        money_tokens = [w for w in cl if MONEY_RE.match(w['text'])]
        if len(money_tokens) < 2:
            continue
        valor_tok, saldo_tok = money_tokens[-2], money_tokens[-1]

        desc_words = []
        doc_num = ''
        for w in cl[1:]:
            if w is valor_tok or w is saldo_tok:
                continue
            if w['x0'] >= doc_x:
                doc_num = w['text']
                continue
            desc_words.append(w['text'])

        transacoes.append(
            PdfTransaction(
                data=parse_date_ddmmyyyy(first['text']),
                descricao=normalize_ws(' '.join(desc_words)) or 'Lançamento',
                valor=parse_valor_br(valor_tok['text']),
                documento=doc_num,
            ),
        )

    return transacoes


# --------------------------------------------------------------------------------------
# BANCO DO NORDESTE (BNB)
# --------------------------------------------------------------------------------------

# Gap vertical (pt) que separa uma quebra de linha dentro do mesmo lançamento (~4-9pt,
# quando a descrição não cabe em uma linha só) de um novo lançamento (~11-13pt).
BNB_GAP_THRESHOLD = 10.5


def parse_banco_nordeste(content: bytes) -> PdfStatement:
    with _open_pdf(content) as pdf:
        texto = _full_text(pdf)

        m_conta = re.search(
            r'Ag[êe]ncia/Conta\s+Corrente:\s*(\d+)\s*-\s*[^/]+/([\d-]+)', texto,
        )
        m_periodo = re.search(
            r'Per[ií]odo:\s*(\d{2}/\d{2}/\d{4})\s+at[ée]\s+(\d{2}/\d{2}/\d{4})', texto,
        )
        if not m_conta or not m_periodo:
            raise PdfParseError(
                'Não foi possível identificar conta/período no extrato do Banco do Nordeste (BNB).',
            )
        agencia, conta = m_conta.group(1), m_conta.group(2)
        data_inicio = parse_date_ddmmyyyy(m_periodo.group(1))
        data_fim = parse_date_ddmmyyyy(m_periodo.group(2))

        transacoes = _parse_bnb_transactions(pdf.pages)

    if not transacoes:
        raise PdfParseError('Nenhuma transação encontrada no extrato do Banco do Nordeste enviado.')

    return PdfStatement(
        banco='bnb',
        bank_name=NOME_POR_BANCO['bnb'],
        bankid=BANKID_POR_BANCO['bnb'],
        acctid=build_acctid(agencia, conta),
        data_inicio=data_inicio,
        data_fim=data_fim,
        transacoes=transacoes,
    )


def _bnb_transaction_from_group(group: list[list[dict]], doc_x: float) -> PdfTransaction | None:
    anchor_idx = None
    for gi, cl in enumerate(group):
        first = cl[0]
        if first['x0'] < 60 and DATE_DDMMYYYY_RE.match(first['text']):
            anchor_idx = gi
            break
    if anchor_idx is None:
        return None

    anchor = group[anchor_idx]
    money_tokens = [w for w in anchor if MONEY_RE.match(w['text'])]
    if len(money_tokens) < 2:
        return None
    valor_tok, saldo_tok = money_tokens[-2], money_tokens[-1]

    # o sinal negativo do Valor às vezes vem como um token "-" separado (espaçado da
    # coluna Valor), em vez de vir junto do número.
    valor_pos = anchor.index(valor_tok)
    sinal_separado = valor_pos > 0 and anchor[valor_pos - 1]['text'] == '-'

    desc_words = []
    doc_num = ''
    for w in anchor[1:]:
        if w is valor_tok or w is saldo_tok or w['text'] == '-':
            continue
        if w['x0'] >= doc_x:
            doc_num = w['text']
            continue
        desc_words.append(w['text'])

    # a descrição pode vir "espremida" em até 3 linhas verticalmente centralizadas na
    # linha com data/valor: uma linha antes (prefixo) e/ou uma linha depois (sufixo).
    parts = [line_text(cl) for cl in group[:anchor_idx]]
    parts.append(normalize_ws(' '.join(desc_words)))
    parts.extend(line_text(cl) for cl in group[anchor_idx + 1:])
    desc = normalize_ws(' '.join(p for p in parts if p)) or 'Lançamento'

    valor = abs(parse_valor_br(valor_tok['text']))
    if sinal_separado or valor_tok['text'].startswith('-'):
        valor = -valor

    return PdfTransaction(
        data=parse_date_ddmmyyyy(anchor[0]['text']),
        descricao=desc,
        valor=valor,
        documento=doc_num,
    )


def _parse_bnb_transactions(pages) -> list[PdfTransaction]:
    header_found = False
    doc_x = 208 - 15
    transacoes: list[PdfTransaction] = []

    for page in pages:
        clusters = cluster_lines(page)
        start = 0

        if not header_found:
            for i, cl in enumerate(clusters):
                keys = {norm_key(w['text']) for w in cl}
                if 'historico' in keys and 'documento' in keys and 'valor' in keys:
                    for w in cl:
                        if norm_key(w['text']) == 'documento':
                            doc_x = w['x0'] - 15
                    header_found = True
                    start = i + 1
                    break
            if not header_found:
                continue

        groups: list[list[list[dict]]] = []
        current_group: list[list[dict]] = []
        prev_top = None
        stop = False
        for cl in clusters[start:]:
            if 'detalhamento do saldo' in norm_key(line_text(cl)):
                stop = True
                break
            top = min(w['top'] for w in cl)
            if prev_top is not None and (top - prev_top) > BNB_GAP_THRESHOLD:
                if current_group:
                    groups.append(current_group)
                current_group = []
            current_group.append(cl)
            prev_top = top
        if current_group:
            groups.append(current_group)

        for group in groups:
            txn = _bnb_transaction_from_group(group, doc_x)
            if txn is not None:
                transacoes.append(txn)

        if stop:
            break

    if not header_found:
        raise PdfParseError('Não foi possível localizar a tabela de lançamentos no extrato do Banco do Nordeste.')

    return transacoes


PARSERS = {
    'bradesco': parse_bradesco,
    'safra': parse_safra,
    'caixa': parse_caixa,
    'bb': parse_banco_do_brasil,
    'sicredi': parse_sicredi,
    'bnb': parse_banco_nordeste,
}


def parse_statement(banco: str, content: bytes) -> PdfStatement:
    parser = PARSERS.get(banco)
    if parser is None:
        raise PdfParseError(f'Banco não suportado: {banco}.')
    return parser(content)
