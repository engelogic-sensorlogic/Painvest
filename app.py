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

import time

from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, url_for

import db
import scoring

VERSAO = "1.1.1"
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
    detalhe_sec = json.loads(r["sec_detalhe"]) if r.get("sec_detalhe") else None
    return render_template("editar.html", r=r, av=scoring.avaliar(r, c), cfg=c, sec=detalhe_sec,
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


def _erro(e):
    return f"{type(e).__name__}: {e}"[:300]


def _coletar(ticker):
    """Cotações e dividendos (Yahoo Finance)."""
    import market
    try:
        db.salvar(ticker, market.coletar(ticker, db.obter(ticker)))
        return True, None
    except Exception as e:  # sem internet, ticker inválido, limite do Yahoo etc.
        db.salvar(ticker, {"erro_coleta": _erro(e)})
        return False, _erro(e)


def _coletar_sec(ticker, c):
    """Fundamentos calculados a partir da SEC."""
    import sec
    try:
        db.salvar(ticker, sec.coletar(ticker, c["contato_sec"], db.DATA_DIR, c["ajuste_payout_ffo"]))
        return True, None
    except Exception as e:
        db.salvar(ticker, {"sec_erro": _erro(e)})
        return False, _erro(e)


# ---------- Atualização em segundo plano com progresso ----------
PROGRESSO = {"rodando": False}
PAUSA_YAHOO = 0.8  # segundos entre tickers
_trava = threading.Lock()


def _set(**kw):
    with _trava:
        PROGRESSO.update(kw)


def _tarefa_atualizacao(tickers):
    import market
    import sec
    c = cfg()
    usar_sec = bool((c.get("contato_sec") or "").strip())
    total = 1 + len(tickers) + ((1 + len(tickers)) if usar_sec else 0)
    _set(rodando=True, total=total, feito=0, ok=0, falhas=0, sec_ok=0, sec_falhas=0,
         etapa="Treasury 10 anos", ticker="", avisos=[], erros=[], usar_sec=usar_sec, concluido=False)
    avisos, erros = [], []
    try:
        try:
            c["treasury_10a"] = market.treasury_10a()
            db.gravar_config(c)
        except Exception:
            avisos.append("Treasury 10 anos não atualizado (mantido o valor da configuração).")
        _set(feito=1)

        for t in tickers:
            _set(etapa="Cotações e dividendos (Yahoo Finance)", ticker=t)
            ok, msg = _coletar(t)
            if not ok:
                erros.append({"ticker": t, "fonte": "Yahoo", "msg": msg})
            with _trava:
                PROGRESSO["ok" if ok else "falhas"] += 1
                PROGRESSO["feito"] += 1
                PROGRESSO["erros"] = list(erros)
            time.sleep(PAUSA_YAHOO)  # evita limitação de requisições do Yahoo

        if usar_sec:
            _set(etapa="Base de empresas da SEC", ticker="")
            try:
                sec.mapa_tickers(c["contato_sec"], db.DATA_DIR)
            except Exception as e:
                avisos.append(f"SEC indisponível: {_erro(e)}")
                usar_sec = False
            _set(feito=PROGRESSO["feito"] + 1)
            for t in tickers:
                _set(etapa="Fundamentos — FFO, payout, dívida (SEC)", ticker=t)
                if usar_sec:
                    ok, msg = _coletar_sec(t, c)
                    if not ok:
                        erros.append({"ticker": t, "fonte": "SEC", "msg": msg})
                    time.sleep(0.15)  # limite de requisições da SEC
                else:
                    ok = False
                with _trava:
                    PROGRESSO["sec_ok" if ok else "sec_falhas"] += 1
                    PROGRESSO["feito"] += 1
                    PROGRESSO["erros"] = list(erros)
        else:
            avisos.append("Coleta SEC desativada: informe seu e-mail de contato em Metodologia.")
    finally:
        _set(rodando=False, concluido=True, etapa="Concluído", ticker="", avisos=avisos, erros=erros)


@app.post("/atualizar")
def atualizar_todos():
    with _trava:
        if PROGRESSO.get("rodando"):
            return jsonify({"iniciado": False, "motivo": "Atualização já em andamento."})
        PROGRESSO.update(rodando=True, total=1, feito=0, etapa="Iniciando", concluido=False)
    tickers = [r["ticker"] for r in db.listar()]
    threading.Thread(target=_tarefa_atualizacao, args=(tickers,), daemon=True).start()
    return jsonify({"iniciado": True})


@app.get("/atualizar/status")
def atualizar_status():
    with _trava:
        return jsonify(dict(PROGRESSO))


@app.post("/atualizar/<ticker>")
def atualizar_um(ticker):
    ticker = ticker.upper()
    ok, _ = _coletar(ticker)
    c = cfg()
    msg = f"{ticker}: cotações {'ok' if ok else 'com falha'}"
    if (c.get("contato_sec") or "").strip():
        ok_sec, _ = _coletar_sec(ticker, c)
        msg += f" · SEC {'ok' if ok_sec else 'com falha'}"
        ok = ok and ok_sec
    flash(msg + ".", "ok" if ok else "erro")
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
            c["contato_sec"] = (f.get("contato_sec") or "").strip()
            c["ajuste_payout_ffo"] = _num(f.get("ajuste_payout_ffo") or "0")
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
