from yahooquery import Ticker

def get_fundamentals(ticker: str) -> dict:
    try:
        # Limpiar sufijos como .US, .BA
        clean_ticker = ticker.replace(".US", "").replace(".BA", "")

        t = Ticker(clean_ticker)
        data = t.all_modules

        if isinstance(data, dict) and clean_ticker in data:
            stats = data[clean_ticker].get("defaultKeyStatistics", {})
            summary = data[clean_ticker].get("summaryDetail", {})
            financials = data[clean_ticker].get("financialData", {})

            # ROE directo o fallback a ROA
            roe = stats.get("returnOnEquity")
            if roe is None:
                roe = financials.get("returnOnAssets")

            # Otros ratios
            roa = financials.get("returnOnAssets")
            profit = financials.get("profitMargins")
            gross = financials.get("grossMargins")
            operating = financials.get("operatingMargins")
            ebitda = financials.get("ebitdaMargins")
            pe = summary.get("trailingPE")

            print(f"📉 {clean_ticker} → ROE={roe}, ROA={roa}, PE={pe}, Margen Neto={profit}, Bruto={gross}, Operativo={operating}, EBITDA={ebitda}")

            return {
                "ticker": ticker,
                "ROE": roe,
                "ROA": roa,
                "PE": pe,
                "profitMargins": profit,
                "grossMargins": gross,
                "operatingMargins": operating,
                "ebitdaMargins": ebitda
            }

        else:
            print(f"⚠️ No se encontraron módulos válidos para {clean_ticker}")
            return {"ticker": ticker, "ROE": None, "ROA": None, "PE": None,
                    "profitMargins": None, "grossMargins": None,
                    "operatingMargins": None, "ebitdaMargins": None}

    except Exception as e:
        print(f"❌ Error al obtener fundamentales de {ticker}: {e}")
        return {"ticker": ticker, "ROE": None, "ROA": None, "PE": None,
                "profitMargins": None, "grossMargins": None,
                "operatingMargins": None, "ebitdaMargins": None}
