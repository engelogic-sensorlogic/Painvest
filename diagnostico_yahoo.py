"""Diagnóstico rápido da conexão com o Yahoo Finance.

Uso:  .venv\\Scripts\\python.exe diagnostico_yahoo.py O ADC PSA
"""
import sys
import time

import yfinance as yf

print(f"yfinance {yf.__version__}")
for ticker in (sys.argv[1:] or ["O"]):
    t = yf.Ticker(ticker)
    for nome, chamada in [
        ("history(max)", lambda: t.history(period="max", auto_adjust=False, actions=True)),
        ("history(1y)", lambda: t.history(period="1y")),
        ("dividends", lambda: t.dividends),
        ("fast_info", lambda: t.fast_info["last_price"]),
    ]:
        try:
            r = chamada()
            tam = len(r) if hasattr(r, "__len__") else r
            print(f"  {ticker:6} {nome:14} OK   -> {tam}")
        except Exception as e:
            print(f"  {ticker:6} {nome:14} ERRO -> {type(e).__name__}: {str(e)[:120]}")
        time.sleep(1)
