"""Tipologia 1: empresa sancionada contratada pelo poder público.

Cruza os cadastros de sanções da CGU (CEIS e CNEP) com contratos de duas fontes
e aponta contratos assinados enquanto a empresa estava impedida de contratar:
  siasg  contratos federais do Portal da Transparência (jan/2022 a jan/2025)
  pncp   contratos de todas as esferas do PNCP (scripts/pncp.py)

Uso: uv run scripts/sancoes.py
     (espera data/sancoes/AAAAMMDD_CEIS.csv, AAAAMMDD_CNEP.csv;
      data/contratos/raw/AAAAMM.zip, de
      portaldatransparencia.gov.br/download-de-dados/{ceis,cnep,compras};
      e data/contratos/pncp/AAAAMM.parquet, de scripts/pncp.py)

Grava data/sancoes_contratos.parquet (um contrato x sanção por linha) e
data/sancoes_stats.json.

Regras:
- Só sanções que impedem contratar: impedimento, suspensão e inidoneidade.
  Multa, publicação extraordinária etc. ficam fora.
- O contrato conta se a data de assinatura cai entre o início e o fim da sanção
  (fim vazio = sem prazo, ainda vigente). Quando o CEIS deixa o fim vazio mas as
  observações dizem o prazo ("pelo período de 1 mês"), o fim é calculado
  (fim_inferido). Medida cautelar do Código de Processo Penal vai para o nível D.
- Casamento pelo CNPJ completo (14 dígitos). Sanção da matriz atingindo contrato
  da filial (mesma raiz de 8 dígitos) é contada à parte, como "raiz".
- Abrangência. O nível diz o quanto a sanção vale; o ente diz onde:
    A) inidoneidade que o cadastro marca "todas as esferas" ou que tem base em lei
       federal (vale em todo lugar pela Lei 14.133, art. 156, §5º): vale em
       qualquer contrato. Impedimento e suspensão marcados "todas as esferas" NÃO
       são A: vão para D e só valem no ente do sancionador. Falso positivo
       achado na conferência manual: um impedimento municipal (Lei 8.666,
       art. 88) marcado "todas as esferas" casava com contratos de prefeituras
       de todo o país;
    B) vale em todos os poderes da esfera do órgão sancionador;
    C) vale só no órgão sancionador, ou na esfera e no poder dele: conta só se
       o órgão contratante for o mesmo (casamento aproximado pelo nome, precisa
       de conferência manual). "Na Esfera e no Poder" foi para C porque o CEIS
       não diz o poder do sancionador e o filtro por esfera deixaria passar,
       por exemplo, sanção de um TRE (Judiciário) em contrato da EBSERH
       (Executivo). Falso positivo achado na conferência manual;
    D) abrangência "Sem Informação" ou outra: ambígua.
  Nos níveis B a D a sanção só vale no ente do sancionador: federal (impedimento
  da Lei 14.133, art. 156, III, e da Lei 10.520) só em contratos da União;
  estadual (ou distrital) só em contratos estaduais da mesma UF; municipal só em
  contratos do mesmo município (município achado no nome do órgão sancionador).
- Fontes: o mesmo contrato federal aparece no SIASG e no PNCP. Contrato do PNCP
  federal é descartado se o SIASG já tem o mesmo CNPJ + UASG + (data de
  assinatura ou número de contrato). Dentro do PNCP, vale o id do PNCP.
- O CEIS só guarda as sanções que ainda estão no cadastro. Sanção expirada e
  removida não aparece, então a contagem é um piso, nunca um teto.
"""
import io
import json
import re
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from extract import norm  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
IMPEDE = ("Impedimento", "Suspensão", "Declaração de Inidoneidade")
# palavras que não ajudam a dizer se dois nomes de órgão são o mesmo
VAZIAS = {"DE", "DA", "DO", "DAS", "DOS", "E", "EM", "NO", "NA", "MINISTERIO", "SECRETARIA",
          "FEDERAL", "NACIONAL", "BRASIL", "BRASILEIRO", "BRASILEIRA", "INSTITUTO", "UNIVERSIDADE",
          "SUPERINTENDENCIA", "REGIONAL", "ESTADO", "GERAL", "COORDENACAO", "COMANDO"}


NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "doze": 12}
PRAZO = r"(?i)(?:prazo|per[ií]odo)\s+de\s+(\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|doze)\s*(?:\([^)]*\)\s*)?(m[eê]s(?:es)?|anos?|dias?)"


def dt(c):
    return pl.col(c).str.to_date("%d/%m/%Y", strict=False)


