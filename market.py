"""Coleta automática de dados de mercado via yfinance (Yahoo Finance).

Coleta: nome, preço, valor de mercado, volume médio em US$, dividend yield (12m),
frequência, meses de pagamento, CAGR do dividendo (5a), anos sem corte e anos de listagem.
AFFO, payout, dívida/EBITDA e rating NÃO têm fonte gratuita confiável -> entrada manual.
"""
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
