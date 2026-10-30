"""Coleta automática de dados de mercado via yfinance (Yahoo Finance).

Coleta: nome, preço, valor de mercado, volume médio em US$, dividend yield (12m),
frequência, meses de pagamento, CAGR do dividendo (5a), anos sem corte e anos de listagem.
AFFO, payout, dívida/EBITDA e rating NÃO têm fonte gratuita confiável -> entrada manual.
"""
from datetime import datetime


def analisar_dividendos(divs, hoje=None):
    """Recebe lista [(datetime, valor)] e devolve métricas de dividendos.

    Função pura (sem rede) para permitir testes.
    """
    hoje = hoje or datetime.now()
    res = {"pagamentos_12m": 0, "frequencia": None, "meses_pagamento": "",
           "cagr_div_5a": None, "anos_sem_corte": None, "div_12m": 0.0}
    if not divs:
        return res

    ult12 = [(d, v) for d, v in divs if (hoje - d).days <= 365]
    n = len(ult12)
    res["pagamentos_12m"] = n
    res["div_12m"] = sum(v for _, v in ult12)
    if n >= 10:
        res["frequencia"] = "Mensal"
    elif n >= 3:
        res["frequencia"] = "Trimestral"
    elif n == 2:
        res["frequencia"] = "Semestral"
    elif n == 1:
        res["frequencia"] = "Anual"
    res["meses_pagamento"] = ",".join(str(m) for m in sorted({d.month for d, _ in ult12}))

    # Totais por ano completo (exclui o ano corrente, ainda parcial)
    anos = {}
    for d, v in divs:
        if d.year < hoje.year:
            anos[d.year] = anos.get(d.year, 0.0) + v
    ult_ano = hoje.year - 1
    if ult_ano in anos and (ult_ano - 5) in anos and anos[ult_ano - 5] > 0:
        res["cagr_div_5a"] = round(((anos[ult_ano] / anos[ult_ano - 5]) ** (1 / 5) - 1) * 100, 2)

    # Anos consecutivos sem corte (queda > 3% no total anual = corte).
    # Dividendos extraordinários podem gerar falso corte -> use o campo manual para corrigir.
    seq = sorted(anos)
    if seq:
        sem_corte = 0
        for ano in range(ult_ano, seq[0], -1):
            if ano not in anos or (ano - 1) not in anos:
                break
            if anos[ano] < anos[ano - 1] * 0.97:
                break
            sem_corte += 1
        res["anos_sem_corte"] = sem_corte
    return res


def coletar(ticker):
    """Coleta dados de um ticker. Retorna dict com os campos automáticos."""
    import yfinance as yf  # import tardio: o app abre mesmo sem internet

    t = yf.Ticker(ticker)
    dados = {}
    fi = t.fast_info
    preco = float(fi["last_price"])
    dados["preco"] = round(preco, 2)
    try:
        dados["market_cap"] = float(fi["market_cap"])
    except Exception:
        dados["market_cap"] = None

    hist = t.history(period="3mo")
    if not hist.empty:
        dados["vol_medio_usd"] = float((hist["Volume"] * hist["Close"]).mean())

    try:
        info = t.info
        dados["nome"] = info.get("longName") or info.get("shortName")
        primeira = info.get("firstTradeDateEpochUtc")
        if primeira:
            dados["anos_listada"] = round((datetime.now() - datetime.fromtimestamp(primeira)).days / 365.25, 1)
    except Exception:
        pass

    divs = [(d.to_pydatetime().replace(tzinfo=None), float(v)) for d, v in t.dividends.items()]
    m = analisar_dividendos(divs)
    dados["dy_bruto"] = round(m.pop("div_12m") / preco * 100, 2) if preco else None
    dados.update(m)
    dados["atualizado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    dados["erro_coleta"] = None
    return dados


def treasury_10a():
    """Rendimento do Treasury de 10 anos (% a.a.) via ^TNX."""
    import yfinance as yf
    return round(float(yf.Ticker("^TNX").fast_info["last_price"]), 2)
