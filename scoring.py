"""Metodologia: filtros eliminatórios + matriz de decisão ponderada.

Percentuais são armazenados como número (5.2 = 5,2%).
"""

SETORES = [
    "Net Lease - Varejo", "Net Lease - Diversificado", "Self-storage", "Industrial/Logística",
    "Residencial - Apartamentos", "Residencial - Casas/MH", "Saúde", "Data Centers",
    "Torres", "Cassinos/Experiências", "Outdoors", "Shoppings", "Strip Centers",
    "Escritórios", "Hotéis", "Hipotecas (mREIT)", "Florestas/Terras", "Outros",
]

RATINGS = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
           "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "NR"]
GRAU_INVESTIMENTO = RATINGS[:RATINGS.index("BBB-") + 1]

CONFIG_PADRAO = {
    "retencao_eua": 30.0,          # % retido na fonte (sem tratado Brasil-EUA)
    "treasury_10a": 4.2,           # % a.a., atualizado automaticamente quando possível
    "filtros": {
        "min_market_cap_bi": 5.0,       # US$ bilhões
        "min_vol_diario_mi": 20.0,      # US$ milhões/dia
        "min_anos_listada": 10,
        "min_anos_sem_corte": 10,
        "max_payout_mensal": 90.0,
        "max_payout_trimestral": 85.0,
        "max_div_ebitda": 6.0,
        "exigir_grau_investimento": True,
        "max_inquilino_pct": 20.0,
        "min_affo_anos_crescimento": 4,
        "setores_excluidos": ["Escritórios", "Hotéis", "Hipotecas (mREIT)"],
    },
    # Pesos (%) — soma deve ser 100
    "pesos": {
        "yield": 20, "frequencia": 15, "cagr": 15, "payout": 15,
        "alavancagem": 15, "rating": 10, "valuation": 10,
    },
    # Faixas de normalização: [valor para nota 0, valor para nota 10]
    "faixas": {
        "spread_yield": [-2.0, 1.0],   # yield líquido - Treasury (p.p.)
        "cagr": [0.0, 6.0],
        "payout": [90.0, 65.0],
        "alavancagem": [6.5, 4.0],
        "valuation": [1.2, 0.8],       # P/AFFO atual ÷ média 5 anos
    },
    "notas_frequencia": {"Mensal": 10, "Trimestral": 6, "Semestral": 2, "Anual": 0},
    "nota_compra": 7.0,
    "nota_observacao": 5.0,
}

NOMES_CRITERIOS = {
    "yield": "Yield líquido vs Treasury", "frequencia": "Frequência",
    "cagr": "Crescimento do dividendo (5a)", "payout": "Payout do AFFO",
    "alavancagem": "Dív. líq./EBITDA", "rating": "Rating", "valuation": "Valuation (P/AFFO)",
}


def _vazio(v):
    return v is None or v == ""


def linear(x, x0, x10):
    """Interpola nota 0..10 entre x0 (nota 0) e x10 (nota 10), com saturação."""
    if x0 == x10:
        return 10.0 if x >= x10 else 0.0
    nota = (x - x0) / (x10 - x0) * 10.0
    return max(0.0, min(10.0, nota))


def nota_rating(rating):
    if _vazio(rating) or rating not in RATINGS:
        return None
    if rating not in GRAU_INVESTIMENTO:
        return 0.0
    i = RATINGS.index(rating)
    if i <= RATINGS.index("A-"):
        return 10.0
    return {"BBB+": 8.0, "BBB": 6.0, "BBB-": 4.0}[rating]


def frequencia_efetiva(r):
    return r.get("frequencia_manual") or r.get("frequencia")


def anos_sem_corte_efetivo(r):
    m = r.get("anos_sem_corte_manual")
    return m if not _vazio(m) else r.get("anos_sem_corte")


def yield_liquido(r, cfg):
    if _vazio(r.get("dy_bruto")):
        return None
    return r["dy_bruto"] * (1 - cfg["retencao_eua"] / 100.0)