def digitos(c):
    return pl.col(c).str.replace_all(r"\D", "")


def prazo_inferido(s: pl.DataFrame) -> pl.DataFrame:
    """Muitas sanções vêm sem data final no CEIS, mas as observações dizem o prazo
    ("pelo período de 1 (um) mês"). Sem isso, a sanção de um mês contaria como
    eterna. Quando o fim está vazio e as observações trazem um prazo, o fim é o
    início + prazo e fim_inferido fica verdadeiro."""
    def fim(r):
        if r["fim"] is not None or r["inicio"] is None or not r["observacoes"]:
            return {"fim": r["fim"], "fim_inferido": False}
        m = re.search(PRAZO, r["observacoes"])
        if not m:
            return {"fim": None, "fim_inferido": False}
        n = int(m[1]) if m[1].isdigit() else NUMEROS[norm(m[1]).lower()]
        u = norm(m[2])[:3]
        dias = n * 365 if u == "ANO" else n * 30 if u == "MES" else n
        return {"fim": r["inicio"] + timedelta(days=dias), "fim_inferido": True}
    out = s.select(pl.struct("fim", "inicio", "observacoes").map_elements(
        fim, return_dtype=pl.Struct({"fim": pl.Date, "fim_inferido": pl.Boolean})).alias("x")).unnest("x")
    return s.with_columns(out["fim"], out["fim_inferido"])


def sancoes() -> pl.DataFrame:
    partes = []
    for f in sorted((DATA / "sancoes").glob("*_C[EN][IE][SP].csv")):
        d = pl.read_csv(f, separator=";", encoding="latin1", infer_schema=False)
        partes.append(d.select(
            pl.col("CADASTRO").alias("cadastro"),
            pl.col("CÓDIGO DA SANÇÃO").alias("cod_sancao"),
            pl.col("TIPO DE PESSOA").alias("tipo_pessoa"),
            digitos("CPF OU CNPJ DO SANCIONADO").alias("cnpj"),
            pl.col("NOME DO SANCIONADO").alias("sancionado"),
            pl.col("CATEGORIA DA SANÇÃO").alias("categoria"),
            dt("DATA INÍCIO SANÇÃO").alias("inicio"),
            dt("DATA FINAL SANÇÃO").alias("fim"),
            pl.col("ABRAGÊNCIA DA SANÇÃO").alias("abrangencia"),
            pl.col("ÓRGÃO SANCIONADOR").alias("orgao_sancionador"),
            pl.col("ESFERA ÓRGÃO SANCIONADOR").alias("esfera"),
            pl.col("UF ÓRGÃO SANCIONADOR").alias("uf_sancionador"),
            pl.col("NÚMERO DO PROCESSO").alias("processo"),
            pl.col("FUNDAMENTAÇÃO LEGAL").str.slice(0, 120).alias("fundamento"),
            dt("DATA PUBLICAÇÃO").alias("publicacao"),
            dt("DATA ORIGEM INFORMAÇÃO").alias("registro_ceis"),
            pl.col("OBSERVAÇÕES").alias("observacoes"),
        ))
    s = pl.concat(partes)
    s = prazo_inferido(s).with_columns(pl.col("observacoes").str.slice(0, 300))
    impede = (pl.any_horizontal(pl.col("categoria").str.starts_with(p) for p in IMPEDE)
              & ~pl.col("categoria").str.contains("Interdição"))
    s = s.filter((pl.col("tipo_pessoa") == "J") & (pl.col("cnpj").str.len_chars() == 14) & impede)
    # inidoneidade só vale em todo lugar quando aplicada com base em lei federal;
    # a da Lei 9.433/BA, por exemplo, tem efeito só no estado
    lei_federal = pl.col("fundamento").str.contains(r"^LEI (8666|14133|8443|12846|8429)\b")
    inidoneidade = pl.col("categoria").str.starts_with("Declaração de Inidoneidade")
    # medida cautelar do Código de Processo Penal (decisão judicial) não é sanção
    # administrativa: o "todas as esferas" do cadastro é duvidoso, vai para D
    cautelar = pl.col("fundamento").str.contains(r"^(CÓDIGO DE PROCESSO|CPP\b)")
    nivel = (
        pl.when(cautelar).then(pl.lit("D"))
        .when(inidoneidade & (pl.col("abrangencia").str.starts_with("Todas as Esferas") | lei_federal)).then(pl.lit("A"))
        .when(pl.col("abrangencia").str.starts_with("Todas as Esferas")).then(pl.lit("D"))
        .when(pl.col("abrangencia") == "Em todos os Poderes da Esfera do órgão sancionador").then(pl.lit("B"))
        .when(pl.col("abrangencia").is_in(["No órgão sancionador", "Na Esfera e no Poder do órgão sancionador"]))
        .then(pl.lit("C"))
        .otherwise(pl.lit("D"))
    )
    s = s.with_columns(nivel.alias("nivel"), pl.col("cnpj").str.slice(0, 8).alias("raiz"))
    return s.with_columns(pl.col("esfera").str.slice(0, 1).alias("esfera_sanc"))  # F, E, M


