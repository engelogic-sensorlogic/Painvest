"""Painvest — triagem de REITs americanos por metodologia própria.

Executa um servidor Flask local e abre o navegador.
"""
import io
import json
import os
import socket
import sys
import threading
import webbrowser
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for

import db
import scoring

VERSAO = "1.0.1"
PORTA = 5077

app = Flask(__name__, template_folder=db.resource_path("templates"),
            static_folder=db.resource_path("static"))
app.secret_key = "painvest-local"

TICKERS_INICIAIS = {
    "O": "Net Lease - Varejo", "ADC": "Net Lease - Varejo", "NNN": "Net Lease - Varejo",
    "WPC": "Net Lease - Diversificado", "PSA": "Self-storage", "EXR": "Self-storage",
    "CUBE": "Self-storage", "PLD": "Industrial/Logística", "EGP": "Industrial/Logística",
    "VICI": "Cassinos/Experiências", "GLPI": "Cassinos/Experiências",
    "ELS": "Residencial - Casas/MH", "MAA": "Residencial - Apartamentos",
    "ESS": "Residencial - Apartamentos", "LAMR": "Outdoors", "AMT": "Torres",
    "EQIX": "Data Centers", "WELL": "Saúde", "LTC": "Saúde", "SPG": "Shoppings",
}


def cfg():
    return db.ler_config(scoring.CONFIG_PADRAO)


def _num(v, tipo=float):
    v = (v or "").strip().replace(",", ".")
    if v == "":
        return None
    return tipo(float(v))


@app.context_processor
def globais():
    return {"versao": VERSAO, "nomes_criterios": scoring.NOMES_CRITERIOS}


@app.template_filter("n")
def fmt_num(v, casas=2, sufixo=""):
    if v is None or v == "":
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".") + sufixo


# ---------------- Páginas ----------------
@app.route("/")
def index():
    c = cfg()
    itens = scoring.ranquear(db.listar(), c)
    return render_template("index.html", itens=itens, cfg=c)


@app.route("/reit/<ticker>", methods=["GET", "POST"])
def editar(ticker):
    ticker = ticker.upper()
    if request.method == "POST":
        f = request.form
        try:
            dados = {
                "setor": f.get("setor") or None,
                "affo_positivo_5a": {"": None, "1": 1, "0": 0}[f.get("affo_positivo_5a", "")],
                "affo_anos_crescimento": _num(f.get("affo_anos_crescimento"), int),
                "payout_affo": _num(f.get("payout_affo")),
                "div_liq_ebitda": _num(f.get("div_liq_ebitda")),
                "rating": f.get("rating") or None,
                "maior_inquilino_pct": _num(f.get("maior_inquilino_pct")),
                "p_affo_atual": _num(f.get("p_affo_atual")),
                "p_affo_media5a": _num(f.get("p_affo_media5a")),
                "frequencia_manual": f.get("frequencia_manual") or None,
                "anos_sem_corte_manual": _num(f.get("anos_sem_corte_manual"), int),
                "notas": f.get("notas") or None,
            }
        except ValueError:
            flash("Valor numérico inválido. Use números, ex.: 5,4", "erro")
            return redirect(url_for("editar", ticker=ticker))
        db.salvar(ticker, dados)
        flash(f"{ticker} salvo.", "ok")
        return redirect(url_for("editar", ticker=ticker))

    r = db.obter(ticker)
    if not r:
        flash(f"{ticker} não cadastrado.", "erro")
        return redirect(url_for("index"))
    c = cfg()
    return render_template("editar.html", r=r, av=scoring.avaliar(r, c), cfg=c,
                           setores=scoring.SETORES, ratings=scoring.RATINGS)


@app.post("/novo")
def novo():
    tickers = [t.strip().upper() for t in request.form.get("tickers", "").replace(";", ",").split(",") if t.strip()]
    for t in tickers:
        if not db.obter(t):
            db.salvar(t, {"setor": TICKERS_INICIAIS.get(t)})
    if tickers:
        flash(f"Adicionado(s): {', '.join(tickers)}. Clique em 'Atualizar cotações' para coletar os dados.", "ok")
    return redirect(url_for("index"))


@app.post("/reit/<ticker>/excluir")
def excluir(ticker):
    db.excluir(ticker)
    flash(f"{ticker.upper()} excluído.", "ok")
    return redirect(url_for("index"))


def _coletar(ticker):
    import market
    try:
        db.salvar(ticker, market.coletar(ticker))
        return True
    except Exception as e:  # sem internet, ticker inválido etc.
        db.salvar(ticker, {"erro_coleta": f"{type(e).__name__}: {e}"[:200]})
        return False


@app.post("/atualizar")
def atualizar_todos():
    import market
    c = cfg()
    try:
        c["treasury_10a"] = market.treasury_10a()
        db.gravar_config(c)
    except Exception:
        flash("Não foi possível atualizar o Treasury 10 anos; mantido o valor da configuração.", "erro")
    ok = falhas = 0
    for r in db.listar():
        if _coletar(r["ticker"]):
            ok += 1
        else:
            falhas += 1
    flash(f"Atualização concluída: {ok} ok, {falhas} com falha.", "ok" if not falhas else "erro")
    return redirect(url_for("index"))


