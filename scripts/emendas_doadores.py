"""Tipologia 9: emenda parlamentar paga a empresa cujo sócio doou à campanha do autor da emenda.

Pessoa jurídica não pode doar a campanha desde 2015; o elo é o sócio pessoa física.
Doar é legal e a coincidência pode ser local e inocente (o empresário da cidade
apoia o candidato da cidade). O resultado é um indício de proximidade que merece
revisão, nunca uma acusação.

Uso: uv run scripts/emendas_doadores.py            (baixa o que faltar e cruza)
     uv run scripts/emendas_doadores.py --baixar   (só baixa e reduz as bases)

Entradas (data/emendas/ e data/tse/ ficam fora do git):
- Portal da Transparência, EmendasParlamentares_PorFavorecido.csv (pagamentos por
  favorecido, com CNPJ). O download da CGU respondeu normalmente, sem verificação humana.
- TSE, prestação de contas de candidatos 2018 e 2022 (receitas) e consulta_cand.
  Os zips são lidos em streaming e apagados; fica só data/tse/receitas_parl_AAAA.parquet
  (deputado federal e senador) e data/tse/cand_parl.parquet.
- data/qsa/socios.parquet (CPF mascarado: nome normalizado + 6 dígitos do meio).
  A colisão por homônimo reaproveita servidor_socio.colisao.

Regras:
- Só emenda individual (a de bancada, de comissão e a de relator não têm um autor).
- Autor → candidato pelo nome normalizado (nome de urna ou nome civil), entre os
  candidatos a deputado federal e senador de 2018 e 2022. Eleitos têm preferência;
  nome que ainda é ambíguo fica de fora.
- Favorecido PJ pela raiz do CNPJ (8 dígitos). Pagamentos a partir de jan/2019.
- Doação anterior ao pagamento: eleição de 2018 vale para pagamentos até out/2022
  e a de 2022 para os de nov/2022 em diante (valem as duas depois disso).
- Sócio na data: entrada na sociedade anterior ou igual ao mês do pagamento.
- Doação do próprio autor a si mesmo fica de fora (autofinanciamento).
- Caso fraco: o sócio não doou ao autor, mas doou a outro candidato do mesmo partido
  (proxy de "doação ao partido", já que o TSE não abre a conta do diretório aqui).
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from qsa import norm_expr  # noqa: E402
from servidor_socio import colisao  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
EME = DATA / "emendas"
TSE = DATA / "tse"
ANOS = (2018, 2022)
BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele/"
URL_EME = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
CARGOS = ["Deputado Federal", "Senador"]
RCOLS = ["SQ_CANDIDATO", "SG_UF", "DS_CARGO", "NR_CPF_CANDIDATO", "SG_PARTIDO", "DS_ORIGEM_RECEITA",
         "NR_CPF_CNPJ_DOADOR", "NM_DOADOR", "NM_DOADOR_RFB", "VR_RECEITA"]
CCOLS = ["SG_UF", "DS_CARGO", "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "NR_CPF_CANDIDATO",
         "SG_PARTIDO", "DS_SIT_TOT_TURNO"]


def baixa(url: str, dest: Path):
    import subprocess
    subprocess.run(["curl", "-sL", "--fail", "-m", "900", "-A", "Mozilla/5.0", "-o", str(dest), url], check=True)
    if dest.read_bytes()[:2] != b"PK":
        dest.unlink()
        raise SystemExit(f"{url}: resposta não é zip (verificação humana?); baixe pelo navegador e salve em {dest}")


def baixar():
    EME.mkdir(exist_ok=True)
    TSE.mkdir(exist_ok=True)
    f = EME / "EmendasParlamentares_PorFavorecido.csv"
    if not f.exists():
        z = EME / "emendas.zip"
        baixa(URL_EME, z)
        zipfile.ZipFile(z).extractall(EME)
        z.unlink()
    cands = []
    for a in ANOS:
        out = TSE / f"receitas_parl_{a}.parquet"
        zc = TSE / f"cand_{a}.zip"
        if not zc.exists() and not (TSE / "cand_parl.parquet").exists():
            baixa(f"{BASE}consulta_cand/consulta_cand_{a}.zip", zc)
        if not out.exists():
            zr = TSE / f"rc_{a}.zip"
            if not zr.exists():
                baixa(f"{BASE}prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{a}.zip", zr)
            z = zipfile.ZipFile(zr)
            partes = []
            for n in z.namelist():
                if n.startswith(f"receitas_candidatos_{a}_") and not n.endswith("BRASIL.csv"):
                    d = pl.read_csv(z.read(n), separator=";", encoding="latin1", infer_schema=False, columns=RCOLS)
                    partes.append(d.filter(pl.col("DS_CARGO").is_in(CARGOS)))
            d = pl.concat(partes).with_columns(pl.lit(a).alias("ano"))
            d.write_parquet(out, compression="zstd")
            print(a, "receitas de deputado/senador:", d.height, file=sys.stderr)
            z.close()
            zr.unlink()
    if not (TSE / "cand_parl.parquet").exists():
        for a in ANOS:
            z = zipfile.ZipFile(TSE / f"cand_{a}.zip")
            for n in z.namelist():
                if n.startswith(f"consulta_cand_{a}_") and n.endswith(".csv") and not n.endswith("BRASIL.csv"):
                    d = pl.read_csv(z.read(n), separator=";", encoding="latin1", infer_schema=False, columns=CCOLS)
                    cands.append(d.filter(pl.col("DS_CARGO").str.to_titlecase().is_in(CARGOS)).with_columns(pl.lit(a).alias("ano")))
            z.close()
            (TSE / f"cand_{a}.zip").unlink()
        pl.concat(cands).write_parquet(TSE / "cand_parl.parquet", compression="zstd")


if __name__ == "__main__" and "--baixar" in sys.argv:
    baixar()
    sys.exit()


def candidatos() -> pl.DataFrame:
    """Uma linha por CPF de candidato a deputado federal ou senador (2018 e 2022)."""
    c = pl.read_parquet(TSE / "cand_parl.parquet").filter(pl.col("NR_CPF_CANDIDATO").str.len_chars() == 11)
    c = c.with_columns(pl.col("DS_SIT_TOT_TURNO").str.to_uppercase().str.starts_with("ELEITO").alias("eleito"))
    nomes = pl.concat([
        c.select("NR_CPF_CANDIDATO", "SG_UF", "SG_PARTIDO", "ano", "eleito", norm_expr("NM_URNA_CANDIDATO").alias("nome")),
        c.select("NR_CPF_CANDIDATO", "SG_UF", "SG_PARTIDO", "ano", "eleito", norm_expr("NM_CANDIDATO").alias("nome")),
    ]).unique()
    return nomes


def autores(c: pl.DataFrame, nomes_autor: list) -> pl.DataFrame:
    """Nome do autor → CPF. Entre os eleitos se houver; ambíguo (2+ CPFs) fica de fora."""
    por_nome = c.group_by("nome").agg(
        pl.col("NR_CPF_CANDIDATO").filter(pl.col("eleito")).unique().alias("cpf_eleito"),
        pl.col("NR_CPF_CANDIDATO").unique().alias("cpf_todos"),
        pl.col("SG_UF").sort_by("ano", descending=True).first().alias("uf"),
        pl.col("SG_PARTIDO").sort_by("ano", descending=True).first().alias("partido"),
    ).with_columns(
        pl.when(pl.col("cpf_eleito").list.len() > 0).then(pl.col("cpf_eleito")).otherwise(pl.col("cpf_todos")).alias("cpfs"))
    a = pl.DataFrame({"autor": nomes_autor}).with_columns(norm_expr("autor").alias("nome")).join(por_nome, on="nome", how="left")
    a = a.with_columns(pl.col("cpfs").list.len().fill_null(0).alias("n_cpf"))
    return a.filter(pl.col("n_cpf") == 1).with_columns(pl.col("cpfs").list.first().alias("cpf_autor")).select(
        "autor", "cpf_autor", "uf", "partido"), a


def pagamentos() -> pl.DataFrame:
    d = pl.read_csv(EME / "EmendasParlamentares_PorFavorecido.csv", separator=";", encoding="latin1", infer_schema=False)
    d = d.filter(pl.col("Tipo de Emenda").str.starts_with("Emenda Individual") & (pl.col("Tipo Favorecido") == "Pessoa Jurídica")
                 & (pl.col("Código do Favorecido").str.len_chars() == 14))
    return d.select(
        pl.col("Nome do Autor da Emenda").alias("autor"), pl.col("Código da Emenda").alias("emenda"),
        pl.col("Código do Favorecido").str.slice(0, 8).alias("cnpj_basico"),
        pl.col("Natureza Jurídica").alias("natureza"), pl.col("UF Favorecido").alias("uf_fav"),
        pl.col("Ano/Mês").cast(pl.Int32).alias("aaaamm"),
        pl.col("Valor Recebido").str.replace_all(r"\.", "").str.replace(",", ".").cast(pl.Float64).alias("valor"),
    ).filter(pl.col("aaaamm") >= 201901)


def doacoes() -> pl.DataFrame:
    """Doações diretas de pessoa física a candidatos (CPF de 11 dígitos), uma chave por nome."""
    d = pl.concat([pl.read_parquet(TSE / f"receitas_parl_{a}.parquet") for a in ANOS])
    d = d.filter(pl.col("NR_CPF_CNPJ_DOADOR").str.len_chars() == 11).with_columns(
        pl.col("NR_CPF_CNPJ_DOADOR").str.slice(3, 6).alias("cpf6"),
        pl.col("VR_RECEITA").str.replace(",", ".").cast(pl.Float64).alias("valor_doado"),
        pl.col("ano").alias("ano_eleicao"))
    base = d.select("NR_CPF_CANDIDATO", "SG_UF", "SG_PARTIDO", "ano_eleicao", "cpf6", "valor_doado",
                    pl.col("NR_CPF_CNPJ_DOADOR").alias("cpf_doador"))
    d1 = base.with_columns(norm_expr_name(d, "NM_DOADOR_RFB").alias("nome_norm"))
    d2 = base.with_columns(norm_expr_name(d, "NM_DOADOR").alias("nome_norm"))
    return pl.concat([d1, d2]).filter(pl.col("nome_norm").is_not_null() & (pl.col("nome_norm") != "")).unique()


def norm_expr_name(d, col):
    return d.select(norm_expr(col)).to_series()


def main():
    baixar()
    c = candidatos()
    pag = pagamentos()
    aut, aut_todos = autores(c, pag["autor"].unique().to_list())
    n_aut = pag["autor"].n_unique()
    pag = pag.join(aut, on="autor")  # só autores identificados
    stats = {"pagamentos_individual_pj_2019+": None, "autores_total": n_aut, "autores_identificados": aut.height,
             "autores_ambiguos": aut_todos.filter(pl.col("n_cpf") > 1).height,
             "autores_sem_candidatura": aut_todos.filter(pl.col("n_cpf") == 0).height}

    # sócios dos favorecidos (só as raízes que aparecem)
    raizes = pag["cnpj_basico"].unique()
    soc = pl.scan_parquet(DATA / "qsa/socios.parquet").filter(pl.col("cnpj_basico").is_in(raizes.implode())).select(
        "cnpj_basico", "nome_norm", "cpf6", "data_entrada", "cod_qualificacao").unique().collect()
    soc = soc.filter(pl.col("cpf6").is_not_null() & (pl.col("cpf6") != "000000"))
    pag = pag.with_columns(((pl.col("aaaamm") // 100) * 12 + pl.col("aaaamm") % 100).alias("mes_idx"))
    stats["pagamentos_individual_pj_2019+"] = {"linhas": pag.height, "valor": pag["valor"].sum(),
                                               "favorecidos": pag["cnpj_basico"].n_unique(),
                                               "autores": pag["cpf_autor"].n_unique()}

    don = doacoes()
    don_pf = don.select("nome_norm", "cpf6").unique()
    # linha de base 1: sócios de favorecidos (pessoas) que doaram a QUALQUER parlamentar
    pessoas_soc = soc.select("nome_norm", "cpf6").unique()
    doam_qualquer = pessoas_soc.join(don_pf, on=["nome_norm", "cpf6"])
    stats["base"] = {"pessoas_socias": pessoas_soc.height, "pessoas_socias_que_doaram_a_algum_parlamentar": doam_qualquer.height,
                     "pct": doam_qualquer.height / pessoas_soc.height}

    # pares (autor, empresa) ligados por sócio doador
    sd = soc.join(don, on=["nome_norm", "cpf6"])          # sócio x doação a candidato
    sd = sd.filter(pl.col("cpf_doador").is_not_null())
    ligados = pag.join(sd, on="cnpj_basico")              # pagamento x (sócio doador)
    ligados = ligados.with_columns(
        (pl.col("data_entrada").dt.year() * 12 + pl.col("data_entrada").dt.month()).alias("ent_idx"),
        pl.when(pl.col("aaaamm") >= 202211).then(2).otherwise(1).alias("n_eleicoes_validas"))
    ligados = ligados.filter(
        ((pl.col("ano_eleicao") == 2018) | (pl.col("aaaamm") >= 202211)) &
        (pl.col("cpf_doador") != pl.col("cpf_autor")))
    sem_data = ligados
    ligados = ligados.filter(pl.col("data_entrada").is_null() | (pl.col("ent_idx") <= pl.col("mes_idx")))

    forte = ligados.filter(pl.col("NR_CPF_CANDIDATO") == pl.col("cpf_autor"))
    fraco = ligados.filter((pl.col("NR_CPF_CANDIDATO") != pl.col("cpf_autor")) & (pl.col("SG_PARTIDO") == pl.col("partido"))
                           & (pl.col("SG_UF") == pl.col("uf")))
    fraco_so = fraco.join(forte.select("emenda", "cnpj_basico").unique(), on=["emenda", "cnpj_basico"], how="anti")

    def resumo(g: pl.DataFrame) -> dict:
        pares = g.select("cpf_autor", "cnpj_basico").unique()
        pg = g.select("emenda", "cnpj_basico", "aaaamm", "valor").unique()
        return {"pares_autor_empresa": pares.height, "autores": g["cpf_autor"].n_unique(), "empresas": g["cnpj_basico"].n_unique(),
                "pessoas_socias_doadoras": g.select("nome_norm", "cpf6").unique().height,
                "pagamentos": pg.height, "valor_pago": round(pg["valor"].sum(), 2),
                "valor_doado_mediana": round(g.group_by("cpf_autor", "cnpj_basico").agg(pl.col("valor_doado").sum())["valor_doado"].median() or 0, 2),
                "valor_doado_p90": round(g.group_by("cpf_autor", "cnpj_basico").agg(pl.col("valor_doado").sum())["valor_doado"].quantile(0.9) or 0, 2)}

    stats["forte"] = resumo(forte)
    stats["forte_sem_filtro_de_data_de_entrada"] = resumo(sem_data.filter(pl.col("NR_CPF_CANDIDATO") == pl.col("cpf_autor")))
    stats["fraco_mesmo_partido_e_uf"] = resumo(fraco_so)
    # recorte: favorecido é sociedade empresária / empresário individual
    emp = forte.filter(pl.col("natureza").str.contains("Empres"))
    stats["forte_so_empresas"] = resumo(emp) if emp.height else None
    stats["forte_por_natureza"] = {r["natureza"]: r["n"] for r in forte.select("cpf_autor", "cnpj_basico", "natureza").unique()
                                   .group_by("natureza").agg(pl.len().alias("n")).sort("n", descending=True).head(6).to_dicts()}
    # concentração: autores com mais pares
    por_autor = forte.select("cpf_autor", "cnpj_basico").unique().group_by("cpf_autor").agg(pl.len().alias("n")).sort("n", descending=True)
    stats["forte_pares_por_autor"] = {"mediana": por_autor["n"].median(), "max": por_autor["n"].max(),
                                      "top10_autores_pct_dos_pares": por_autor.head(10)["n"].sum() / por_autor["n"].sum()}
    # sócio doa ao autor: quantos pares de (autor, empresa) possíveis existiam
    pares_total = pag.select("cpf_autor", "cnpj_basico").unique().height
    stats["pares_autor_empresa_total"] = pares_total
    stats["forte_pct_dos_pares"] = stats["forte"]["pares_autor_empresa"] / pares_total

    # linha de base 2: embaralha os autores entre pagamentos da mesma UF do favorecido
    # (mantém empresa, valor, mês e a UF; troca quem emendou) e refaz o casamento
    soc_doa = sd.select("cnpj_basico", "NR_CPF_CANDIDATO", "ano_eleicao", "cpf_doador", "data_entrada").unique()
    pagu = pag.select("cpf_autor", "cnpj_basico", "uf", "aaaamm", "mes_idx").unique()
    autores_uf = pagu.select("cpf_autor", "uf").unique()
    rs = []
    for i in range(20):
        emb = pagu.with_columns(pl.col("cpf_autor").shuffle(seed=i).over("uf"))
        h = emb.join(soc_doa, on="cnpj_basico").filter(
            (pl.col("NR_CPF_CANDIDATO") == pl.col("cpf_autor")) & (pl.col("cpf_doador") != pl.col("cpf_autor")) &
            ((pl.col("ano_eleicao") == 2018) | (pl.col("aaaamm") >= 202211)) &
            (pl.col("data_entrada").is_null() | ((pl.col("data_entrada").dt.year() * 12 + pl.col("data_entrada").dt.month()) <= pl.col("mes_idx"))))
        rs.append(h.select("cpf_autor", "cnpj_basico").unique().height)
    real = forte.select("cpf_autor", "cnpj_basico").unique().height
    stats["embaralhando_autores_na_mesma_uf"] = {"real": real, "rodadas": rs, "media": sum(rs) / len(rs),
                                                 "razao_real_sobre_aleatorio": real / (sum(rs) / len(rs)) if sum(rs) else None}

    # falso positivo por homônimo: reaproveita servidor_socio.colisao no nível da pessoa
    pessoas_doadoras = don.select("nome_norm", "cpf6").unique().join(
        soc.select("nome_norm").unique(), on="nome_norm")  # só nomes que existem nos favorecidos (economiza)
    stats["colisao_pessoa"] = colisao(pessoas_doadoras, soc.select("nome_norm", "cpf6").unique(), rodadas=20)
    # e no nível do achado: sorteia de novo o CPF6 dos doadores, na mesma região fiscal, e conta os pares
    dd = sd.select("nome_norm", "cpf6").unique().with_columns(pl.col("cpf6").str.slice(5, 1).alias("reg"))
    pagar = pag.select("emenda", "cpf_autor", "cnpj_basico", "aaaamm", "mes_idx").unique()
    don_full = don.join(soc.select("nome_norm").unique(), on="nome_norm")
    fp = []
    for i in range(20):
        emb = don_full.with_columns(pl.col("cpf6").str.slice(5, 1).alias("reg")).with_columns(
            pl.col("cpf6").shuffle(seed=i).over("reg"))
        h = soc.join(emb, on=["nome_norm", "cpf6"]).join(pagar, on="cnpj_basico").filter(
            (pl.col("NR_CPF_CANDIDATO") == pl.col("cpf_autor")) & (pl.col("cpf_doador") != pl.col("cpf_autor")) &
            ((pl.col("ano_eleicao") == 2018) | (pl.col("aaaamm") >= 202211)) &
            (pl.col("data_entrada").is_null() | ((pl.col("data_entrada").dt.year() * 12 + pl.col("data_entrada").dt.month()) <= pl.col("mes_idx"))))
        fp.append(h.select("cpf_autor", "cnpj_basico").unique().height)
    stats["falso_positivo_pares"] = {"rodadas": fp, "media": sum(fp) / len(fp), "taxa": sum(fp) / len(fp) / real if real else None}

    # saída com dados pessoais só no disco local
    forte.select("emenda", "cpf_autor", "cnpj_basico", "natureza", "aaaamm", "valor", "nome_norm", "cpf6", "ano_eleicao",
                 "valor_doado").write_parquet(DATA / "emendas_doadores.parquet", compression="zstd")
    (DATA / "emendas_doadores_stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False, default=float))
    print(json.dumps(stats, indent=1, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