def contratos_siasg() -> pl.DataFrame:
    partes = []
    for f in sorted((DATA / "contratos" / "raw").glob("*.zip")):
        with zipfile.ZipFile(f) as z:
            nome = next(n for n in z.namelist() if n.endswith("_Compras.csv"))
            d = pl.read_csv(io.BytesIO(z.read(nome)), separator=";", encoding="latin1", infer_schema=False)
        partes.append(d.select(
            pl.col("Número do Contrato").alias("contrato"),
            pl.col("Objeto").alias("objeto"),
            pl.col("Modalidade Compra").alias("modalidade"),
            pl.col("Nome Órgão Superior").alias("orgao_superior"),
            pl.col("Nome Órgão").alias("orgao"),
            pl.col("Código UG").alias("cod_ug"),
            pl.col("Nome UG").alias("ug"),
            dt("Data Assinatura Contrato").alias("assinatura"),
            dt("Data Fim Vigência").alias("fim_vigencia"),
            digitos("Código Contratado").alias("cnpj"),
            pl.col("Nome Contratado").alias("contratado"),
            pl.col("Valor Final Compra").str.replace(",", ".").cast(pl.Float64, strict=False).alias("valor"),
            pl.lit(f.stem).alias("arquivo"),
        ))
    c = pl.concat(partes).filter(pl.col("cnpj").str.len_chars() == 14)
    # o mesmo contrato reaparece em meses seguintes; fica a versão mais recente
    return (c.sort("arquivo").unique(["cod_ug", "contrato", "cnpj"], keep="last")
             .with_columns(pl.lit("siasg").alias("fonte"), pl.lit("F").alias("esfera_contrato"),
                           pl.lit(None, pl.String).alias("uf"), pl.lit(None, pl.String).alias("municipio"),
                           pl.concat_str("cod_ug", "contrato", "cnpj", separator="|").alias("chave")))


def contratos_pncp(siasg: pl.DataFrame) -> pl.DataFrame:
    fs = sorted((DATA / "contratos" / "pncp").glob("??????.parquet"))
    if not fs:
        return siasg.clear()
    c = pl.concat([pl.read_parquet(f) for f in fs])
    c = c.filter((pl.col("tipo_pessoa") == "PJ") & digitos("cnpj").str.len_chars().eq(14)
                 & pl.col("assinatura").is_not_null())
    c = (c.sort("publicacao_pncp").unique("id_pncp", keep="last")
          .select(pl.col("contrato"), pl.col("objeto"), pl.lit(None, pl.String).alias("modalidade"),
                  pl.lit(None, pl.String).alias("orgao_superior"), pl.col("orgao"),
                  pl.col("cod_unidade").alias("cod_ug"), pl.col("unidade").alias("ug"),
                  pl.col("assinatura"), pl.col("fim_vigencia"), digitos("cnpj").alias("cnpj"),
                  pl.col("contratado"), pl.coalesce("valor_global", "valor_inicial").alias("valor"),
                  pl.lit("pncp").alias("arquivo"), pl.lit("pncp").alias("fonte"),
                  pl.col("esfera").alias("esfera_contrato"), pl.col("uf"), pl.col("municipio"),
                  pl.col("id_pncp").alias("chave")))
    # contrato federal já presente no SIASG
    ja = siasg.select("cnpj", "cod_ug", "assinatura", "contrato")
    dup = c.filter(pl.col("esfera_contrato") == "F").join(ja.select("cnpj", "cod_ug", "assinatura").unique(),
                                                          on=["cnpj", "cod_ug", "assinatura"])["chave"].to_list()
    dup += c.filter(pl.col("esfera_contrato") == "F").join(ja.select("cnpj", "cod_ug", "contrato").unique(),
                                                           on=["cnpj", "cod_ug", "contrato"])["chave"].to_list()
    return c.filter(~pl.col("chave").is_in(dup)).with_columns(pl.lit(len(set(dup))).alias("_dups"))


