# PDF → OFX

Projeto Django isolado contendo apenas o conversor de extrato bancário em PDF
para OFX (Bradesco, Safra, Caixa, Banco do Brasil, Sicredi e Banco do
Nordeste). Sem login, sem outras telas, sem persistência em banco — o OFX
gerado fica em cache por alguns minutos só para permitir o download.

## Rodando localmente

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python manage.py runserver
```

Acesse http://127.0.0.1:8000/.

## Estrutura

- `conversor_config/` — configuração do projeto Django (settings, urls, wsgi).
- `converter/` — o módulo em si:
  - `common.py`, `parsers.py`, `ofx_writer.py` — leitura dos PDFs e geração do OFX.
  - `store.py` — guarda o OFX gerado no cache (Django `LocMemCache`) por um TTL curto.
  - `views.py` / `urls.py` — página única e os dois endpoints de API (converter/baixar).
  - `templates/converter/index.html` — a página.
  - `static/converter/` — CSS e JS da página.

## Variáveis de ambiente (produção)

- `DEBUG` (padrão `False`)
- `SECRET_KEY`
- `ALLOWED_HOSTS` (lista separada por vírgula)
- `CSRF_TRUSTED_ORIGINS` (lista separada por vírgula)
