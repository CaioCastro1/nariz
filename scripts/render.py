"""Injeta data/painel.json no template e grava painel/index.html."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tpl = (ROOT / "painel" / "template.html").read_text(encoding="utf-8")
data = (ROOT / "data" / "painel.json").read_text(encoding="utf-8").replace("</", "<\\/")
assert "/*__DATA__*/null" in tpl
(ROOT / "painel" / "index.html").write_text(tpl.replace("/*__DATA__*/null", data), encoding="utf-8")
print("painel/index.html", round(len(data) / 1e3), "KB de dados")