@app.post("/atualizar/<ticker>")
def atualizar_um(ticker):
    if _coletar(ticker.upper()):
        flash(f"{ticker.upper()} atualizado.", "ok")
    else:
        flash(f"Falha ao coletar {ticker.upper()}. Verifique a internet e o ticker.", "erro")
    return redirect(request.referrer or url_for("index"))


@app.route("/calendario")
def calendario():
    c = cfg()
    itens = [(r, a) for r, a in scoring.ranquear(db.listar(), c) if a["status"] != "Reprovada"]
    linhas = []
    for r, a in itens:
        meses = {int(m) for m in (r.get("meses_pagamento") or "").split(",") if m}
        linhas.append((r, a, meses))
    return render_template("calendario.html", linhas=linhas)


@app.route("/config", methods=["GET", "POST"])
def config():
    c = cfg()
    if request.method == "POST":
        f = request.form
        try:
            c["retencao_eua"] = _num(f["retencao_eua"])
            c["treasury_10a"] = _num(f["treasury_10a"])
            for k in ["min_market_cap_bi", "min_vol_diario_mi", "max_payout_mensal",
                      "max_payout_trimestral", "max_div_ebitda", "max_inquilino_pct"]:
                c["filtros"][k] = _num(f[k])
            for k in ["min_anos_listada", "min_anos_sem_corte", "min_affo_anos_crescimento"]:
                c["filtros"][k] = _num(f[k], int)
            c["filtros"]["exigir_grau_investimento"] = "exigir_grau_investimento" in f
            c["filtros"]["setores_excluidos"] = f.getlist("setores_excluidos")
            for k in c["pesos"]:
                c["pesos"][k] = _num(f[f"peso_{k}"])
            for k in c["faixas"]:
                c["faixas"][k] = [_num(f[f"faixa_{k}_0"]), _num(f[f"faixa_{k}_10"])]
            for k in c["notas_frequencia"]:
                c["notas_frequencia"][k] = _num(f[f"freq_{k}"])
            c["nota_compra"] = _num(f["nota_compra"])
            c["nota_observacao"] = _num(f["nota_observacao"])
        except (ValueError, TypeError, KeyError):
            flash("Valor inválido em algum campo.", "erro")
            return redirect(url_for("config"))
        ok, total = scoring.validar_pesos(c["pesos"])
        if not ok:
            flash(f"A soma dos pesos deve ser 100 (atual: {total:g}).", "erro")
            return redirect(url_for("config"))
        db.gravar_config(c)
        flash("Configuração salva.", "ok")
        return redirect(url_for("config"))
    return render_template("config.html", cfg=c, setores=scoring.SETORES)


@app.post("/config/padrao")
def config_padrao():
    db.gravar_config(scoring.CONFIG_PADRAO)
    flash("Metodologia restaurada para o padrão.", "ok")
    return redirect(url_for("config"))


# ---------------- Backup ----------------
@app.route("/backup")
def backup():
    return render_template("backup.html", db_path=db.DB_PATH)


@app.get("/backup/exportar")
def backup_exportar():
    pacote = db.exportar_json()
    pacote["exportado_em"] = datetime.now().isoformat(timespec="seconds")
    dados = json.dumps(pacote, ensure_ascii=False, indent=2).encode("utf-8")
    nome = f"painvest_backup_{datetime.now():%Y%m%d_%H%M}.json"
    return send_file(io.BytesIO(dados), mimetype="application/json", as_attachment=True, download_name=nome)


@app.post("/backup/restaurar")
def backup_restaurar():
    arq = request.files.get("arquivo")
    if not arq or not arq.filename:
        flash("Selecione o arquivo de backup.", "erro")
        return redirect(url_for("backup"))
    try:
        n = db.importar_json(json.load(arq))
        flash(f"Backup restaurado: {n} REITs.", "ok")
    except Exception as e:
        flash(f"Falha ao restaurar: {e}", "erro")
    return redirect(url_for("backup"))


@app.post("/encerrar")
def encerrar():
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return "<p style='font-family:sans-serif'>Painvest encerrado. Pode fechar esta aba.</p>"


# ---------------- Inicialização ----------------
def porta_em_uso(porta):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", porta)) == 0


def primeira_execucao():
    if not db.listar():
        for t, setor in TICKERS_INICIAIS.items():
            db.salvar(t, {"setor": setor})


def main():
    # Executável sem console (--noconsole): stdout/stderr são None
    if sys.stdout is None or sys.stderr is None:
        nulo = open(os.devnull, "w")
        sys.stdout = sys.stdout or nulo
        sys.stderr = sys.stderr or nulo
    url =f"http://127.0.0.1:{PORTA}/"
    if porta_em_uso(PORTA):  # já aberto: só abre o navegador
        webbrowser.open(url)
        return
    db.inicializar()
    primeira_execucao()
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    if "--dev" in sys.argv:
        app.run(host="127.0.0.1", port=PORTA, debug=True, use_reloader=False)
    else:
        from waitress import serve
        serve(app, host="127.0.0.1", port=PORTA, threads=4)


if __name__ == "__main__":
    main()