# ---------------- Etapa 1: filtros eliminatórios ----------------
def filtros(r, cfg):
    """Retorna lista de (nome, resultado, detalhe); resultado True/False/None (sem dado)."""
    f = cfg["filtros"]
    out = []

    def add(nome, valor, cond, detalhe):
        out.append((nome, None if _vazio(valor) else bool(cond(valor)), detalhe))

    freq = frequencia_efetiva(r)
    max_payout = f["max_payout_mensal"] if freq == "Mensal" else f["max_payout_trimestral"]

    add("AFFO positivo 5 anos", r.get("affo_positivo_5a"), lambda v: int(v) == 1, "Informar (Supplemental)")
    add(f"AFFO/ação crescente ≥ {f['min_affo_anos_crescimento']} de 5 anos", r.get("affo_anos_crescimento"),
        lambda v: int(v) >= f["min_affo_anos_crescimento"], f"{r.get('affo_anos_crescimento') or '—'} anos")
    asc = anos_sem_corte_efetivo(r)
    add(f"Sem corte de dividendo ≥ {f['min_anos_sem_corte']} anos", asc,
        lambda v: int(v) >= f["min_anos_sem_corte"], f"{asc if not _vazio(asc) else '—'} anos")
    add(f"Payout AFFO ≤ {max_payout:.0f}%", r.get("payout_affo"), lambda v: v <= max_payout,
        f"{r.get('payout_affo') if not _vazio(r.get('payout_affo')) else '—'}%")
    add(f"Dív. líq./EBITDA ≤ {f['max_div_ebitda']}x", r.get("div_liq_ebitda"),
        lambda v: v <= f["max_div_ebitda"], f"{r.get('div_liq_ebitda') or '—'}x")
    if f.get("exigir_grau_investimento"):
        add("Rating grau de investimento", r.get("rating"), lambda v: v in GRAU_INVESTIMENTO,
            r.get("rating") or "—")
    add(f"Listada ≥ {f['min_anos_listada']} anos", r.get("anos_listada"),
        lambda v: v >= f["min_anos_listada"],
        f"{r['anos_listada']:.0f} anos" if not _vazio(r.get("anos_listada")) else "—")
    add(f"Valor de mercado ≥ US$ {f['min_market_cap_bi']} bi", r.get("market_cap"),
        lambda v: v / 1e9 >= f["min_market_cap_bi"],
        f"US$ {r['market_cap'] / 1e9:.1f} bi" if not _vazio(r.get("market_cap")) else "—")
    add(f"Volume diário ≥ US$ {f['min_vol_diario_mi']} mi", r.get("vol_medio_usd"),
        lambda v: v / 1e6 >= f["min_vol_diario_mi"],
        f"US$ {r['vol_medio_usd'] / 1e6:.1f} mi" if not _vazio(r.get("vol_medio_usd")) else "—")
    add("Setor permitido", r.get("setor"), lambda v: v not in f["setores_excluidos"], r.get("setor") or "—")
    add(f"Maior inquilino ≤ {f['max_inquilino_pct']:.0f}% da receita", r.get("maior_inquilino_pct"),
        lambda v: v <= f["max_inquilino_pct"],
        f"{r.get('maior_inquilino_pct') if not _vazio(r.get('maior_inquilino_pct')) else '—'}%")
    return out


# ---------------- Etapa 2: matriz ponderada ----------------
def notas(r, cfg):
    fx = cfg["faixas"]
    n = {}
    yl = yield_liquido(r, cfg)
    n["yield"] = None if yl is None else linear(yl - cfg["treasury_10a"], *fx["spread_yield"])
    freq = frequencia_efetiva(r)
    n["frequencia"] = None if not freq else float(cfg["notas_frequencia"].get(freq, 0))
    n["cagr"] = None if _vazio(r.get("cagr_div_5a")) else linear(r["cagr_div_5a"], *fx["cagr"])
    n["payout"] = None if _vazio(r.get("payout_affo")) else linear(r["payout_affo"], *fx["payout"])
    n["alavancagem"] = None if _vazio(r.get("div_liq_ebitda")) else linear(r["div_liq_ebitda"], *fx["alavancagem"])
    n["rating"] = nota_rating(r.get("rating"))
    pa, pm = r.get("p_affo_atual"), r.get("p_affo_media5a")
    n["valuation"] = None if _vazio(pa) or _vazio(pm) or not pm else linear(pa / pm, *fx["valuation"])
    return n


def avaliar(r, cfg):
    """Avaliação completa de uma REIT."""
    fl = filtros(r, cfg)
    ns = notas(r, cfg)
    pesos = cfg["pesos"]
    peso_total = sum(pesos.values())
    disponivel = {k: v for k, v in ns.items() if v is not None}
    peso_disp = sum(pesos[k] for k in disponivel)
    nota = sum(ns[k] * pesos[k] for k in disponivel) / peso_disp if peso_disp else None
    completo = peso_disp == peso_total

    reprovados = [x for x in fl if x[1] is False]
    pendentes = [x for x in fl if x[1] is None]
    if reprovados:
        status = "Reprovada"
    elif pendentes or not completo:
        status = "Dados pendentes"
    elif nota >= cfg["nota_compra"]:
        status = "Candidata"
    elif nota >= cfg["nota_observacao"]:
        status = "Observação"
    else:
        status = "Descarte"

    return {
        "filtros": fl, "notas": ns, "nota": nota, "nota_completa": completo,
        "status": status, "reprovados": reprovados, "pendentes": pendentes,
        "yield_liquido": yield_liquido(r, cfg), "frequencia": frequencia_efetiva(r),
    }


ORDEM_STATUS = {"Candidata": 0, "Observação": 1, "Dados pendentes": 2, "Descarte": 3, "Reprovada": 4}


def ranquear(reits, cfg):
    itens = [(r, avaliar(r, cfg)) for r in reits]
    itens.sort(key=lambda x: (ORDEM_STATUS[x[1]["status"]], -(x[1]["nota"] or -1)))
    return itens


def validar_pesos(pesos):
    total = sum(pesos.values())
    return abs(total - 100) < 1e-6, total
