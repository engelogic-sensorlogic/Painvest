"""Coleta de fundamentos na SEC (EDGAR XBRL companyfacts) — fonte oficial e gratuita.

Calcula aproximações padronizadas (definição Nareit) a partir dos balanços anuais (10-K):
  FFO      = Lucro líquido + Depreciação/Amortização − Ganhos na venda de imóveis
             + Impairments − Dividendos preferenciais
  EBITDAre = Lucro líquido + Juros + Impostos + D&A − Ganhos + Impairments
  Payout   = Dividendos pagos aos ordinaristas ÷ FFO (o ajuste FFO→AFFO por setor é feito no scoring)
  Dívida líquida / EBITDAre anualizado (último trimestre x 4, como as REITs divulgam;
  na falta de dados trimestrais, usa o último ano fiscal)

A SEC exige um User-Agent com e-mail de contato (configurado na tela Metodologia).
"""
import json
import os
import time
import urllib.request
from datetime import date

URL_TICKERS = "https://www.sec.gov/files/company_tickers.json"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Tags XBRL candidatas, em ordem de preferência
TAGS = {
    "lucro": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "da": ["DepreciationAndAmortization", "DepreciationDepletionAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "RealEstateDepreciationAndAmortization",
           "DepreciationAndAmortizationRealEstate", "Depreciation"],
    "ganhos": ["GainsLossesOnSalesOfInvestmentRealEstate", "GainLossOnSaleOfProperties",
               "GainLossOnSaleOfRealEstateInvestmentProperty", "GainLossOnDispositionOfAssets1",
               "GainLossOnSaleOfPropertyPlantEquipment", "GainLossOnDispositionOfAssets"],
    "impairment": ["ImpairmentOfRealEstate", "ImpairmentOfLongLivedAssetsHeldForUse",
                   "AssetImpairmentCharges", "ImpairmentOfLongLivedAssetsToBeDisposedOf"],
    "pref": ["DividendsPreferredStock", "PreferredStockDividendsIncomeStatementImpact",
             "DividendsPreferredStockCash"],
    # Juros: tags novas (taxonomia 2024+) e, por último, juros pagos no fluxo de caixa
    "juros": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseOperating",
              "InterestExpenseDebt", "InterestAndDebtExpense", "InterestExpenseNet",
              "InterestExpenseDebtExcludingAmortization", "InterestPaidNet", "InterestPaid"],
    "impostos": ["IncomeTaxExpenseBenefit"],
    "dividendos": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "DividendsCommonStockCash",
                   "PaymentsOfOrdinaryDividends", "DividendsCommonStock"],
    "acoes": ["WeightedAverageNumberOfDilutedSharesOutstanding",
              "WeightedAverageNumberOfSharesOutstandingBasic"],
    "caixa": ["CashAndCashEquivalentsAtCarryingValue",
              "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
}
# Dívida: tags "totais" (usa a maior) ou soma de componentes
TAGS_DIVIDA_TOTAL = ["DebtLongtermAndShorttermCombinedAmount", "LongTermDebt", "DebtInstrumentCarryingAmount",
                     "LongTermDebtAndCapitalLeaseObligations"]
TAGS_DIVIDA_COMPONENTES = ["UnsecuredDebt", "SecuredDebt", "SeniorNotes", "NotesPayable",
                           "LineOfCredit", "LongTermLineOfCredit", "CommercialPaper",
                           "UnsecuredLongTermDebt", "SecuredLongTermDebt", "OtherLongTermDebt"]


# ---------------- Acesso à SEC ----------------
def _get_json(url, contato, tentativas=2):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"Painvest uso-pessoal {contato}",
        "Accept-Encoding": "identity",
    })
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i + 1 == tentativas:
                raise
            time.sleep(1.0)


def mapa_tickers(contato, cache_dir, max_dias=7):
    """Mapa TICKER -> CIK, com cache local de 7 dias."""
    cache = os.path.join(cache_dir, "sec_tickers.json")
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < max_dias * 86400:
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    dados = _get_json(URL_TICKERS, contato)
    mapa = {v["ticker"].upper(): int(v["cik_str"]) for v in dados.values()}
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(mapa, f)
    return mapa


def baixar_fatos(cik, contato):
    return _get_json(URL_FACTS.format(cik=cik), contato)


# ---------------- Extração ----------------
def _duracao_dias(item):
    try:
        return (date.fromisoformat(item["end"]) - date.fromisoformat(item["start"])).days
    except (KeyError, ValueError):
        return None


