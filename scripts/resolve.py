"""Resolução de entidades: junta grafias diferentes da mesma organização.

Ordem de prioridade:
1. aliases.csv (curadoria manual): nome normalizado ou chave -> id canônico.
2. Automático: nome sem sufixo societário igual ao de uma entidade com CNPJ.
3. Senão, a própria chave.
Gera data/entidades.parquet (chave -> id, rótulo) e data/participacoes_resolvidas.parquet.
"""
import csv
import re
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SUFIXOS = r"\b(S A|SA|S\/A|LTDA|EIRELI|ME|EPP|CIA|COMPANHIA|HOLDING|PARTICIPACOES|DO BRASIL|BRASIL|GRUPO)\b"


def base_nome(n: str) -> str:
    n = re.sub(SUFIXOS, " ", n)
    return re.sub(r"\s+", " ", n).strip()


def load_aliases():
    path = ROOT / "curadoria" / "aliases.csv"
    m = {}
    if path.exists():
        for row in csv.DictReader(path.open(encoding="utf-8")):
            m[row["de"].strip()] = row["para"].strip()
    return m


def main():
    p = pl.read_parquet(DATA / "participacoes.parquet")
    nomes = (p.group_by("chave", "nome").len().sort("len", descending=True)
              .unique("chave", keep="first").select("chave", "nome"))
    cont = p.group_by("chave").agg(pl.col("id").n_unique().alias("n"))
    ent = nomes.join(cont, on="chave")
    ent = ent.with_columns(
        pl.col("chave").str.replace(r"^(CNPJ|NOME):", "").alias("valor"),
    )
    from extract import norm  # noqa: E402
    ent = ent.with_columns(pl.col("nome").map_elements(lambda s: base_nome(norm(s)), return_dtype=pl.String).alias("base"))

    # mapa automático base -> CNPJ mais frequente
    cnpj = ent.filter(pl.col("chave").str.starts_with("CNPJ:") & (pl.col("base") != ""))
    auto = (cnpj.sort("n", descending=True).unique("base", keep="first")
                .select("base", pl.col("chave").alias("auto_id")))
    ent = ent.join(auto, on="base", how="left")

    aliases = load_aliases()
    def resolve(chave, base, auto_id):
        for k in (chave, "NOME:" + base, base):
            if k in aliases:
                return aliases[k]
        if auto_id:
            return auto_id
        if chave.startswith("NOME:") and base:
            return "NOME:" + base
        return chave
    ent = ent.with_columns(
        pl.struct("chave", "base", "auto_id").map_elements(
            lambda s: resolve(s["chave"], s["base"], s["auto_id"]), return_dtype=pl.String).alias("id_ent")
    )
    # segunda passada: alias pode apontar para outro alias
    ent = ent.with_columns(pl.col("id_ent").map_elements(lambda x: aliases.get(x, x), return_dtype=pl.String))
    ent.select("chave", "nome", "n", "id_ent").write_parquet(DATA / "entidades.parquet")
    pr = p.join(ent.select("chave", "id_ent"), on="chave").unique(subset=["id", "id_ent"])
    pr.write_parquet(DATA / "participacoes_resolvidas.parquet")
    print("entidades antes", ent.height, "depois", ent["id_ent"].n_unique(), file=sys.stderr)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