def contratos() -> pl.DataFrame:
    siasg = contratos_siasg()
    pncp = contratos_pncp(siasg)
    print(f"siasg {siasg.height} | pncp {pncp.height} (federais já no siasg descartados: "
          f"{pncp['_dups'][0] if pncp.height else 0})")
    c = pl.concat([siasg, pncp.drop("_dups", strict=False)], how="diagonal")
    c = c.filter(pl.col("assinatura") <= date.today())  # descarta datas digitadas errado (ex.: 2102)
    return c.with_columns(pl.col("cnpj").str.slice(0, 8).alias("raiz"))


def mesmo_orgao(a: str, b: str) -> bool:
    ta = set(norm(a).split()) - VAZIAS
    tb = set(norm(b).split()) - VAZIAS
    return bool(ta) and bool(tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.6


def municipio_do_sancionador(s: pl.DataFrame, c: pl.DataFrame) -> pl.DataFrame:
    """Acha o município no nome do órgão sancionador municipal: entre os municípios
    da mesma UF vistos nos contratos, o de nome mais longo contido no nome do órgão."""
    nomes = {}
    for uf, m in c.filter(pl.col("municipio").is_not_null()).select("uf", "municipio").unique().iter_rows():
        nomes.setdefault(uf, set()).add(norm(m))
    nomes = {uf: sorted(v, key=len, reverse=True) for uf, v in nomes.items()}

    def acha(o, uf):
        o = f" {norm(o or '')} "
        return next((m for m in nomes.get(uf, []) if f" {m} " in o), None)

    return s.with_columns(pl.struct("orgao_sancionador", "uf_sancionador").map_elements(
        lambda r: acha(r["orgao_sancionador"], r["uf_sancionador"]), return_dtype=pl.String).alias("municipio_sanc"))


def valor(g):
    return round(g["valor"].sum() or 0, 2)


def resumo(g):
    return {"contratos": g.height, "empresas": g["cnpj"].n_unique(), "valor": valor(g),
            "so_cnpj_exato": g.filter(pl.col("casamento") == "cnpj").height,
            "constava_no_ceis": g.filter(pl.col("constava_no_ceis")).height}


def main():
    s, c = sancoes(), contratos()
    s = municipio_do_sancionador(s, c)
    print(f"{s.height} sanções que impedem contratar (PJ) | {c.height} contratos com CNPJ, "
          f"assinados de {c['assinatura'].min()} a {c['assinatura'].max()}")

    dentro = (pl.col("assinatura") >= pl.col("inicio")) & (
        pl.col("fim").is_null() | (pl.col("assinatura") <= pl.col("fim")))
    # onde a sanção vale: nível A em qualquer lugar; senão só no ente do sancionador
    vale = (
        (pl.col("nivel") == "A")
        | ((pl.col("esfera_sanc") == "F") & (pl.col("esfera_contrato") == "F"))
        | ((pl.col("esfera_sanc") == "E") & pl.col("esfera_contrato").is_in(["E", "D"])
           & (pl.col("uf") == pl.col("uf_sancionador")))
        | ((pl.col("esfera_sanc") == "M") & (pl.col("esfera_contrato") == "M")
           & (pl.col("uf") == pl.col("uf_sancionador"))
           & (pl.col("municipio").map_elements(norm, return_dtype=pl.String) == pl.col("municipio_sanc")))
    )
    exato = c.join(s.drop("raiz"), on="cnpj").filter(dentro).with_columns(pl.lit("cnpj").alias("casamento"))
    raiz = (c.join(s.rename({"cnpj": "cnpj_sancionado"}), on="raiz")
             .filter(pl.col("cnpj") != pl.col("cnpj_sancionado")).filter(dentro)
             .drop("cnpj_sancionado").with_columns(pl.lit("raiz").alias("casamento")))
    m = pl.concat([exato, raiz], how="diagonal").filter(vale)
    m = m.with_columns(pl.struct("orgao_sancionador", "orgao", "ug", "orgao_superior").map_elements(
        lambda r: any(mesmo_orgao(r["orgao_sancionador"] or "", r[k] or "") for k in ("orgao", "ug", "orgao_superior")),
        return_dtype=pl.Boolean).alias("mesmo_orgao"))
    m = m.filter((pl.col("nivel") != "C") | pl.col("mesmo_orgao"))
    m = m.with_columns(
        (pl.col("assinatura") - pl.col("inicio")).dt.total_days().alias("dias_apos_inicio"),
        # o órgão deve consultar o CEIS antes de contratar (Lei 14.133, art. 91, §4º);
        # se a sanção só foi registrada depois da assinatura (ou no mesmo dia), ele não tinha como ver
        (pl.col("registro_ceis").is_not_null() & (pl.col("assinatura") > pl.col("registro_ceis")))
        .alias("constava_no_ceis"),
    )
    m.write_parquet(DATA / "sancoes_contratos.parquet")

    # um contrato pode bater com várias sanções: para contar, fica a mais forte
    # (nível A < B < C < D; no empate, CNPJ exato antes de raiz, depois a que já constava no CEIS)
    por_contrato = (m.sort(["nivel", "casamento", "constava_no_ceis", "cod_sancao"], descending=[False, False, True, False])
                    .unique("chave", keep="first", maintain_order=True))
    stats = {
        "base": {"sancoes_impeditivas_pj": s.height, "contratos": c.height,
                 "contratos_por_fonte": {k[0]: g.height for k, g in c.group_by("fonte")},
                 "contratos_por_esfera": {k[0]: g.height for k, g in c.group_by("esfera_contrato")},
                 "assinatura_de": str(c["assinatura"].min()), "assinatura_ate": str(c["assinatura"].max())},
        "por_nivel": {k[0]: resumo(g) for k, g in sorted(por_contrato.group_by("nivel"))},
        "por_fonte_esfera_nivel": {},
    }
    for (fonte, esfera, nivel), g in sorted(por_contrato.group_by("fonte", "esfera_contrato", "nivel")):
        stats["por_fonte_esfera_nivel"].setdefault(fonte, {}).setdefault(esfera, {})[nivel] = resumo(g)
    fortes = por_contrato.filter(pl.col("nivel").is_in(["A", "B", "C"]) & (pl.col("casamento") == "cnpj")
                                 & pl.col("constava_no_ceis"))
    stats["fortes"] = {"contratos": fortes.height, "empresas": fortes["cnpj"].n_unique(), "valor": valor(fortes),
                       "por_fonte_esfera": {f"{k[0]}/{k[1]}": {"contratos": g.height, "empresas": g["cnpj"].n_unique(),
                                                              "valor": valor(g)}
                                            for k, g in sorted(fortes.group_by("fonte", "esfera_contrato"))}}
    # por esfera do contrato (F federal, E estadual/distrital, M municipal) e, à parte, só a janela
    # em que as duas fontes cobrem todos os meses (assinatura de jan/2023 a jan/2025): fora dela
    # o PNCP tem buracos (abr a nov/2025 quase vazios) e os números não são comparáveis
    esf = pl.col("esfera_contrato").replace({"D": "E"})
    jan = (pl.col("assinatura") >= date(2023, 1, 1)) & (pl.col("assinatura") <= date(2025, 1, 31))
    def por_esfera(g):
        g = g.with_columns(esf.alias("e"))
        return {k[0]: resumo(h) | {"valor_mi": round(valor(h) / 1e6, 2)} for k, h in sorted(g.group_by("e"))}
    exato = por_contrato.filter(pl.col("nivel").is_in(["A", "B", "C"]) & (pl.col("casamento") == "cnpj"))
    stats["por_esfera_contrato"] = {
        "todas_as_validas": por_esfera(exato),
        "fortes": por_esfera(fortes),
        "fortes_janela_2023_01_a_2025_01": por_esfera(fortes.filter(jan)),
        "nao_registradas_no_ceis": por_esfera(exato.filter(~pl.col("constava_no_ceis"))),
    }
    nr = exato.filter(~pl.col("constava_no_ceis") & pl.col("registro_ceis").is_not_null())
    stats["atraso_registro_contratos_nao_registrados"] = {
        "contratos": nr.height,
        "mediana_dias_assinatura_ate_registro": (nr["registro_ceis"] - nr["assinatura"]).dt.total_days().median()}
    stats["mesmo_orgao_sancionador_e_contratante_aprox"] = resumo(exato.filter(pl.col("mesmo_orgao"))) | {
        "valor_mi": round(valor(exato.filter(pl.col("mesmo_orgao"))) / 1e6, 2)}
    atraso = s.filter((pl.col("inicio") >= date(2022, 1, 1)) & pl.col("registro_ceis").is_not_null()).with_columns(
        (pl.col("registro_ceis") - pl.col("inicio")).dt.total_days().alias("d"))
    stats["atraso_registro_sancoes_desde_2022"] = {
        k[0]: {"sancoes": g.height, "mediana_dias": g["d"].median(),
               "pct_mais_30d": round((g["d"] > 30).mean() * 100), "pct_mais_180d": round((g["d"] > 180).mean() * 100)}
        for k, g in sorted(atraso.group_by("esfera_sanc"))}
    (DATA / "sancoes_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