def serie_anual(fatos, tags, unidade="USD"):
    """{ano_fiscal_fim: valor} de períodos anuais (~1 ano) informados em 10-K.

    Usa a primeira tag (em ordem de preferência) que tiver dados recentes.
    Retorna (serie, tag_usada).
    """
    gaap = fatos.get("facts", {}).get("us-gaap", {})
    melhor, tag_melhor = {}, None
    for tag in tags:
        itens = gaap.get(tag, {}).get("units", {}).get(unidade, [])
        serie = {}
        for it in itens:
            dur = _duracao_dias(it)
            if dur is None or not 340 <= dur <= 380 or not str(it.get("form", "")).startswith("10-K"):
                continue
            ano = int(it["end"][:4])
            # mantém o valor do arquivamento mais recente (inclui reapresentações)
            anterior = serie.get(ano)
            if anterior is None or it.get("filed", "") >= anterior[1]:
                serie[ano] = (float(it["val"]), it.get("filed", ""))
        serie = {a: v for a, (v, _) in serie.items()}
        if serie and (not melhor or max(serie) > max(melhor)):
            melhor, tag_melhor = serie, tag
    return melhor, tag_melhor


def serie_trimestral(fatos, tags, unidade="USD"):
    """{data_fim: valor} de trimestres isolados (~3 meses), de 10-Q e 10-K.

    Muitas empresas informam alguns itens (D&A, impairment) só como ACUMULADO do ano
    (3, 6, 9 e 12 meses). O trimestre é obtido pela diferença entre acumulados
    consecutivos com o mesmo início: T2 = 6m − 3m, T3 = 9m − 6m, T4 = 12m − 9m.
    Valores trimestrais informados diretamente têm prioridade.
    Retorna (serie, tag_usada) da tag com o trimestre mais recente.
    """
    gaap = fatos.get("facts", {}).get("us-gaap", {})
    melhor, tag_melhor = {}, None
    for tag in tags:
        unicos = {}
        for it in gaap.get(tag, {}).get("units", {}).get(unidade, []):
            dur = _duracao_dias(it)
            if dur is None:
                continue
            n = round(dur / 91.3)
            if not 1 <= n <= 4 or abs(dur - n * 91.3) > 20:
                continue
            k = (it["start"], it["end"])
            if k not in unicos or it.get("filed", "") >= unicos[k][2]:
                unicos[k] = (n, float(it["val"]), it.get("filed", ""))

        serie, grupos = {}, {}
        for (ini, fim), (n, v, _) in unicos.items():
            if n == 1:
                serie[fim] = v                      # trimestre informado diretamente
            grupos.setdefault(ini, {})[n] = (fim, v)
        for acum in grupos.values():               # trimestres derivados dos acumulados
            for n in (2, 3, 4):
                if n in acum and (n - 1) in acum:
                    fim, v = acum[n]
                    serie.setdefault(fim, v - acum[n - 1][1])
        if serie and (not melhor or max(serie) > max(melhor)):
            melhor, tag_melhor = serie, tag
    return melhor, tag_melhor


def valor_instante(fatos, tags, quando, unidade="USD"):
    """Valor de balanço. `quando`: ano fiscal (int, 10-K) ou data exata 'AAAA-MM-DD'.

    Retorna (valor, tag)."""
    gaap = fatos.get("facts", {}).get("us-gaap", {})

    def casa(it):
        if "start" in it:
            return False
        if isinstance(quando, int):
            return it.get("end", "")[:4] == str(quando) and str(it.get("form", "")).startswith("10-K")
        return it.get("end") == quando

    for tag in tags:
        itens = [it for it in gaap.get(tag, {}).get("units", {}).get(unidade, []) if casa(it)]
        if itens:
            it = max(itens, key=lambda x: (x["end"], x.get("filed", "")))
            return float(it["val"]), tag
    return None, None


def valor_trimestre(fatos, chave, fim):
    """Valor do trimestre encerrado em `fim`, testando as tags candidatas em ordem."""
    for tag in TAGS[chave]:
        serie, _ = serie_trimestral(fatos, [tag])
        if fim in serie:
            return serie[fim], tag
    return None, None


def valor_anual(fatos, chave, ano):
    """Valor do ano fiscal `ano`, testando as tags candidatas em ordem."""
    for tag in TAGS[chave]:
        serie, _ = serie_anual(fatos, [tag])
        if ano in serie:
            return serie[ano], tag
    return None, None


def divida_total(fatos, quando):
    totais = [(v, t) for v, t in (valor_instante(fatos, [t], quando) for t in TAGS_DIVIDA_TOTAL) if v]
    if totais:
        return max(totais)
    soma, usadas = 0.0, []
    for t in TAGS_DIVIDA_COMPONENTES:
        v, _ = valor_instante(fatos, [t], quando)
        if v:
            soma += v
            usadas.append(t)
    return (soma, "+".join(usadas)) if usadas else (None, None)


