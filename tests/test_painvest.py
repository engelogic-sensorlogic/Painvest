import io
import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import market  # noqa: E402
import scoring  # noqa: E402

COMPLETA = {
    "ticker": "TST", "setor": "Net Lease - Varejo", "affo_positivo_5a": 1, "affo_anos_crescimento": 5,
    "anos_sem_corte": 15, "payout_affo": 75.0, "div_liq_ebitda": 5.4, "rating": "A-",
    "anos_listada": 30, "market_cap": 50e9, "vol_medio_usd": 300e6, "maior_inquilino_pct": 3.5,
    "dy_bruto": 5.6, "frequencia": "Mensal", "cagr_div_5a": 3.0, "p_affo_atual": 13.0, "p_affo_media5a": 15.0,
}


def cfg():
    return json.loads(json.dumps(scoring.CONFIG_PADRAO))


def test_linear_e_saturacao():
    assert scoring.linear(0, 0, 6) == 0
    assert scoring.linear(3, 0, 6) == 5
    assert scoring.linear(99, 0, 6) == 10
    assert scoring.linear(65, 90, 65) == 10  # escala decrescente
    assert scoring.linear(77.5, 90, 65) == 5


def test_pesos_padrao_somam_100():
    assert scoring.validar_pesos(scoring.CONFIG_PADRAO["pesos"])[0]


def test_reit_completa_e_candidata():
    av = scoring.avaliar(COMPLETA, cfg())
    assert all(r is True for _, r, _ in av["filtros"])
    assert av["nota_completa"]
    assert av["status"] in ("Candidata", "Observação")
    assert av["yield_liquido"] == pytest.approx(3.92)


def test_setor_excluido_reprova():
    r = dict(COMPLETA, setor="Escritórios")
    assert scoring.avaliar(r, cfg())["status"] == "Reprovada"


def test_payout_limite_depende_da_frequencia():
    r = dict(COMPLETA, payout_affo=88.0)
    assert scoring.avaliar(r, cfg())["status"] != "Reprovada"          # mensal: limite 90
    r["frequencia"] = "Trimestral"
    assert scoring.avaliar(r, cfg())["status"] == "Reprovada"          # trimestral: limite 85


def test_junk_reprova_e_override_manual():
    assert scoring.avaliar(dict(COMPLETA, rating="BB+"), cfg())["status"] == "Reprovada"
    r = dict(COMPLETA, anos_sem_corte=3, anos_sem_corte_manual=12)
    assert scoring.avaliar(r, cfg())["status"] != "Reprovada"


def test_dados_faltando_ficam_pendentes():
    av = scoring.avaliar({"ticker": "X", "setor": "Self-storage"}, cfg())
    assert av["status"] == "Dados pendentes"
    assert av["nota"] is None


def test_analise_dividendos_mensal():
    hoje = datetime(2026, 10, 30)
    divs = []
    for ano in range(2014, 2027):
        for mes in range(1, 13):
            d = datetime(ano, mes, 1)
            if d <= hoje:
                divs.append((d, 0.20 * (1.03 ** (ano - 2014))))
    m = market.analisar_dividendos(divs, hoje)
    assert m["frequencia"] == "Mensal"
    assert m["cagr_div_5a"] == pytest.approx(3.0, abs=0.01)
    assert m["anos_sem_corte"] == 12  # histórico desde 2014, sem cortes


def test_mensal_data_ex_fim_de_mes_nao_gera_falso_corte():
    """Caso Realty Income: data-ex no último dia do mês -> anos com 11 ou 13 pagamentos."""
    hoje = datetime(2026, 10, 30)
    divs, valor = [], 0.20
    for ano in range(2013, 2027):
        for mes in range(1, 13):
            # dezembro: em anos pares a data-ex cai em 1º/jan do ano seguinte
            d = datetime(ano + 1, 1, 1) if (mes == 12 and ano % 2 == 0) else datetime(ano, mes, 28)
            if d <= hoje:
                divs.append((d, valor))
                valor *= 1.002  # aumento pequeno e contínuo
    anos = {}
    for d, _ in divs:
        anos[d.year] = anos.get(d.year, 0) + 1
    assert {11, 13} <= set(anos.values())  # confirma o cenário de 11/13 pagamentos
    m = market.analisar_dividendos(divs, hoje)
    assert m["frequencia"] == "Mensal"
    assert m["anos_sem_corte"] >= 10
    assert m["cagr_div_5a"] == pytest.approx((1.002 ** 12 - 1) * 100, abs=0.1)  # CAGR anual


