"""Lê o zip mensal do e-Agendas (CGU) e gera duas tabelas em data/:

- reunioes.parquet: uma linha por (reunião, autoridade anfitriã)
- participacoes.parquet: uma linha por (reunião, entidade privada representada)
- pessoas_privadas.parquet: uma linha por (reunião, pessoa privada), com CPF parcial

Regras:
- Só "Reunião" e "Audiência". Eventos e audiências públicas ficam fora: são
  abertos e não indicam acesso privilegiado.
- Reuniões com "CANCELAD" no assunto são descartadas.
- "Interesse Próprio" (pessoa física sem entidade) não entra no ranking.
- Entidades com CNPJ são agrupadas pela raiz (8 primeiros dígitos), que junta
  matriz e filiais. Sem CNPJ, a chave é o nome normalizado.
"""
import io
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import polars as pl

DATA = Path(__file__).resolve().parent.parent / "data"
TIPOS = {"Reunião", "Audiência"}

RE_CNPJ = re.compile(r"\(CNPJ:\s*([\d./-]+)\)")
RE_DOC = re.compile(r"\((CPF|CNPJ|Passaporte)[^)]*\)")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", s).upper()
    return re.sub(r"\s+", " ", s).strip()


RE_CPF = re.compile(r"\(CPF:\s*\*{3}\.(\d{3})\.(\d{3})-\*{2}\)")


def split_participante(p: str):
    """Separa um participante em (parte da pessoa, entidade bruta)."""
    if "representando" in p:
        pessoa, ent = p.rsplit("representando", 1)
        return pessoa.strip(), ent.strip()
    # Formato sem "representando" (estrangeiros): "Nome (Passaporte) / Firma - cargo / Entidade"
    if " / " in p:
        pessoa, ent = p.rsplit(" / ", 1)
        return pessoa.strip(), ent.strip()
    return p, ""


def entidade(ent: str):
    """(nome, cnpj com 14 dígitos ou "") da entidade representada."""
    m = RE_CNPJ.search(ent)
    cnpj = re.sub(r"\D", "", m.group(1)) if m else ""
    return RE_DOC.sub("", ent).strip(" -–"), cnpj if len(cnpj) == 14 else ""


def participantes_privados(participantes: str):
    if "Agentes privados participantes:" not in participantes:
        return []
    bloco = participantes.split("Agentes privados participantes:", 1)[1]
    return [p.strip() for p in bloco.split(" | ") if p.strip()]


def parse_privados(participantes: str):
    """Devolve [(chave, nome, cnpj_raiz)] das entidades privadas da reunião."""
    out = {}
    for p in participantes_privados(participantes):
        nome, cnpj = entidade(split_participante(p)[1])
        if not nome or norm(nome) in {"INTERESSE PROPRIO", "ND"}:
            continue
        chave = "CNPJ:" + cnpj[:8] if cnpj else "NOME:" + norm(nome)
        out[chave] = (chave, nome, cnpj[:8])
    return list(out.values())


def parse_pessoas(participantes: str):
    """Devolve [(pessoa, cpf6, cargo, entidade, cnpj)] por participante privado.

    cpf6 são os 6 dígitos visíveis do CPF mascarado (***.123.456-** -> "123456");
    vazio quando não há CPF ou quando é o marcador ***.000.000-**.
    """
    out = {}
    for p in participantes_privados(participantes):
        pessoa, ent = split_participante(p)
        m = RE_CPF.search(pessoa)
        cpf6 = m.group(1) + m.group(2) if m else ""
        if cpf6 == "000000":
            cpf6 = ""
        if m:
            nome, cargo = pessoa[:m.start()], pessoa[m.end():]
        else:
            pessoa = RE_DOC.sub("", pessoa)
            nome, cargo = (pessoa.split(" / ", 1) + [""])[:2] if " / " in pessoa else (pessoa.split(" - ", 1) + [""])[:2]
        nome = nome.strip(" -–/")
        cargo = cargo.strip(" -–/")
        ent_nome, cnpj = entidade(ent)
        if nome:
            out[(norm(nome), cpf6, norm(ent_nome))] = (nome, cpf6, cargo, ent_nome, cnpj)
    return list(out.values())


def main():
    z = zipfile.ZipFile(DATA / "dados_e-agendas.zip")
    frames = []
    for name in sorted(z.namelist()):
        df = pl.read_csv(io.BytesIO(z.read(name)), infer_schema=False)
        df = df.with_columns(pl.lit(name.removesuffix(".csv")).alias("mes"))
        frames.append(df)
        print(name, df.height, file=sys.stderr)
    raw = pl.concat(frames, how="diagonal_relaxed")
    print("linhas brutas", raw.height, file=sys.stderr)

    base = raw.filter(
        pl.col("Tipo de registro").is_in(TIPOS)
        & ~pl.col("Assunto do Compromisso").fill_null("").str.to_uppercase().str.contains("CANCELAD")
    ).select(
        pl.col("ID do registro").alias("id"),
        pl.col("mes"),
        pl.col("Data de início").str.strptime(pl.Date, "%d-%m-%Y", strict=False).alias("data"),
        pl.col("Tipo de registro").alias("tipo"),
        pl.col("Nome").alias("autoridade"),
        pl.col("Cargo/Função").alias("cargo"),
        pl.col("Órgão/Entidade").alias("orgao"),
        pl.col("Assunto do Compromisso").alias("assunto"),
        pl.col("Participantes").fill_null("").alias("participantes"),
    ).unique(subset=["id", "autoridade"])

    base.drop("participantes").write_parquet(DATA / "reunioes.parquet")

    reun = base.unique(subset=["id"]).select("id", "participantes")
    rows = []
    for rid, part in reun.iter_rows():
        for chave, nome, cnpj in parse_privados(part):
            rows.append((rid, chave, nome, cnpj))
    part = pl.DataFrame(rows, schema=["id", "chave", "nome", "cnpj_raiz"], orient="row")
    part.write_parquet(DATA / "participacoes.parquet")

    # Uma linha por (reunião, pessoa privada), para cruzar com bases de pessoas.
    rows = []
    for rid, part_txt in reun.iter_rows():
        for r in parse_pessoas(part_txt):
            rows.append((rid, *r))
    pes = pl.DataFrame(rows, schema=["id", "pessoa", "cpf6", "cargo_declarado", "entidade", "cnpj"], orient="row")
    anf = base.group_by("id").agg(
        pl.col("data").min(),
        pl.col("orgao").mode().first().alias("orgao"),
        pl.col("orgao").unique().sort().str.join(" ; ").alias("orgaos"),
    )
    pes = pes.join(anf, on="id", how="left").with_columns(
        pl.col("pessoa").map_elements(norm, return_dtype=pl.String).alias("pessoa_norm"))
    pes.write_parquet(DATA / "pessoas_privadas.parquet")
    print("pessoas privadas", pes.height, "com cpf6", (pes["cpf6"] != "").sum(), file=sys.stderr)
    print("reuniões", base["id"].n_unique(), "participações privadas", part.height,
          "entidades", part["chave"].n_unique(), file=sys.stderr)


if __name__ == "__main__":
    main()
