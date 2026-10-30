# Painvest

Triagem de REITs americanos com metodologia própria, inspirada nos filtros do índice IAFD (AUVP11) e adaptada à realidade das REITs e do investidor brasileiro.

> Ferramenta de apoio à decisão. Não é recomendação de investimento.

## Metodologia

**Etapa 1 — filtros eliminatórios** (todos configuráveis em *Metodologia*):

| Critério IAFD | Versão REIT |
|---|---|
| Lucro 5 anos | AFFO positivo 5 anos + AFFO/ação crescente em ≥ 4 de 5 |
| ROE > 10% | Sem corte de dividendo há ≥ 10 anos |
| Margem > 8% | Payout do AFFO ≤ 85% (≤ 90% para mensais) |
| Dívida < 3x EBITDA | Dív. líq./EBITDA ≤ 6x + rating grau de investimento |
| 5 anos de bolsa | ≥ 10 anos listada |
| Valor ≥ R$ 3 bi | Valor de mercado ≥ US$ 5 bi |
| Volume | Volume médio diário ≥ US$ 20 mi |
| Exclusão setorial | Escritórios, hotéis, mREITs; maior inquilino ≤ 20% da receita |

**Etapa 2 — matriz ponderada (0–10, interpolação linear):** yield líquido (após retenção de 30% nos EUA) vs Treasury 10a — 20%; frequência (mensal 10, trimestral 6) — 15%; CAGR do dividendo 5a — 15%; payout AFFO — 15%; dív./EBITDA — 15%; rating — 10%; valuation P/AFFO vs média 5a — 10%.

**Status:** Candidata (nota ≥ 7) · Observação (≥ 5) · Descarte · Reprovada (falhou filtro) · Dados pendentes.

## Dados

- **Automáticos (Yahoo Finance / yfinance):** preço, valor de mercado, volume, DY 12m, frequência, meses de pagamento, CAGR 5a, anos sem corte, anos de listagem, Treasury 10a.
- **Calculados pela SEC (EDGAR XBRL, 10-K anuais):** FFO (definição Nareit: lucro + D&A − ganhos na venda + impairments − dividendos preferenciais), payout do FFO (+ ajuste configurável de 5 p.p. para aproximar o AFFO), FFO positivo/crescente em 5 anos, dívida líquida/EBITDAre. Requer e-mail de contato em *Metodologia* (exigência da SEC). A ficha da REIT mostra o cálculo ano a ano e as tags XBRL usadas.
- **Manuais:** rating, maior inquilino e P/AFFO. Qualquer valor digitado nos campos de AFFO/payout/dívida **prevalece** sobre o calculado.
- A detecção de corte usa o total anual de dividendos; dividendos extraordinários podem gerar falso corte → use o campo de correção manual.

## Uso em desenvolvimento

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pytest
python app.py --dev
python -m pytest -q tests
```

## Gerar o instalador

```bat
build.bat 1.0.0
```

Cria o ambiente, roda os testes, gera o executável (PyInstaller) e compila `installer\Painvest.iss` com o Inno Setup 7. Resultado: `dist_installer\Painvest_Setup_1.0.0.exe`.

O instalador é por usuário (sem admin); o banco fica em `{pasta do app}\data\painvest.db` e é preservado em atualizações.

## Backup

Menu **Backup** → *Exportar backup* gera um `.json` com REITs, dados manuais e metodologia. Em uma instalação nova, *Restaurar* recarrega tudo.

## Estrutura

```
app.py          Servidor Flask, rotas e inicialização
scoring.py      Filtros eliminatórios e matriz ponderada
market.py       Coleta automática (yfinance) e análise de dividendos
db.py           SQLite, configuração e backup
templates/      Páginas (ranking, edição, calendário, metodologia, backup)
installer/      Script do Inno Setup 7
tests/          Testes automáticos (pytest)
```