def test_extraordinario_nao_conta_como_corte():
    hoje = datetime(2026, 10, 30)
    divs = [(datetime(a, m, 15), 1.0) for a in range(2012, 2027) for m in (3, 6, 9, 12)
            if datetime(a, m, 15) <= hoje]
    divs.append((datetime(2022, 12, 28), 3.5))  # dividendo especial
    m = market.analisar_dividendos(divs, hoje)
    assert m["frequencia"] == "Trimestral"
    assert m["anos_sem_corte"] >= 14
    assert m["div_12m"] == pytest.approx(4.0)


def test_suspensao_conta_como_corte():
    hoje = datetime(2026, 10, 30)
    divs = [(datetime(a, mes, 1), 0.3) for a in range(2012, 2027) for mes in range(1, 13)
            if datetime(a, mes, 1) <= hoje and not (datetime(2020, 5, 1) <= datetime(a, mes, 1) <= datetime(2021, 6, 1))]
    m = market.analisar_dividendos(divs, hoje)
    assert m["anos_sem_corte"] == 5  # retomada em jul/2021


def test_analise_dividendos_corte_trimestral():
    hoje = datetime(2026, 10, 30)
    divs = []
    for ano in range(2015, 2027):
        valor = 1.0 if ano != 2020 else 0.5
        for mes in (3, 6, 9, 12):
            d = datetime(ano, mes, 15)
            if d <= hoje:
                divs.append((d, valor))
    m = market.analisar_dividendos(divs, hoje)
    assert m["frequencia"] == "Trimestral"
    assert m["meses_pagamento"] == "3,6,9,12"
    assert m["anos_sem_corte"] == 6  # corte em mar/2020


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    caminho = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "DB_PATH", caminho)
    for f in ("conectar",):
        pass
    db.inicializar(caminho)
    # Redireciona o caminho padrão para o banco de teste
    orig = db.conectar
    monkeypatch.setattr(db, "conectar", lambda path=None: orig(path or caminho))
    import app as appmod
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_rotas_e_backup(cliente):
    db.salvar("TST", {k: v for k, v in COMPLETA.items() if k != "ticker"})
    for url in ["/", "/reit/TST", "/calendario", "/config", "/backup"]:
        assert cliente.get(url).status_code == 200, url
    assert "TST" in cliente.get("/").get_data(as_text=True)

    # Edição manual
    resp = cliente.post("/reit/TST", data={"setor": "Self-storage", "affo_positivo_5a": "1",
                                           "payout_affo": "70,5", "rating": "BBB+"})
    assert resp.status_code == 302
    assert db.obter("TST")["payout_affo"] == 70.5

    # Backup -> apaga -> restaura
    pacote = cliente.get("/backup/exportar").get_data()
    db.excluir("TST")
    assert db.obter("TST") is None
    cliente.post("/backup/restaurar", data={"arquivo": (io.BytesIO(pacote), "b.json")},
                 content_type="multipart/form-data")
    assert db.obter("TST")["rating"] == "BBB+"


def test_config_rejeita_pesos_errados(cliente):
    c = cfg()
    form = {"retencao_eua": "30", "treasury_10a": "4,2", "nota_compra": "7", "nota_observacao": "5"}
    form.update({k: str(v) for k, v in c["filtros"].items() if not isinstance(v, (list, bool))})
    form.update({f"peso_{k}": "10" for k in c["pesos"]})  # soma 70
    form.update({f"faixa_{k}_0": str(v[0]) for k, v in c["faixas"].items()})
    form.update({f"faixa_{k}_10": str(v[1]) for k, v in c["faixas"].items()})
    form.update({f"freq_{k}": str(v) for k, v in c["notas_frequencia"].items()})
    resp = cliente.post("/config", data=form, follow_redirects=True)
    assert "soma dos pesos" in resp.get_data(as_text=True)