def calcular(fatos):
    """Calcula os indicadores a partir do JSON companyfacts. Função pura (testável)."""
    s, tags = {}, {}
    for chave, lista in TAGS.items():
        unidade = "shares" if chave == "acoes" else "USD"
        s[chave], tags[chave] = serie_anual(fatos, lista, unidade)

    if not s["lucro"] or not s["da"]:
        raise ValueError("Balanço sem lucro líquido ou depreciação em XBRL padrão.")

    anos = sorted(a for a in s["lucro"] if a in s["da"])
    ffo = {}
    for a in anos:
        ffo[a] = (s["lucro"][a] + s["da"][a] - s["ganhos"].get(a, 0.0)
                  + s["impairment"].get(a, 0.0) - s["pref"].get(a, 0.0))
    ult = anos[-1]
    ult5 = [a for a in anos if a > ult - 5]
    ffo_ps = {a: ffo[a] / s["acoes"][a] for a in anos if s["acoes"].get(a)}

    res = {"ffo_ano_ref": ult, "detalhe": {"tags": tags, "anos": {}}}
    # FFO positivo nos últimos 5 anos (exige 5 anos de histórico)
    res["ffo_positivo_calc"] = (1 if all(ffo[a] > 0 for a in ult5) else 0) if len(ult5) >= 5 else None
    # Anos com FFO/ação crescente (comparações dentro da janela de 5 anos)
    comp = [a for a in ult5 if a in ffo_ps and (a - 1) in ffo_ps]
    res["ffo_anos_cresc_calc"] = sum(1 for a in comp if ffo_ps[a] > ffo_ps[a - 1]) if len(comp) >= 4 else None

    # Payout do último ano
    div = s["dividendos"].get(ult)
    payout = None
    if div and ffo[ult] > 0:
        payout = abs(div) / ffo[ult] * 100
        if not 0 < payout < 300:
            payout = None
    res["payout_calc"] = round(payout, 1) if payout is not None else None

    # Dívida líquida / EBITDAre — preferência: último trimestre anualizado (padrão das REITs).
    # Cada componente é buscado NA DATA EXATA, testando todas as tags candidatas.
    # Juros e D&A são obrigatórios: se faltarem, usa o ano fiscal (nunca assume zero).
    lucros_q, _ = serie_trimestral(fatos, TAGS["lucro"])
    ebitda, base, quando, comp = None, None, None, {}
    for f in sorted(lucros_q, reverse=True)[:2]:          # trimestre mais recente (ou o anterior)
        if f[:4] < str(ult):
            break
        comp = {k: valor_trimestre(fatos, k, f) for k in ("lucro", "juros", "impostos", "da", "ganhos", "impairment")}
        dvd_q, _ = divida_total(fatos, f)
        if comp["lucro"][0] is not None and comp["da"][0] is not None and comp["juros"][0] is not None and dvd_q:
            v = {k: (c[0] or 0.0) for k, c in comp.items()}
            ebitda = 4 * (v["lucro"] + v["juros"] + v["impostos"] + v["da"] - v["ganhos"] + v["impairment"])
            base, quando = f"trimestre encerrado em {f} x 4", f
            break
    if ebitda is None or ebitda <= 0:
        comp = {k: valor_anual(fatos, k, ult) for k in ("lucro", "juros", "impostos", "da", "ganhos", "impairment")}
        if comp["juros"][0] is None:
            # Sem juros o EBITDA sai subestimado: melhor não calcular do que exibir número enganoso
            ebitda, base, quando = None, f"não calculado — juros não encontrados no ano fiscal {ult}", ult
        else:
            v = {k: (c[0] or 0.0) for k, c in comp.items()}
            ebitda = v["lucro"] + v["juros"] + v["impostos"] + v["da"] - v["ganhos"] + v["impairment"]
            base, quando = f"ano fiscal {ult}", ult
    dvd, tag_dvd = divida_total(fatos, quando)
    caixa, _ = valor_instante(fatos, TAGS["caixa"], quando)
    alav = None
    if dvd and ebitda and ebitda > 0:
        alav = (dvd - (caixa or 0.0)) / ebitda
        if not 0 <= alav < 30:
            alav = None
    res["div_ebitda_calc"] = round(alav, 2) if alav is not None else None
    tags["divida"] = tag_dvd

    for a in anos[-6:]:
        res["detalhe"]["anos"][a] = {
            "lucro": s["lucro"][a], "da": s["da"][a], "ganhos": s["ganhos"].get(a),
            "impairment": s["impairment"].get(a), "ffo": ffo[a],
            "ffo_acao": ffo_ps.get(a), "dividendos": s["dividendos"].get(a),
        }
    res["detalhe"]["ultimo"] = {"ebitda": ebitda, "divida": dvd, "caixa": caixa, "base_ebitda": base,
                                "componentes": {k: {"valor": c[0], "tag": c[1]} for k, c in comp.items()}}
    return res


def coletar(ticker, contato, cache_dir):
    """Retorna dict pronto para gravar no banco."""
    from datetime import datetime
    mapa = mapa_tickers(contato, cache_dir)
    cik = mapa.get(ticker.upper()) or mapa.get(ticker.upper().replace(".", "-"))
    if not cik:
        raise ValueError(f"Ticker {ticker} não encontrado na SEC.")
    r = calcular(baixar_fatos(cik, contato))
    return {
        "payout_calc": r["payout_calc"], "div_ebitda_calc": r["div_ebitda_calc"],
        "ffo_positivo_calc": r["ffo_positivo_calc"], "ffo_anos_cresc_calc": r["ffo_anos_cresc_calc"],
        "ffo_ano_ref": r["ffo_ano_ref"], "sec_detalhe": json.dumps(r["detalhe"]),
        "sec_atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M"), "sec_erro": None,
    }
