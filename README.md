<div align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&height=200&section=header&text=PDF%20→%20OFX%20📄&fontSize=70&animation=fadeIn" />
</div>

<h1 align="center">PDF → OFX</h1>

<p align="center">
  <em>Conversor de extratos bancários em PDF para o formato OFX — sem login, sem persistência em banco.</em>
</p>

<br>

## 🛠️ Tecnologias e Ferramentas

<div align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Django-092E20?style=for-the-badge&logo=django&logoColor=white" alt="Django" />
  <img src="https://img.shields.io/badge/pdfplumber-black?style=for-the-badge&logo=adobeacrobatreader&logoColor=white" alt="pdfplumber" />
  <img src="https://img.shields.io/badge/WhiteNoise-4B8BBE?style=for-the-badge&logo=python&logoColor=white" alt="WhiteNoise" />
  <img src="https://img.shields.io/badge/Gunicorn-499848?style=for-the-badge&logo=gunicorn&logoColor=white" alt="Gunicorn" />
</div>

<br>

## 🌟 Sobre o Projeto

**PDF → OFX** é uma aplicação Django isolada que converte extratos bancários em PDF (Bradesco, Safra, Caixa, Banco do Brasil, Sicredi e Banco do Nordeste) para o formato **OFX**, pronto para importar em qualquer sistema financeiro. Não há login, outras telas ou persistência em banco de dados — o arquivo OFX gerado fica em cache por alguns minutos só para permitir o download pelo próprio usuário.

---

## 🚀 Como Executar Localmente

Siga os passos abaixo para rodar o projeto na sua máquina:

### 1. Clone o repositório
```bash
git clone https://github.com/by-BC/pdf-to-ofx.git
cd pdf-to-ofx
```

### 2. Crie o ambiente virtual e instale as dependências
```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

### 3. Configuração de Variáveis de Ambiente
Para desenvolvimento local, defina `DEBUG=1` — sem isso, o Django força redirecionamento HTTPS (`SECURE_SSL_REDIRECT`) e o `runserver` não responde:

```powershell
$env:DEBUG = "1"          # PowerShell
```
```bash
export DEBUG=1            # Linux/macOS/Git Bash
```

### 4. Rode a aplicação
```bash
python manage.py runserver
```
Abra [http://127.0.0.1:8000](http://127.0.0.1:8000) no seu navegador para ver o resultado! ✨

<br>

## 📁 Estrutura

- `conversor_config/` — configuração do projeto Django (settings, urls, wsgi).
- `converter/` — o módulo em si:
  - `common.py`, `parsers.py`, `ofx_writer.py` — leitura dos PDFs e geração do OFX.
  - `store.py` — guarda o OFX gerado no cache (Django `LocMemCache`) por um TTL curto.
  - `views.py` / `urls.py` — página única e os dois endpoints de API (converter/baixar).
  - `templates/converter/index.html` — a página.
  - `static/converter/` — CSS e JS da página.

## 🔒 Variáveis de Ambiente (produção)

- `DEBUG` (padrão `False`)
- `SECRET_KEY`
- `ALLOWED_HOSTS` (lista separada por vírgula)
- `CSRF_TRUSTED_ORIGINS` (lista separada por vírgula)
</content>
