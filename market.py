"""Coleta automática de dados de mercado via yfinance (Yahoo Finance).

Coleta: nome, preço, valor de mercado, volume médio em US$, dividend yield (12m),
frequência, meses de pagamento, CAGR do dividendo (5a), anos sem corte e anos de listagem.
AFFO, payout, dívida/EBITDA e rating NÃO têm fonte gratuita confiável -> entrada manual.
"""
import logging
import time
from datetime import datetime, timedelta
from statistics import median


def analisar_dividendos(divs, hoje=None):
    """Recebe lista [(datetime, valor)] e devolve métricas de dividendos.

    Função pura (sem rede) para permitir testes.
    """
    hoje = hoje or datetime.now()
    res = {"pagamentos_12m": 0, "frequencia": None, "meses_pagamento": "",
           "cagr_div_5a": None, "anos_sem_corte": None, "div_12m": 0.0}
    divs = sorted((d, v) for d, v in divs if v and v > 0)
    if not divs:
        return res

    # 1) Separa dividendos extraordinários: valor > 1,5x a mediana dos vizinhos
    vals = [v for _, v in divs]
    regulares = []
    for i, (d, v) in enumerate(divs):
        viz = vals[max(0, i - 4):i] + vals[i + 1:i + 5]
        if viz and v > 1.5 * median(viz):
            continue
        regulares.append((d, v))
    if not regulares:
        return res

    # 2) Frequência e meses (pagamentos regulares nos últimos 12 meses)
    ult12 = [(d, v) for d, v in regulares if (hoje - d).days <= 365]
    n = len(ult12)
    res["pagamentos_12m"] = n
    if n >= 10:
        res["frequencia"] = "Mensal"
    elif n >= 3:
        res["frequencia"] = "Trimestral"
    elif n == 2:
        res["frequencia"] = "Semestral"
    elif n == 1:
        res["frequencia"] = "Anual"
    res["meses_pagamento"] = ",".join(str(m) for m in sorted({d.month for d, _ in ult12}))

    # 3) Dividendo anualizado = último pagamento regular x pagamentos/ano
    #    (evita erro de 13 datas-ex num ano quando a data-ex cai no fim do mês)
    por_ano = {"Mensal": 12, "Trimestral": 4, "Semestral": 2, "Anual": 1}.get(res["frequencia"])
    ultimo_d, ultimo_v = regulares[-1]
    res["div_12m"] = ultimo_v * por_ano if por_ano else sum(v for _, v in ult12)

    # 4) Cortes: pagamento regular < 97% do anterior, confirmado pelo pagamento seguinte,
    #    ou suspensão (intervalo > 2,5x o intervalo típico).
    intervalos = [(regulares[i][0] - regulares[i - 1][0]).days for i in range(1, len(regulares))]
    tipico = median(intervalos) if intervalos else 365
    ultimo_corte = None
    for i in range(1, len(regulares)):
        d, v = regulares[i]
        anterior = regulares[i - 1][1]
        if intervalos[i - 1] > 2.5 * tipico:
            ultimo_corte = d
        elif v < 0.97 * anterior:
            seguinte = regulares[i + 1][1] if i + 1 < len(regulares) else v
            if seguinte < 0.97 * anterior:
                ultimo_corte = d
    if (hoje - ultimo_d).days > 2.5 * tipico:  # pagamentos suspensos atualmente
        ultimo_corte = hoje
    inicio = ultimo_corte or regulares[0][0]
    res["anos_sem_corte"] = int((hoje - inicio).days / 365.25)

    # 5) CAGR 5 anos: pagamento regular atual vs. o de ~5 anos antes
    alvo = ultimo_d - timedelta(days=round(5 * 365.25))
    proximos = [(abs((d - alvo).days), v) for d, v in regulares if abs((d - alvo).days) <= 120]
    if proximos:
        v5 = min(proximos)[1]
        res["cagr_div_5a"] = round(((ultimo_v / v5) ** (1 / 5) - 1) * 100, 2)
    return res


def _limitado(e):
    """True se o erro indica limitação de requisições do Yahoo."""
    txt = f"{type(e).__name__} {e}".lower()
    return "ratelimit" in txt or "too many requests" in txt or "429" in txt


