"""Tipologia 2: servidor federal sócio de empresa contratada pelo órgão em que trabalha.

Lei 14.133/2021, art. 9º, §1º: o agente público de órgão ou entidade licitante ou
contratante não pode participar, direta ou indiretamente, da licitação ou da
execução do contrato. Lei 8.112/1990, art. 117, X: o servidor não pode participar
de gerência ou administração de sociedade privada (pode ser só cotista ou
acionista).

Uso: uv run scripts/servidor_socio.py          (baixa o que faltar e cruza)
     uv run scripts/servidor_socio.py --baixar (só baixa os cadastros)

Entradas:
- data/qsa/socios.parquet (scripts/qsa.py): sócios pessoa física do CNPJ.
- Cadastro completo de servidores do SIAPE e do Banco Central em alguns meses
  (MESES), baixado do Portal da Transparência com o mesmo URL de
  scripts/servidores.py, mas sem o filtro do e-Agendas. Fica em
  data/servidor_socio_cadastro/AAAAMM[_BACEN].parquet, só com nome, CPF parcial,
  cargo, função e órgãos de lotação e exercício.
- Contratos federais: data/contratos/raw/*.zip (SIASG, lidos por
  sancoes.contratos()) e data/contratos/pncp/*.parquet (PNCP, só esfera federal).

Saídas (com nomes de pessoas físicas, só no disco local):
- data/servidor_socio.parquet: um servidor x empresa x contrato por linha.
- data/servidor_socio_stats.json: números agregados.

Regras:
- Servidor ↔ sócio pela chave nome normalizado + os 6 dígitos visíveis do CPF
  (os dois cadastros mostram os mesmos dígitos, do 4º ao 9º).
- Sócio → contratos pela raiz do CNPJ (8 dígitos), que junta matriz e filiais.
- "Mesmo órgão": o órgão ou a UG contratante é o órgão de lotação ou de exercício
  do servidor, por casamento aproximado de nome (mesmo_orgao() de sancoes.py ou
  mesmo_nome_orgao() de porta_giratoria.py). "Mesma pasta" usa o órgão superior.
- Servidor na data: o servidor consta do cadastro do mês de MESES mais próximo da
  assinatura (no máximo 12 meses de distância). Fora disso, o contrato fica como
  "sem retrato" e não entra nas contagens principais.
- Sócio na data: a entrada na sociedade é anterior ou igual à assinatura. O QSA
  só mostra a composição atual, então quem saiu da sociedade antes do mês do QSA
  não aparece (piso, não teto).
- Administrador: qualificações com poder de gestão (sócio-administrador,
  administrador, diretor, presidente, titular de empresa individual etc.), o que
  a Lei 8.112 veda. Os demais (sócio, sócio com/sem capital, cotista) só ferem a
  Lei 14.133 se o servidor atuou na licitação ou no contrato, o que estes dados
  não mostram.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from porta_giratoria import mesmo_nome_orgao  # noqa: E402
from extract import norm  # noqa: E402
from sancoes import VAZIAS, contratos  # noqa: E402
from servidores import COLS, URL, baixa  # noqa: E402
from qsa import norm_expr  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
CAD = DATA / "servidor_socio_cadastro"
# retratos do cadastro espalhados pelo período dos contratos (SIASG 2022-01..2025-01, PNCP 2023+)
MESES = ["202206", "202212", "202306", "202312", "202406", "202412", "202508"]
CAD_COLS = ["Id_SERVIDOR_PORTAL", "NOME", "CPF", "DESCRICAO_CARGO", "SIGLA_FUNCAO", "NIVEL_FUNCAO", "FUNCAO",
            "ORG_LOTACAO", "ORGSUP_LOTACAO", "ORG_EXERCICIO", "ORGSUP_EXERCICIO", "TIPO_VINCULO",
            "SITUACAO_VINCULO"]
assert set(CAD_COLS) <= set(COLS + ["CPF"])
# qualificações com poder de gerência ou administração (tabela Qualificacoes da Receita)
ADMIN = {"05", "10", "16", "28", "34", "49", "50", "65", "66", "67", "68", "70", "72", "73", "74"}
# sócios sem função de gestão no QSA
SOCIO = {"22", "23", "24", "25", "26", "29", "30", "31", "38", "47", "52", "53", "55", "56", "58"}
# o resto ("outro"): conselheiro de administração, procurador, liquidante, inventariante etc.


def baixa_cadastros():
    CAD.mkdir(exist_ok=True)
    for mes in MESES:
        for fonte in ("SIAPE", "BACEN"):
            dest = CAD / (f"{mes}.parquet" if fonte == "SIAPE" else f"{mes}_BACEN.parquet")
            if dest.exists():
                continue
            buf = baixa(URL.format(mes, fonte))
            if buf[:2] != b"PK":
                raise SystemExit(f"{mes} {fonte}: resposta não é zip (verificação humana?); parando")
            z = zipfile.ZipFile(io.BytesIO(buf))
            nome = next(n for n in z.namelist() if n.endswith("Cadastro.csv"))
            d = pl.read_csv(z.read(nome), separator=";", encoding="latin1", infer_schema=False, columns=CAD_COLS)
            d = d.with_columns(
                pl.concat_str(pl.col("CPF").str.extract(r"^\*{3}\.(\d{3})\.(\d{3})-\*{2}$", 1),
                              pl.col("CPF").str.extract(r"^\*{3}\.(\d{3})\.(\d{3})-\*{2}$", 2)).alias("cpf6"),
                norm_expr("NOME").alias("nome_norm"),
                pl.lit(mes).alias("mes"), pl.lit(fonte).alias("fonte"),
            ).drop("CPF")
            d.write_parquet(dest, compression="zstd")
            print(mes, fonte, d.height, "linhas", file=sys.stderr)


if __name__ == "__main__" and "--baixar" in sys.argv:
    baixa_cadastros()
    sys.exit()


# além das de sancoes.VAZIAS: palavras que se repetem em dezenas de órgãos (todo
# instituto federal tem EDUCACAO CIENCIA TECNOLOGIA) e não distinguem um do outro
GENERICAS = {"EDUCACAO", "CIENCIA", "TECNOLOGIA", "TECNOLOGICA", "FUNDACAO", "HOSPITAL", "UNIVERSITARIO",
             "UNIDADES", "UNIDADE", "COM", "VINCULO", "DIRETO", "GESTORA", "EXECUTORA", "AGENCIA", "CENTRO",
             "PESQUISA", "SAUDE", "SERVICOS", "SERVICO", "EMPRESA", "BRASILEIRA", "SUPERIOR", "ESCOLA",
             "INST", "FED", "EDUC", "CIENC", "TEC", "UNIV", "FUND", "MIN", "SEC", "SUPERINT", "A", "O", "AS", "OS"}
STOP = {"DE", "DA", "DO", "DAS", "DOS", "E", "EM", "NO", "NA", "A", "O"}
# tipo de instituição: os dois nomes têm de ter o mesmo. Sem isso, com as palavras
# genéricas de lado, "INST.FED.DE EDUC.,CIENC.E TEC.DA BAHIA" vira só "BAHIA" e casa
# com a UFBA, e a UTFPR casa com a UFPR.
TIPOS = {"UNIVERSIDADE": "UNIV", "UNIV": "UNIV", "INSTITUTO": "INST", "INST": "INST", "CENTRO": "CENTRO",
         "TECNOLOGICA": "TEC", "TECNOLOGICO": "TEC", "RURAL": "RURAL", "HOSPITAL": "HOSP", "AGENCIA": "AGENCIA",
         "ESCOLA": "ESCOLA", "COMANDO": "COMANDO", "CONSELHO": "CONSELHO", "EMPRESA": "EMPRESA"}


def tipo(tokens) -> set:
    return {TIPOS[t] for t in tokens if t in TIPOS}


def mesmo(a: str, b: str) -> bool:
    """Mesmo órgão por nome. Aceita se porta_giratoria.mesmo_nome_orgao (que
    tolera as abreviações do SIAPE) diz que sim; senão, toda palavra distintiva
    de cada lado tem de ter par no outro, igual ou abreviada por prefixo.
    sancoes.mesmo_orgao, que aceita 60% das palavras, junta institutos federais
    de estados diferentes e a UFRJ com a Rural do Rio, então aqui não basta."""
    if not a or not b:
        return False
    if mesmo_nome_orgao(a, b):
        return True
    ta = [t for t in norm(a).split() if t not in STOP]
    tb = [t for t in norm(b).split() if t not in STOP]
    da = {t for t in ta if t not in GENERICAS and t not in VAZIAS}
    db = {t for t in tb if t not in GENERICAS and t not in VAZIAS}
    if tipo(ta) != tipo(tb) and tipo(ta) and tipo(tb):
        return False
    if not da and not db:
        # nome só com palavras genéricas ("MINISTERIO DA SAUDE"): um contido no outro
        return set(ta) <= set(tb) or set(tb) <= set(ta)
    par = lambda x, ys: any(x == y or (min(len(x), len(y)) >= 3 and (x.startswith(y) or y.startswith(x)))  # noqa: E731
                            for y in ys)
    return bool(da) and bool(db) and all(par(x, db) for x in da) and all(par(y, da) for y in db)


def tipo_empresa(nat):
    """Natureza jurídica (tabela Naturezas da Receita) -> grupo."""
    return (pl.when(nat.is_in(["2011", "2038"])).then(pl.lit("estatal"))
            .when(nat.str.starts_with("2")).then(pl.lit("empresa privada"))
            .when(nat.str.starts_with("3")).then(pl.lit("sem fins lucrativos"))
            .when(nat.str.starts_with("1")).then(pl.lit("administração pública"))
            .when(nat.is_null()).then(pl.lit("sem cadastro"))
            .otherwise(pl.lit("outra")))


def mes_int(m: str) -> int:
    return int(m[:4]) * 12 + int(m[4:]) - 1


def cadastro() -> pl.DataFrame:
    fs = sorted(CAD.glob("*.parquet"))
    s = pl.concat([pl.read_parquet(f) for f in fs])
    return s.filter(pl.col("cpf6").is_not_null() & (pl.col("cpf6") != "000000"))


def colisao(serv: pl.DataFrame, soc_chaves: pl.DataFrame, rodadas=20) -> dict:
    """Quantos servidores casariam com algum sócio por acaso: sorteia de novo os
    CPF6 dos servidores dentro da mesma região fiscal (9º dígito do CPF, o último
    dos 6 visíveis) e refaz o casamento."""
    pessoas = serv.select("nome_norm", "cpf6").unique().with_columns(pl.col("cpf6").str.slice(5, 1).alias("reg"))
    nomes_qsa = soc_chaves.join(pessoas.select("nome_norm").unique(), on="nome_norm")
    real = pessoas.join(nomes_qsa, on=["nome_norm", "cpf6"]).height
    mesmo_nome = pessoas.join(nomes_qsa.rename({"cpf6": "cpf6_q"}), on="nome_norm")
    falsos = []
    for i in range(rodadas):
        emb = pessoas.with_columns(pl.col("cpf6").shuffle(seed=i).over("reg"))
        falsos.append(emb.join(nomes_qsa, on=["nome_norm", "cpf6"]).height)
    return {
        "pessoas_servidor": pessoas.height,
        "servidores_com_homonimo_no_qsa": mesmo_nome["nome_norm"].n_unique(),
        "pares_mesmo_nome": mesmo_nome.height,
        "pares_mesmo_nome_cpf6_diferente": mesmo_nome.filter(pl.col("cpf6") != pl.col("cpf6_q")).height,
        "casados_nome_cpf6": real,
        "rodadas": rodadas,
        "falsos_por_rodada": falsos,
        "falsos_media": sum(falsos) / rodadas,
        "taxa_falso_positivo": sum(falsos) / rodadas / real if real else None,
    }


def fmt(v):
    return round(float(v or 0), 2)


def main():
    if not (DATA / "qsa" / "socios.parquet").exists():
        raise SystemExit("rode antes: uv run scripts/qsa.py")
    baixa_cadastros()
    qsa_meta = json.loads((DATA / "qsa" / "meta.json").read_text())

    serv = cadastro()
    # chave nome+cpf6 dentro do próprio cadastro: quantas apontam para 2+ IDs
    ids = serv.group_by("nome_norm", "cpf6").agg(pl.col("Id_SERVIDOR_PORTAL").n_unique().alias("n"),
                                                 pl.col("fonte").n_unique().alias("fontes"))
    dentro = {"chaves": ids.height, "chaves_2+_ids": ids.filter(pl.col("n") > 1).height,
              "chaves_2+_ids_mesma_fonte": ids.filter((pl.col("n") > 1) & (pl.col("fontes") == 1)).height}

    soc = (pl.scan_parquet(DATA / "qsa" / "socios.parquet")
           .filter(pl.col("cpf6").is_not_null() & (pl.col("cpf6") != "000000")))
    chaves_serv = serv.select("nome_norm", "cpf6").unique()
    soc_chaves = soc.select("nome_norm", "cpf6").unique().join(
        chaves_serv.lazy().select("nome_norm").unique(), on="nome_norm").collect()
    col = colisao(serv, soc_chaves)
    col["dentro_do_cadastro"] = dentro
    print("colisão", {k: v for k, v in col.items() if k != "falsos_por_rodada"}, file=sys.stderr)

    socios = soc.join(chaves_serv.lazy(), on=["nome_norm", "cpf6"]).collect()
    socios = socios.with_columns(
        pl.when(pl.col("cod_qualificacao").is_in(ADMIN)).then(pl.lit("administrador"))
          .when(pl.col("cod_qualificacao").is_in(SOCIO)).then(pl.lit("sócio"))
          .otherwise(pl.lit("outro")).alias("papel"))
    emp = (pl.scan_parquet(DATA / "qsa" / "empresas.parquet")
           .join(socios.lazy().select("cnpj_basico").unique(), on="cnpj_basico").collect())
    socios = socios.join(emp.select("cnpj_basico", "natureza_juridica", "natureza", "porte"), on="cnpj_basico",
                         how="left").with_columns(tipo_empresa(pl.col("natureza_juridica")).alias("tipo_empresa"))
    print("vínculos servidor-empresa", socios.height, file=sys.stderr)

    c = contratos()
    if "esfera_contrato" in c.columns:
        c = c.filter(pl.col("esfera_contrato") == "F")
    if "fonte" not in c.columns:
        c = c.with_columns(pl.lit("siasg").alias("fonte"))
    c = c.filter(pl.col("assinatura").is_not_null())
    base_contratos = {"contratos": c.height, "valor": fmt(c["valor"].sum()),
                      "assinatura_de": str(c["assinatura"].min()), "assinatura_ate": str(c["assinatura"].max()),
                      "por_fonte": {f: n for f, n in c.group_by("fonte").len().iter_rows()}}

    m = socios.join(c, left_on="cnpj_basico", right_on="raiz")
    # retrato do cadastro mais próximo da assinatura
    mis = [mes_int(x) for x in MESES]
    m = m.with_columns((pl.col("assinatura").dt.year() * 12 + pl.col("assinatura").dt.month() - 1).alias("mi_ass"))
    m = m.with_columns(pl.col("mi_ass").map_elements(
        lambda x: min(mis, key=lambda y: abs(y - x)), return_dtype=pl.Int64).alias("mi_retrato"))
    m = m.with_columns(((pl.col("mi_retrato") - pl.col("mi_ass")).abs() <= 12).alias("tem_retrato"))
    serv_m = serv.with_columns(pl.col("mes").map_elements(mes_int, return_dtype=pl.Int64).alias("mi_retrato"))
    lot = serv_m.group_by("nome_norm", "cpf6", "mi_retrato").agg(
        pl.col("ORG_LOTACAO", "ORG_EXERCICIO", "ORGSUP_LOTACAO", "ORGSUP_EXERCICIO", "DESCRICAO_CARGO", "FUNCAO",
               "SIGLA_FUNCAO", "NIVEL_FUNCAO", "SITUACAO_VINCULO").drop_nulls().unique(),
        pl.col("Id_SERVIDOR_PORTAL").unique(), pl.col("fonte").unique())
    m = m.join(lot, on=["nome_norm", "cpf6", "mi_retrato"], how="left").with_columns(
        pl.col("Id_SERVIDOR_PORTAL").is_not_null().alias("servidor_na_data"))

    # órgão: compara uma vez cada combinação distinta
    def rel(r):
        orgs_c = [r["orgao"], r["ug"]]
        orgs_s = [o for o in (r["ORG_LOTACAO"] or []) + (r["ORG_EXERCICIO"] or []) if o and o != "Sem informação"]
        if any(mesmo(a, b) for a in orgs_c for b in orgs_s):
            return "mesmo órgão"
        sups_s = [o for o in (r["ORGSUP_LOTACAO"] or []) + (r["ORGSUP_EXERCICIO"] or []) if o]
        sups_c = [r["orgao_superior"], r["orgao"]]
        if any(mesmo(a, b) for a in sups_c for b in sups_s + orgs_s):
            return "mesma pasta"
        return ""
    combos = m.filter(pl.col("servidor_na_data")).select(
        "orgao", "ug", "orgao_superior", "ORG_LOTACAO", "ORG_EXERCICIO", "ORGSUP_LOTACAO", "ORGSUP_EXERCICIO").unique()
    combos = combos.with_columns(pl.struct(pl.all()).map_elements(rel, return_dtype=pl.String).alias("relacao"))
    m = m.join(combos, on=["orgao", "ug", "orgao_superior", "ORG_LOTACAO", "ORG_EXERCICIO", "ORGSUP_LOTACAO",
                           "ORGSUP_EXERCICIO"], how="left", nulls_equal=True)
    m = m.with_columns(
        pl.col("relacao").fill_null(""),
        (pl.col("data_entrada").is_null() | (pl.col("data_entrada") <= pl.col("assinatura"))).alias("socio_na_data"),
        pl.concat_str("nome_norm", "cpf6", separator="|").alias("pessoa"),
    )
    m.write_parquet(DATA / "servidor_socio.parquet", compression="zstd")

    def resumo(g: pl.DataFrame) -> dict:
        u = g.unique(["pessoa", "chave"])  # um contrato conta uma vez por servidor
        uc = g.unique("chave")
        return {"servidores": g["pessoa"].n_unique(), "empresas": g["cnpj_basico"].n_unique(),
                "contratos": uc.height, "valor": fmt(uc["valor"].sum()), "pares_servidor_contrato": u.height}

    na_data_todos = m.filter(pl.col("servidor_na_data") & pl.col("socio_na_data"))
    proprio_todos = na_data_todos.filter(pl.col("relacao") == "mesmo órgão")
    # o indício é sócio de empresa privada; fundação de apoio, associação e estatal
    # (onde o servidor é dirigente por designação, com previsão legal) ficam à parte
    privada = pl.col("tipo_empresa") == "empresa privada"
    na_data = na_data_todos.filter(privada)
    proprio = proprio_todos.filter(privada)
    stats = {
        "gerado_em": str(__import__("datetime").date.today()),
        "qsa": qsa_meta,
        "cadastro": {"meses": MESES, "linhas": serv.height, "pessoas": chaves_serv.height,
                     "fontes": sorted(serv["fonte"].unique().to_list())},
        "contratos_base": base_contratos,
        "colisao": col,
        "mesmo_orgao_por_tipo_empresa": {t: resumo(g) for (t,), g in proprio_todos.group_by("tipo_empresa")},
        "na_assinatura_por_tipo_empresa": {t: resumo(g) for (t,), g in na_data_todos.group_by("tipo_empresa")},
        "servidores_socios": {
            "pessoas": socios["pessoa"].n_unique() if "pessoa" in socios.columns else
            socios.select("nome_norm", "cpf6").unique().height,
            "vinculos": socios.height, "empresas": socios["cnpj_basico"].n_unique(),
            "por_papel": {p: socios.filter(pl.col("papel") == p).select("nome_norm", "cpf6").unique().height
                          for p in ("administrador", "sócio", "outro")},
            "por_papel_empresa_privada": {
                p: socios.filter((pl.col("papel") == p) & privada).select("nome_norm", "cpf6").unique().height
                for p in ("administrador", "sócio", "outro")},
            "em_empresa_privada": socios.filter(privada).select("nome_norm", "cpf6").unique().height,
        },
        "socios_de_contratadas_qualquer_data": resumo(m.filter(privada)),
        "sem_retrato": resumo(m.filter(~pl.col("tem_retrato") & privada)),
        "servidor_e_socio_na_assinatura": resumo(na_data),
        "mesmo_orgao": resumo(proprio),
        "mesmo_orgao_administrador": resumo(proprio.filter(pl.col("papel") == "administrador")),
        "mesmo_orgao_socio": resumo(proprio.filter(pl.col("papel") != "administrador")),
        "mesma_pasta": resumo(na_data.filter(pl.col("relacao") == "mesma pasta")),
        "outro_orgao": resumo(na_data.filter(pl.col("relacao") == "")),
        "mesmo_orgao_entrou_depois_da_assinatura": resumo(m.filter(
            pl.col("servidor_na_data") & ~pl.col("socio_na_data") & (pl.col("relacao") == "mesmo órgão") & privada)),
        "mesmo_orgao_por_fonte": {f: resumo(g) for (f,), g in proprio.group_by("fonte")},
        "mesmo_orgao_top_orgaos": [
            {"orgao": o, "servidores": g["pessoa"].n_unique(), "contratos": g["chave"].n_unique(),
             "valor": fmt(g.unique("chave")["valor"].sum())}
            for (o,), g in sorted(proprio.group_by("orgao"), key=lambda x: -x[1]["chave"].n_unique())[:15]],
        "mesmo_orgao_com_funcao": resumo(proprio.filter(pl.col("FUNCAO").list.eval(
            pl.element().is_in(["Sem informação", "Sigiloso", ""]).not_()).list.any())),
        "mesmo_orgao_vinculo": {str(k): n for k, n in proprio.unique("pessoa").with_columns(
            pl.col("SITUACAO_VINCULO").list.first()).group_by("SITUACAO_VINCULO").len().iter_rows()},
        # a Lei 8.112 veda a administração de empresa privada em qualquer caso, não só
        # quando a empresa contrata com o próprio órgão
        "administrador_de_contratada_qualquer_orgao": resumo(na_data.filter(pl.col("papel") == "administrador")),
        "administrador_qualquer_orgao_estatutario": resumo(na_data.filter(
            (pl.col("papel") == "administrador")
            & ~pl.col("SITUACAO_VINCULO").list.eval(pl.element().str.contains("CELETISTA|CONTRATO TEMPORARIO")).list.all())),
        "mesmo_orgao_cargos": {str(k): n for k, n in proprio.unique("pessoa").with_columns(
            pl.col("DESCRICAO_CARGO").list.first()).group_by("DESCRICAO_CARGO").len()
            .sort("len", descending=True).head(15).iter_rows()},
        "mesmo_orgao_maior_contrato": fmt(proprio["valor"].max()),
        "mesmo_orgao_mediana_contrato": fmt(proprio.unique("chave")["valor"].median()),
        "mesmo_orgao_modalidade": {str(k): n for k, n in proprio.unique("chave").group_by("modalidade").len()
                                   .sort("len", descending=True).iter_rows()},
        "mesmo_orgao_qualificacao": {str(k): n for k, n in proprio.unique(["pessoa", "cnpj_basico"])
                                     .group_by("qualificacao").len().sort("len", descending=True).iter_rows()},
    }
    (DATA / "servidor_socio_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in stats.items() if k not in ("colisao",)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
