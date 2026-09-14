import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader


def parse_money(text):
    clean = text.strip().replace("$", "").replace(" ", "")
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    return float(clean)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: leer_total_pdf.py archivo.pdf")

    path = Path(sys.argv[1])
    result = {
        "ok": False,
        "path": str(path),
        "total": None,
        "raw": "",
        "error": "",
    }

    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        result["raw"] = text[-4000:]

        patterns = [
            r"(?:Importe\s+Total|TOTAL|Total)\s*[:$]?\s*\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})",
        ]

        matches = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                try:
                    matches.append((match.group(0), parse_money(match.group(1))))
                except Exception:
                    pass

        if matches:
            # AFIP-style invoices can contain subtotal, IVA and total. The largest
            # monetary value is usually the final total; Access IMPORTE includes IVA.
            best = max(matches, key=lambda item: item[1])
            result["ok"] = True
            result["total"] = best[1]
            result["matched"] = best[0]
        else:
            fallback = []
            for match in re.finditer(r"\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]{4,},[0-9]{2})\b", text):
                try:
                    value = parse_money(match.group(1))
                    if 0 < value < 100_000_000:
                        fallback.append((match.group(1), value))
                except Exception:
                    pass
            if fallback:
                best = max(fallback, key=lambda item: item[1])
                result["ok"] = True
                result["total"] = best[1]
                result["matched"] = f"fallback:{best[0]}"
            else:
                result["error"] = "No se encontro un importe total en el texto del PDF."
    except Exception as exc:
        result["error"] = str(exc)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