def com_retentativa(func, tentativas=3, espera=6.0, dormir=None):
    """Executa func(); se o Yahoo limitar, espera (6s, 12s...) e tenta de novo."""
    for i in range(tentativas):
        try:
            return func()
        except Exception as e:
            if not _limitado(e) or i + 1 == tentativas:
                raise
            (dormir or time.sleep)(espera * (i + 1))


class HistoricoVazio(RuntimeError):
    """O Yahoo às vezes responde vazio quando está limitando requisições."""


def obter_historico(t, ticker, dormir=None, espera=4.0):
    """Histórico diário com dividendos. Tenta períodos alternativos e espera entre tentativas,
    pois resposta vazia costuma indicar limitação temporária do Yahoo."""
    tentativas = [
        dict(period="max"),
        dict(start="1970-01-01"),
        dict(period="10y"),
        dict(period="1y"),
    ]
    ultimo_erro = None
    for i, kw in enumerate(tentativas):
        try:
            hist = com_retentativa(lambda: t.history(auto_adjust=False, actions=True, raise_errors=True, **kw), dormir=dormir)
            if hist is not None and not hist.empty:
                return hist
            ultimo_erro = HistoricoVazio(f"Yahoo retornou histórico vazio para {ticker} (provável limitação temporária).")
        except Exception as e:
            ultimo_erro = e
            logging.getLogger("painvest").warning("Yahoo %s %s: %s: %s", ticker, kw, type(e).__name__, str(e)[:200])
        if i + 1 < len(tentativas):
            (dormir or time.sleep)(espera * (i + 1))
    raise ultimo_erro


def coletar(ticker, existente=None):
    """Coleta dados de um ticker com o mínimo de requisições ao Yahoo.

    1 requisição: histórico completo (preço, volume, dividendos, início da negociação).
    + valor de mercado (fast_info) e, só na primeira vez, o nome da empresa.
    """
    import yfinance as yf  # import tardio: o app abre mesmo sem internet

    existente = existente or {}
    t = yf.Ticker(ticker)
    hist = obter_historico(t, ticker)

    dados = {}
    preco = float(hist["Close"].iloc[-1])
    dados["preco"] = round(preco, 2)
    rec = hist.tail(63)  # ~3 meses de pregões
    dados["vol_medio_usd"] = float((rec["Volume"] * rec["Close"]).mean())
    inicio = hist.index[0].to_pydatetime().replace(tzinfo=None)
    dados["anos_listada"] = round((datetime.now() - inicio).days / 365.25, 1)

    try:
        dados["market_cap"] = float(com_retentativa(lambda: t.fast_info["market_cap"]))
    except Exception:
        pass  # mantém o valor anterior gravado no banco

    if not existente.get("nome"):
        try:
            info = com_retentativa(lambda: t.info)
            dados["nome"] = info.get("longName") or info.get("shortName")
        except Exception:
            pass

    serie = hist["Dividends"] if "Dividends" in hist else []
    divs = [(d.to_pydatetime().replace(tzinfo=None), float(v)) for d, v in serie.items() if v]
    if dados["anos_listada"] < 11:
        # Histórico curto (veio de uma tentativa alternativa): busca dividendos completos à parte
        try:
            completos = com_retentativa(lambda: t.dividends)
            if completos is not None and len(completos) > len(divs):
                divs = [(d.to_pydatetime().replace(tzinfo=None), float(v)) for d, v in completos.items() if v]
                dados["anos_listada"] = max(dados["anos_listada"],
                                            round((datetime.now() - divs[0][0]).days / 365.25, 1))
        except Exception:
            pass
        if existente.get("anos_listada"):
            dados["anos_listada"] = max(dados["anos_listada"], existente["anos_listada"])
    m = analisar_dividendos(divs)
    dados["dy_bruto"] = round(m.pop("div_12m") / preco * 100, 2) if preco else None
    dados.update(m)
    dados["atualizado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    dados["erro_coleta"] = None
    return dados


def treasury_10a():
    """Rendimento do Treasury de 10 anos (% a.a.) via ^TNX."""
    import yfinance as yf
    hist = com_retentativa(lambda: yf.Ticker("^TNX").history(period="5d", raise_errors=True))
    return round(float(hist["Close"].iloc[-1]), 2)
