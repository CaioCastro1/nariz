"""Tipologia 6: indícios de empresa de fachada em contratos públicos.

Uso: uv run scripts/fachada.py
Pré-requisito: data/qsa/estabelecimentos.parquet (uv run scripts/qsa.py --estab).
Saídas: data/fachada_stats.json (agregados) e data/fachada_casos.parquet (contratos com
pelo menos um indicador, para revisão humana; fica fora do git). Método: docs/metodo/6_fachada.md.

Contratos: sancoes.contratos() (SIASG + PNCP). Cadastro: data/qsa (Receita, mês em meta.json).

Indicadores, cada um contado à parte e depois somados num grau (ver docs/metodo/6_fachada.md):
  a  matriz aberta menos de 6 meses antes da assinatura
  b  valor do contrato > 100x o capital social (e >= R$ 50 mil)
  c  CNAE principal sem relação evidente com o objeto (regra de palavras-chave, só amostra)
  d  situação cadastral suspensa/inapta/baixada na assinatura ou até 180 dias depois
  e  fornecedoras diferentes do mesmo órgão com o mesmo endereço ou um sócio em comum (tipologia 7)

Limite central: a Receita só publica o estado ATUAL (mês de meta.json). Capital, CNAE e situação
podem ter mudado desde a assinatura.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from sancoes import contratos  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
QSA = DATA / "qsa"
JANELA = (date(2023, 1, 1), date(2025, 1, 31))  # onde SIASG e PNCP cobrem todos os meses (docs/metodo/1_sancoes.md)
VALOR_MIN_B = 50_000
RAZAO_B = 100
VALOR_MAX = 1e9
GRUPO_MAX = 8  # acima disso o "mesmo endereço"/"mesmo sócio" é prédio, contador ou holding grande

# categoria de objeto -> (regex em minúsculas, divisões CNAE 2.0 plausíveis). Regra simples: só vale
# se UMA categoria casa com o objeto; o resultado é amostra para revisão manual, não prova.
CATEGORIAS = {
    "obras": (r"\b(obras?|constru[cç][aã]o|reforma|pavimenta|edifica|engenharia|terraplan|drenagem|saneamento)",
              {41, 42, 43, 71, 81, 68, 23, 24, 25, 16, 46, 47, 33, 77, 39, 38, 37, 35, 74, 80, 70}),
    "ti": (r"(software|sistemas? de informa|tecnologia da informa|inform[aá]tica|computador|licen[cç]as? de uso|hospedagem)",
           {26, 46, 47, 58, 59, 61, 62, 63, 33, 77, 95, 73, 82, 85, 74, 70, 18}),
    "saude": (r"(medicamento|material m[eé]dico|hospitalar|insumos? (m[eé]dic|hospital)|farm[aá]c|odontol|laborat)",
              {21, 32, 46, 47, 86, 87, 75, 33, 26, 72, 20, 22, 17, 28}),
    "alimentos": (r"(g[eê]neros aliment|merenda|alimenta[cç][aã]o|refei[cç]|hortifruti|marmit)",
                  {1, 3, 10, 11, 15, 46, 47, 56, 82, 49, 52}),
    "apoio": (r"(limpeza|conserva[cç][aã]o|vigil[aâ]ncia|portaria|m[aã]o[ -]de[ -]obra|terceiriza|jardinagem|copeiragem)",
              {80, 81, 78, 82, 43, 74, 70, 85, 49, 56, 77, 84, 46, 47, 41, 42, 71, 20, 22, 17, 25, 31, 1, 3, 36, 37, 38, 39}),
    "combustivel": (r"(combust[ií]vel|gasolina|diesel|etanol)", {19, 46, 47, 35, 52, 49, 4}),
    "veiculos": (r"(ve[ií]culo|loca[cç][aã]o de (ve|autom|[oô]nibus)|pneu)",
                 {29, 30, 45, 46, 47, 49, 50, 51, 52, 77, 22, 95, 53, 81, 85}),
}
PUBLICAS = ["2011", "2038"]  # empresa pública e sociedade de economia mista (estatais)


def segmento(nj):
    """Agrupa a natureza jurídica (códigos da Receita) nas categorias que importam para a leitura."""
    return (pl.when(nj == "2135").then(pl.lit("empresário individual / MEI"))
              .when(nj.is_in(["2062", "2305", "2240"])).then(pl.lit("Ltda / EIRELI / SLU"))
              .when(nj.is_in(["2054", "2046"])).then(pl.lit("sociedade anônima"))
              .when(nj == "2143").then(pl.lit("cooperativa"))
              .otherwise(pl.lit("outras")))


def carrega():
    c = contratos().filter(pl.col("valor") > 0)
    emp = pl.read_parquet(QSA / "empresas.parquet").unique("cnpj_basico")
    est = pl.read_parquet(QSA / "estabelecimentos.parquet")
    n0 = c.height
    c = c.join(emp, left_on="raiz", right_on="cnpj_basico", how="left").join(est, on="cnpj", how="left")
    cob = {"contratos_pj": n0, "sem_empresas": c.filter(pl.col("natureza_juridica").is_null()).height,
           "sem_estabelecimento": c.filter(pl.col("situacao").is_null()).height}
    return c, cob


def exclusoes(c):
    """Fora do universo: administração pública (1xxx), estatais, sem fins lucrativos (3xxx),
    pessoa física/produtor rural (4xxx), organização internacional (5xxx) e CNPJ sem cadastro."""
    nj = pl.col("natureza_juridica")
    motivo = (pl.when(nj.is_null() | pl.col("situacao").is_null()).then(pl.lit("sem cadastro na Receita (CNPJ não achado)"))
                .when(nj.str.starts_with("1")).then(pl.lit("administração pública"))
                .when(nj.is_in(PUBLICAS)).then(pl.lit("empresa pública / economia mista"))
                .when(nj.str.starts_with("3")).then(pl.lit("sem fins lucrativos (fundação, associação, religiosa)"))
                .when(nj.str.starts_with("4") | nj.str.starts_with("5")).then(pl.lit("pessoa física, produtor rural ou internacional"))
                .otherwise(None))
    c = c.with_columns(motivo.alias("excl"))
    ex = c.filter(pl.col("excl").is_not_null()).group_by("excl").agg(
        pl.len().alias("contratos"), pl.col("cnpj").n_unique().alias("empresas")).sort("contratos", descending=True)
    return c.filter(pl.col("excl").is_null()).drop("excl"), ex


def indicadores_abcd(c):
    dias = (pl.col("assinatura") - pl.col("data_inicio")).dt.total_days()
    obj = pl.col("objeto").fill_null("").str.to_lowercase()
    c = c.with_columns(
        dias.alias("dias_abertura"),
        pl.col("cnae_principal").str.slice(0, 2).cast(pl.Int32, strict=False).alias("cnae_div"),
        segmento(pl.col("natureza_juridica")).alias("segmento"),
        *[obj.str.contains(rx).alias(f"cat_{n}") for n, (rx, _) in CATEGORIAS.items()])
    ncat = sum(pl.col(f"cat_{n}").cast(pl.Int32) for n in CATEGORIAS)
    cat = pl.lit(None, pl.String)
    for n in CATEGORIAS:
        cat = pl.when(pl.col(f"cat_{n}")).then(pl.lit(n)).otherwise(cat)
    c = c.with_columns(pl.when(ncat == 1).then(cat).alias("categoria_objeto"))
    ok = pl.lit(None, pl.Boolean)
    for n, (_, divs) in CATEGORIAS.items():
        ok = pl.when(pl.col("categoria_objeto") == n).then(pl.col("cnae_div").is_in(sorted(divs))).otherwise(ok)
    c = c.with_columns(ok.alias("_cnae_ok"))
    matriz = pl.col("matriz_filial") == "1"
    # situação só conta se a data é posterior à abertura (descarta a "data" de uma ativa e registros truncados)
    irreg = (pl.col("situacao").is_in(["03", "04", "08"]) & pl.col("data_situacao").is_not_null()
             & (pl.col("data_situacao") > pl.col("data_inicio").fill_null(date(1900, 1, 1))))
    return c.with_columns(
        (matriz & dias.is_between(0, 182)).alias("a"),
        (matriz & dias.is_between(0, 89)).alias("a_90d"),
        (dias < 0).alias("inicio_posterior"),
        ((pl.col("capital_social") > 0) & (pl.col("valor") >= VALOR_MIN_B)
         & (pl.col("valor") > RAZAO_B * pl.col("capital_social"))).alias("b"),
        ((pl.col("capital_social") > 0) & (pl.col("valor") >= VALOR_MIN_B)
         & (pl.col("valor") > 1000 * pl.col("capital_social"))).alias("b_1000x"),
        ((pl.col("capital_social") == 0) & (pl.col("valor") >= VALOR_MIN_B)).alias("capital_zero"),
        (pl.col("_cnae_ok") == False).fill_null(False).alias("c"),  # noqa: E712
        (irreg & (pl.col("data_situacao") <= pl.col("assinatura"))).alias("d_antes"),
        (irreg & (pl.col("data_situacao") > pl.col("assinatura"))
         & (pl.col("data_situacao") <= pl.col("assinatura") + timedelta(days=180))).alias("d_logo"),
        matriz.alias("matriz"),
    ).with_columns((pl.col("d_antes") | pl.col("d_logo")).alias("d")).drop(
        [f"cat_{n}" for n in CATEGORIAS] + ["_cnae_ok"])


def indicador_e(c):
    """Fornecedoras (raízes de CNPJ diferentes) do mesmo órgão no mesmo endereço ou com sócio em comum."""
    org = pl.coalesce(pl.col("orgao"), pl.col("ug"), pl.lit("?")) + pl.lit("|") + pl.col("esfera_contrato").fill_null("?")
    c = c.with_columns(org.alias("org"))
    num = pl.col("numero").fill_null("").str.strip_chars()
    end = pl.concat_str(pl.col("cep").fill_null(""), pl.col("logradouro").fill_null("").str.to_uppercase().str.strip_chars(),
                        num, pl.col("complemento").fill_null("").str.to_uppercase().str.strip_chars(), separator="|")
    valido = ((pl.col("cep").fill_null("").str.len_chars() == 8) & ~num.is_in(["", "S/N", "SN", "0"])
              & (pl.col("logradouro").fill_null("").str.len_chars() > 3))
    ce = c.with_columns(end.alias("_end")).filter(valido).select("org", "raiz", "_end").unique()
    ee = (ce.with_columns(pl.col("raiz").n_unique().over("org", "_end").alias("n"))
            .filter(pl.col("n").is_between(2, GRUPO_MAX)).select("org", "raiz").unique()
            .with_columns(pl.lit(True).alias("e_endereco")))
    par = c.select("org", "raiz").unique()
    s = (pl.scan_parquet(QSA / "socios.parquet").filter(pl.col("cnpj_basico").is_in(par["raiz"].unique()))
           .select(pl.col("cnpj_basico").alias("raiz"), "cpf6", "nome_norm").unique().collect())
    es = (par.join(s, on="raiz").with_columns(pl.col("raiz").n_unique().over("org", "cpf6", "nome_norm").alias("n"))
             .filter(pl.col("n").is_between(2, GRUPO_MAX)).select("org", "raiz").unique()
             .with_columns(pl.lit(True).alias("e_socio")))
    c = c.join(ee, on=["org", "raiz"], how="left").join(es, on=["org", "raiz"], how="left")
    return c.with_columns(pl.col("e_endereco").fill_null(False), pl.col("e_socio").fill_null(False)).with_columns(
        (pl.col("e_endereco") | pl.col("e_socio")).alias("e"))


def grau(c):
    n = sum(pl.col(x).cast(pl.Int32) for x in "abcde")
    return c.with_columns(n.alias("n_ind")).with_columns(
        pl.when(pl.col("n_ind") >= 3).then(pl.lit("alta"))
          .when(pl.col("n_ind") == 2).then(pl.lit("média"))
          .when(pl.col("n_ind") == 1).then(pl.lit("baixa")).alias("grau"))


def resumo(g):
    # valor soma só contratos <= R$ 1 bi: há erros de digitação de centenas de bilhões no SIASG/PNCP
    return {"contratos": g.height, "empresas": g["cnpj"].n_unique(),
            "valor": round(float(g.filter(pl.col("valor") <= VALOR_MAX)["valor"].sum() or 0))}


def bloco(c):
    out = {"universo": resumo(c)}
    for k in ["a", "a_90d", "b", "b_1000x", "c", "d", "d_antes", "d_logo", "e", "e_endereco", "e_socio"]:
        out[k] = resumo(c.filter(pl.col(k)))
    out["inicio_posterior_assinatura"] = resumo(c.filter(pl.col("inicio_posterior")))
    out["capital_zero_valor_ge_50k"] = resumo(c.filter(pl.col("capital_zero")))
    out["grau"] = {gr: resumo(c.filter(pl.col("grau") == gr)) for gr in ["alta", "média", "baixa"]}
    out["sem_indicador"] = resumo(c.filter(pl.col("n_ind") == 0))
    comb = (c.filter(pl.col("n_ind") >= 2)
              .with_columns(pl.concat_str([pl.when(pl.col(k)).then(pl.lit(k)) for k in "abcde"], separator="+",
                                          ignore_nulls=True).alias("comb"))
              .group_by("comb").agg(pl.len().alias("contratos"), pl.col("cnpj").n_unique().alias("empresas"),
                                    pl.col("valor").filter(pl.col("valor") <= VALOR_MAX).sum().round(0).alias("valor"))
              .sort("contratos", descending=True).head(12))
    out["combinacoes"] = comb.to_dicts()
    # taxa por segmento: MEI e empresa nova podem ser legítimos, então o que importa é o contraste
    seg = []
    for (s,), g in c.group_by("segmento"):
        row = {"segmento": s, "contratos": g.height, "empresas": g["cnpj"].n_unique(),
               "mediana_valor": round(float(g["valor"].median()))}
        for k in "abcde":
            row["pct_" + k] = round(float(g[k].mean()), 4)
        row["pct_alta_ou_media"] = round(float((g["n_ind"] >= 2).mean()), 4)
        seg.append(row)
    out["por_segmento"] = sorted(seg, key=lambda x: -x["contratos"])
    esf = []
    for (e,), g in c.group_by("esfera_contrato"):
        row = {"esfera": e, "contratos": g.height}
        for k in "abcde":
            row["n_" + k] = int(g[k].sum())
        row["n_alta"] = int((g["n_ind"] >= 3).sum())
        row["n_media"] = int((g["n_ind"] == 2).sum())
        esf.append(row)
    out["por_esfera"] = sorted(esf, key=lambda x: -x["contratos"])
    fx = []
    for lo, hi, nome in [(0, 50_000, "até R$ 50 mil"), (50_000, 500_000, "R$ 50 mil a 500 mil"),
                         (500_000, 5_000_000, "R$ 500 mil a 5 mi"), (5_000_000, 1e15, "acima de R$ 5 mi")]:
        g = c.filter((pl.col("valor") >= lo) & (pl.col("valor") < hi))
        if g.height:
            fx.append({"faixa": nome, "contratos": g.height, **{"pct_" + k: round(float(g[k].mean()), 4) for k in "abde"},
                       "pct_alta_ou_media": round(float((g["n_ind"] >= 2).mean()), 4)})
    out["por_faixa_valor"] = fx
    cc = (c.filter(pl.col("categoria_objeto").is_not_null()).group_by("categoria_objeto")
            .agg(pl.len().alias("contratos_com_categoria"), pl.col("c").sum().alias("cnae_sem_relacao"))
            .sort("contratos_com_categoria", descending=True))
    out["c_por_categoria"] = cc.to_dicts()
    top = (c.filter(pl.col("a")).group_by("org").agg(pl.len().alias("n_a"))
            .join(c.group_by("org").agg(pl.len().alias("n")), on="org").sort("n_a", descending=True).head(10))
    out["orgaos_top_a"] = [{"orgao": o.split("|")[0], "esfera": o.split("|")[1], "contratos_a": a, "contratos": n}
                           for o, a, n in top.select("org", "n_a", "n").iter_rows()]
    h = (c.filter(pl.col("dias_abertura").is_between(0, 729) & pl.col("matriz"))
           .group_by((pl.col("dias_abertura") // 90).alias("tri")).agg(pl.len().alias("contratos")).sort("tri"))
    out["abertura_por_trimestre_0_24m"] = [{"de_dias": t * 90, "contratos": n} for t, n in h.iter_rows()]
    return out


def main():
    meta = json.loads((QSA / "meta.json").read_text())
    c, cob = carrega()
    c, ex = exclusoes(c)
    c = grau(indicador_e(indicadores_abcd(c)))
    janela = c.filter(pl.col("assinatura").is_between(*JANELA))
    stats = {"mes_cadastro_receita": meta["mes"], "cobertura": cob, "exclusoes": ex.to_dicts(),
             "parametros": {"a_meses": 6, "b_razao": RAZAO_B, "b_valor_min": VALOR_MIN_B, "d_dias_depois": 180,
                            "e_grupo_max": GRUPO_MAX, "janela_continua": [str(d) for d in JANELA]},
             "todos_os_meses": bloco(c), "janela_continua": bloco(janela)}
    (DATA / "fachada_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    c.filter(pl.col("n_ind") >= 1).select(
        "chave", "fonte", "esfera_contrato", "orgao", "ug", "uf", "municipio", "assinatura", "valor", "objeto", "cnpj",
        "contratado", "segmento", "capital_social", "porte", "data_inicio", "dias_abertura", "cnae_principal",
        "categoria_objeto", "situacao", "data_situacao", "a", "b", "c", "d", "e", "e_endereco", "e_socio",
        "n_ind", "grau").write_parquet(DATA / "fachada_casos.parquet", compression="zstd")
    print(json.dumps({k: stats["todos_os_meses"][k] for k in ["universo", "a", "b", "c", "d", "e", "grau", "sem_indicador"]},
                     ensure_ascii=False))
    print(cob, ex.to_dicts())


if __name__ == "__main__":
    main()
