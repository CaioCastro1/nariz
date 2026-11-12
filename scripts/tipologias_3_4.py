"""Tipologias 3 e 4 da porta giratória.

Tipologia 3: servidor ATIVO que se reúne com o governo representando entidade privada
  (Lei 8.112/1990 art. 117, XI; Lei 12.813/2013 art. 5º).
Tipologia 4: quarentena (Lei 12.813/2013 art. 6º, II): ex-ocupante de cargo de alto
  escalão que se reúne com o órgão de origem até 6 meses depois de deixar o cargo.

Entradas (locais, com dados pessoais): data/porta_giratoria.parquet (porta_giratoria.py),
data/servidores/*.parquet (servidores.py).
Saídas:
- data/tipologias_3_4_casos.parquet: uma linha por (reunião, pessoa) em cada tipologia
  (contém nomes: só no disco, nunca publicar).
- data/tipologias_3_4_stats.json: números agregados.

Uso: uv run scripts/tipologias_3_4.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from extract import norm  # noqa: E402
from porta_giratoria import (FORA, QUARENTENA_DIAS, alto_escalao, fim_do_mes, limpa_nome,  # noqa: E402
                             mes_int, mesmo_nome_orgao, relacao_orgao)

DATA = Path(__file__).resolve().parent.parent / "data"
# o mês de saída é o último mês no cadastro: a saída real cai dentro dele, até 30 dias
# antes do fim do mês. Dias contados do fim do mês SUBESTIMAM o tempo real em até ~30 dias.
FOLGA_MES = 30
FOLGA_DIAS = QUARENTENA_DIAS - FOLGA_MES  # 153: dentro da janela mesmo com a imprecisão

# ---------------------------------------------------------------------------------------
# Natureza da entidade representada (por nome; o tipo do painel mistura sindicatos de
# servidores com "empresa" e autarquias com "sociedade civil")
# ---------------------------------------------------------------------------------------
ENTE_PUBLICO = re.compile(
    r"\b(FUNDACAO OSWALDO CRUZ|EMPRESA BRASILEIRA DE PESQUISA AGROPECUARIA|FUNDACAO UNIVERSIDADE|"
    r"UNIVERSIDADE (FEDERAL|DE BRASILIA|TECNOLOGICA FEDERAL|DA INTEGRACAO)|INSTITUTO FEDERAL|INST FEDERAL|"
    r"CENTRO FEDERAL DE EDUCACAO|INSTITUTO NACIONAL (DA PROPRIEDADE|DE COLONIZACAO|DO SEGURO|DE ESTUDOS E PESQUISAS)|"
    r"INSTITUTO BRASILEIRO DE MUSEUS|SUPERINTENDENCIA (DE SEGUROS|NACIONAL DE PREVIDENCIA|DO DESENVOLVIMENTO)|"
    r"AUTORIDADE NACIONAL|ANSN|COMISSAO NACIONAL DE ENERGIA|FUND COORD DE APERFEICOAMENTO|"
    r"COMPANHIA DE DESENVOLVIMENTO DOS VALES|AGENCIA REGULADORA DE SERVICOS PUBLICOS|INSTITUTO BENJAMIN CONSTANT|"
    r"CONSELHO FEDERAL DE|ANPD|SGTES|MGI|MMA|IBC|ASSESSOR TECNICO|INSTITUTO NACIONAL DE METROLOGIA|"
    r"INSTITUTO BUTANTAN|FUNDACAO EZEQUIEL DIAS|CENTRO NACIONAL DE TECNOLOGIA ELETRONICA AVANCADA|CNPQ|"
    r"CONSELHO NACIONAL (DE SECRETARIAS|DE DESENVOLVIMENTO|DA JUVENTUDE|DE DIRETORES)|CONSELHO REGIONAL|"
    r"CONSELHO CURADOR|AGENCIA (PERNAMBUCANA|BRASILEIRA DE APOIO)|COMPANHIA DE SANEAMENTO AMBIENTAL|"
    r"FRENTE NACIONAL DE PREFEIT\w+|ORGANIZACAO (INTERNACIONAL|MUNDIAL|DAS NACOES)|OMPI|CENAPET|"
    r"FORUM NACIONAL DE EDUCACAO|ASSOCIACAO NACIONAL DOS SECRETARIOS E DIRIGENTES MUNICIPAIS|"
    r"ASSOCIACAO NACIONAL DE MUNICIPIOS|ASSOCIACAO BRASILEIRA DE AGENCIAS REGULADORAS|IF[A-Z]{2,4})\b")
SINDICAL = re.compile(
    r"\b(SIND\w*|ADUF\w*|FASUBRA|CUT|CTB|CSB|NCST|CENTRAL (UNICA )?DOS TRABALHADORES|ASSIBGE|UNACON|ANFFA|AACE|"
    r"ANAFE|ANAUNI|ASDNER|ANASEF|FONACATE|SINTFUB|SINDTTAE|MTST|MAM|MONAPE|FENAJ|MOVIMENTO|SINASEFE|PROIFES|"
    r"ASSECOR|ANMP|UJS|FNL|PERITOS MEDICOS FEDERAIS|DEFENSORES PUBLICOS|DESEMBARGADORES|"
    r"TECNICOS DE FISCALIZACAO FEDERAL|UNIAO DA JUVENTUDE|FRENTE NACIONAL DE LUTA)\b|"
    r"(ASSOCIACAO|UNIAO|FEDERACAO|CONFEDERACAO|FED NAC)\b.*\b(SERVIDORES|TRABALHADORES|TRAB|ANALISTAS|FISCAIS|"
    r"AUDITORES|DOCENTES|PROFESSORES|ADVOGADOS PUBLICOS|ADVOGADOS DA UNIAO|DIPLOMATAS|EMPREGADOS|DIRIGENTES DAS INST)\b|"
    r"\bASSOCIACAO DE MULHERES DIPLOMATAS")
INST_PUBLICAS = re.compile(r"\b(CONIF|CONSELHO NACIONAL DAS INSTITUICOES|CONSAD|CONFEMEL|"
                           r"ASSOC NAC DIRIGENTES DAS INST FED)\b")
ACADEMICA = re.compile(
    r"\b(SOCIEDADE BRASILEIRA|SBPC|ASSOCIACAO BRASILEIRA DE ENSINO|FEDERACAO BRASILEIRA DAS ASSOCIACOES|"
    r"ASSOCIACAO NACIONAL DE PESQUISA|FUNDACAO DE APOIO|FUNDACAO ARTHUR BERNARDES|FIOTEC|FGV|FUNDACAO GETULIO|"
    r"COMITE BRASILEIRO DE BARRAGENS|RNP|UNIVERSIDADE|INSTITUTO DE ENSINO E PESQUISA|INSTITUTO DE BIOLOGIA|"
    r"INSTITUTO TECNOLOGICO|FUNDACAO DE AMPARO|FUNDACAO INSTITUTO|INSTITUTO .* UFV|MATEMATICA PURA)\b")
EMPRESARIAL = {"Empresa", "Associação empresarial", "Advocacia e consultoria"}

CEDIDO = {"CEDIDO/REQUISITADO", "CEDIDO SUS/LEI 8270", "REQ.DE OUTROS ORGAOS", "EXERC. 7 ART93 8112"}
CELETISTA = {"CELETISTA/EMPREGADO", "EMPREGO PUBLICO", "CLT ANS -DEC 6657/08", "EMPREGO PCC/EX-TERRI"}
TEMPORARIO = {"CONT.PROF.SUBSTITUTO", "CONTRATO TEMPORARIO"}
CONSELHEIRO = {"CONSELHEIRO DO CARF", "CONSELHEIRO RPSOCIAL"}
ACAD_CARGO = re.compile(r"PROFESSOR|PESQUISADOR|TECNOLOGISTA|DOCENTE|MAGISTERIO")
CONSELHO_CARGO = re.compile(r"CONSELHEIR|\bCONSELHO\b|SUPLENTE")


def natureza(rotulo: str, entidade: str, tipo: str) -> str:
    t = norm(f"{rotulo or ''} {entidade or ''}")
    if ENTE_PUBLICO.search(t):
        return "ente público"
    if SINDICAL.search(t):
        return "sindical ou classista"
    if INST_PUBLICAS.search(t):
        return "colegiado de instituições públicas"
    if ACADEMICA.search(t) or tipo == "Sociedade civil e academia":
        return "acadêmica ou científica"
    if tipo == "Sindicato e movimento social":
        return "sindical ou classista"
    return {"Empresa": "empresa", "Associação empresarial": "associação empresarial",
            "Advocacia e consultoria": "advocacia e consultoria"}.get(tipo, "outra")


def carrega_cadastro(cpfs: set[str]) -> pl.DataFrame:
    """Cadastros mensais só das pessoas de interesse (mesma chave de porta_giratoria.py)."""
    arqs = sorted((DATA / "servidores").glob("*.parquet"))
    s = pl.concat([pl.read_parquet(a) for a in arqs], how="diagonal_relaxed")
    s = s.filter(pl.col("cpf6").is_in(list(cpfs)))
    s = s.with_columns(pl.col("nome_norm").map_elements(limpa_nome, return_dtype=pl.String))
    s = s.with_columns(
        (pl.col("nome_norm") + "|" + pl.col("cpf6")).alias("sid"),
        pl.struct("SIGLA_FUNCAO", "NIVEL_FUNCAO", "DESCRICAO_CARGO").map_elements(
            lambda r: alto_escalao(r["SIGLA_FUNCAO"], r["NIVEL_FUNCAO"], r["DESCRICAO_CARGO"]),
            return_dtype=pl.Boolean).alias("alto"),
        pl.col("mes").map_elements(mes_int, return_dtype=pl.Int64).alias("mi"))
    return s


def mes_efetivo(mr: int, meses_ok: list[int], meses_set: set[int]) -> int:
    """Mês de cadastro que vale para a reunião (set/2026 ainda não foi publicado)."""
    if mr in meses_set:
        return mr
    antes = [m for m in meses_ok if m < mr]
    return antes[-1] if antes else mr


def regime(situacoes: set[str]) -> str:
    if situacoes & CEDIDO:
        return "cedido ou requisitado"
    if situacoes & CONSELHEIRO:
        return "conselheiro (CARF, Previdência)"
    if situacoes & CELETISTA:
        return "celetista"
    if situacoes & TEMPORARIO:
        return "temporário ou substituto"
    return "estatutário ou comissionado"


def conta(df: pl.DataFrame, col: str, k: int = 15, chave="sid"):
    return [list(x) for x in df.filter(pl.col(col).is_not_null()).group_by(col)
            .agg(pl.col(chave).n_unique().alias("pessoas"), pl.col("id").n_unique().alias("reunioes"))
            .sort(["pessoas", "reunioes"], descending=True).head(k).iter_rows()]


def main():
    pg = pl.read_parquet(DATA / "porta_giratoria.parquet")
    priv = pg.filter(~pl.col("interesse_proprio") & ~pl.col("tipo").is_in(FORA).fill_null(False))
    proprio = pg.filter(pl.col("interesse_proprio"))
    cpfs = set(priv["cpf6"].unique().to_list())
    s = carrega_cadastro(cpfs)
    meses_ok = sorted(s["mi"].unique().to_list())
    meses_set = set(meses_ok)
    print("cadastro", s.height, "linhas;", len(meses_ok), "meses", file=sys.stderr)

    # linhas do cadastro por pessoa e mês
    por_sid_mes = {}
    for r in s.select("sid", "mi", "SITUACAO_VINCULO", "DESCRICAO_CARGO", "ORG_LOTACAO", "ORGSUP_LOTACAO",
                      "ORG_EXERCICIO", "ORGSUP_EXERCICIO", "alto").iter_rows(named=True):
        por_sid_mes.setdefault((r["sid"], r["mi"]), []).append(r)
    meses_sid = {}
    alto_sid = {}
    orgs_alto = {}
    for (sid, mi), rows in por_sid_mes.items():
        meses_sid.setdefault(sid, []).append(mi)
        if any(r["alto"] for r in rows):
            alto_sid.setdefault(sid, []).append(mi)
            for r in rows:
                if r["alto"]:
                    orgs_alto.setdefault(sid, set()).update({(r["ORG_LOTACAO"], r["ORGSUP_LOTACAO"]),
                                                             (r["ORG_EXERCICIO"], r["ORGSUP_EXERCICIO"])})
    for d_ in (meses_sid, alto_sid):
        for k in d_:
            d_[k].sort()

    ordem_rel = ["mesmo órgão", "mesma pasta", "pasta sucessora"]

    def relacao(host_txt, orgs):
        rel = ""
        for org, orgsup in orgs:
            for host in (host_txt or "").split(" ; "):
                x = relacao_orgao(host, org or "", orgsup or "")
                if x and (not rel or ordem_rel.index(x) < ordem_rel.index(rel)):
                    rel = x
        return rel

    # =====================================================================================
    # TIPOLOGIA 3: servidor ativo representando entidade privada
    # =====================================================================================
    ativos = priv.filter(pl.col("situacao") == "ativo")
    linhas3 = []
    for r in ativos.iter_rows(named=True):
        d = r["data"]
        mr = mes_efetivo(d.year * 12 + d.month - 1, meses_ok, meses_set)
        rows = por_sid_mes.get((r["sid"], mr)) or por_sid_mes.get(
            (r["sid"], max([m for m in meses_sid[r["sid"]] if m <= mr], default=mr)), [])
        sit = {x["SITUACAO_VINCULO"] for x in rows if x["SITUACAO_VINCULO"]}
        cargos = " ".join(x["DESCRICAO_CARGO"] or "" for x in rows)
        orgs = {(x["ORG_LOTACAO"], x["ORGSUP_LOTACAO"]) for x in rows} | \
               {(x["ORG_EXERCICIO"], x["ORGSUP_EXERCICIO"]) for x in rows}
        rel = relacao(r["orgaos"] or r["orgao"], orgs)
        nat = natureza(r["rotulo"], r["entidade"], r["tipo"])
        reg = regime(sit)
        # órgão da própria lotação citado como entidade (ex.: servidor da CVM listado como "CVM")
        org_proprio = any(mesmo_nome_orgao(r["rotulo"] or "", o or "") for o, _ in orgs)
        academico = bool(ACAD_CARGO.search(cargos))
        # --- explicações legítimas (derrubam o indício) ---
        if norm(r["rotulo"] or "").startswith("INTERESSE PROPRIO"):
            expl = "interesse próprio declarado na entidade"
        elif reg == "cedido ou requisitado":
            expl = "cedido ou requisitado"
        elif reg.startswith("conselheiro"):
            expl = "conselheiro (CARF, Previdência)"
        elif nat == "sindical ou classista":
            expl = "sindicato, associação de servidores ou central"
        elif nat == "colegiado de instituições públicas" or CONSELHO_CARGO.search(r["cargo_declarado"] or ""):
            expl = "conselho ou colegiado"
        elif nat == "acadêmica ou científica" and academico:
            expl = "professor ou pesquisador em entidade acadêmica ou científica"
        elif nat == "ente público" and rel in ("mesmo órgão", "mesma pasta", "pasta sucessora") or org_proprio:
            expl = "registro provável errado (entidade pública do próprio órgão)"
        elif nat == "ente público":
            expl = "entidade pública classificada como privada"
        else:
            expl = ""
        # --- força do indício (só sem explicação) ---
        if expl:
            forca = "explicada"
        elif nat in ("empresa", "associação empresarial", "advocacia e consultoria"):
            if reg == "estatutário ou comissionado" and rel in ("mesmo órgão", "mesma pasta"):
                forca = "alta"
            else:
                forca = "média"
        elif nat == "acadêmica ou científica" and not academico:
            forca = "baixa"
        elif rel in ("mesmo órgão", "mesma pasta") and reg == "estatutário ou comissionado":
            forca = "média"
        else:
            forca = "baixa"
        linhas3.append({"id": r["id"], "data": r["data"], "sid": r["sid"], "orgao": r["orgao"],
                        "rotulo": r["rotulo"], "natureza": nat, "setor": r["setor"], "tipo_painel": r["tipo"],
                        "cargo_declarado": r["cargo_declarado"], "regime": reg, "cargo_origem": cargos.strip()[:80],
                        "relacao_orgao": rel, "explicacao": expl, "forca": forca})
    t3m = pl.DataFrame(linhas3)
    rank = {"alta": 3, "média": 2, "baixa": 1, "explicada": 0}
    t3m = t3m.with_columns(pl.col("forca").replace_strict(rank, return_dtype=pl.Int64).alias("rk"))
    # pessoa: melhor força entre as reuniões; se só há explicadas, a explicação mais frequente
    pessoa3 = (t3m.sort("rk", descending=True).group_by("sid", maintain_order=True)
               .agg(pl.col("forca").first(), pl.col("rk").first(),
                    pl.col("explicacao").filter(pl.col("explicacao") != "").mode().first().alias("explicacao"),
                    pl.col("regime").first(), pl.col("natureza").first(),
                    pl.col("id").n_unique().alias("reunioes")))
    t3m = t3m.join(pessoa3.select("sid", pl.col("forca").alias("forca_pessoa")), on="sid")

    def serie_forca(df, col, k=12):
        """pessoas por (col, força), usando a força da pessoa; col vem da reunião."""
        out = {}
        for f in ("alta", "média", "baixa", "explicada"):
            sub = df.filter(pl.col("forca_pessoa") == f)
            out[f] = conta(sub, col, k)
        return out

    # órgão e setor: contam pessoas (força da pessoa) que tiveram reunião naquele órgão/setor
    t3_orgao = {f: conta(t3m.filter(pl.col("forca_pessoa") == f), "orgao", 12)
                for f in ("alta", "média", "baixa")}
    t3_setor = {f: conta(t3m.filter(pl.col("forca_pessoa") == f), "setor", 12) for f in ("alta", "média", "baixa")}
    ativos_unsound = t3m.select("sid").n_unique()
    forte = t3m.filter(pl.col("forca") == "alta")

    stats3 = {
        "pessoas_ativas_privadas": pessoa3.height,
        "reunioes": t3m["id"].n_unique(),
        "por_forca": {f: pessoa3.filter(pl.col("forca") == f).height for f in rank},
        "reunioes_por_forca_pessoa": {f: t3m.filter(pl.col("forca_pessoa") == f)["id"].n_unique() for f in rank},
        "explicacoes_pessoas": {k: v for k, v in pessoa3.filter(pl.col("forca") == "explicada")
                                .group_by("explicacao").len().sort("len", descending=True).iter_rows()},
        "por_regime_pessoa": {k: v for k, v in pessoa3.group_by("regime").len().sort("len", descending=True)
                              .iter_rows()},
        "alta_por_natureza": {k: v for k, v in pessoa3.filter(pl.col("forca") == "alta")
                              .group_by("natureza").len().sort("len", descending=True).iter_rows()},
        "alta_pessoas_reunioes_mesmo_orgao": forte.filter(pl.col("relacao_orgao") == "mesmo órgão")["sid"].n_unique(),
        "alta_por_orgao": conta(forte, "orgao", 15),
        "alta_por_setor": conta(forte, "setor", 12),
        "por_orgao_pessoas_por_forca": t3_orgao,
        "por_setor_pessoas_por_forca": t3_setor,
        "alta_cargos_origem": conta(forte, "cargo_origem", 10),
        "explicada_por_orgao": conta(t3m.filter(pl.col("forca_pessoa") == "explicada"), "orgao", 8),
        "checagem_total_pessoas": ativos_unsound,
    }

    # =====================================================================================
    # TIPOLOGIA 4: quarentena de 6 meses (Lei 12.813, art. 6º, II)
    # =====================================================================================
    # Regra: reunião (entidade privada, fora "interesse próprio") em que a pessoa
    #  (a) ocupou, em algum mês do cadastro, cargo de alto escalão (alto_escalao());
    #  (b) NÃO ocupa alto escalão no mês da reunião (mês efetivo do cadastro);
    #  (c) dias entre o fim do último mês com alto escalão e a data da reunião, 0 < dias <= 183;
    #  (d) anfitrião da reunião = órgão onde ocupou o cargo (lotação ou exercício das linhas de alto escalão).
    linhas4 = []
    for r in priv.iter_rows(named=True):
        sid = r["sid"]
        if sid not in alto_sid:
            continue
        d = r["data"]
        mr = d.year * 12 + d.month - 1
        eff = mes_efetivo(mr, meses_ok, meses_set)
        altos = alto_sid[sid]
        if eff in altos:
            continue  # ainda ocupa o cargo: caso de tipologia 3, não de quarentena
        antes = [m for m in altos if m < eff]
        if not antes:
            continue
        saida = fim_do_mes(antes[-1])
        dias = (d - saida).days
        if dias <= 0 or dias > QUARENTENA_DIAS + FOLGA_MES:
            continue
        rel = relacao(r["orgaos"] or r["orgao"], orgs_alto[sid])
        if not rel:
            continue
        no_cadastro = eff in set(meses_sid[sid])
        # cargo no momento da saída
        rows_saida = por_sid_mes[(sid, antes[-1])]
        alto_row = next(x for x in rows_saida if x["alto"])
        linhas4.append({"id": r["id"], "data": d, "sid": sid, "orgao": r["orgao"], "rotulo": r["rotulo"],
                        "tipo_painel": r["tipo"], "setor": r["setor"], "dias_desde_saida_cargo": dias,
                        "relacao_orgao": rel, "continua_no_cadastro": no_cadastro,
                        "cargo_alto": alto_row["DESCRICAO_CARGO"], "orgao_origem": alto_row["ORG_EXERCICIO"]})
    t4m = pl.DataFrame(linhas4) if linhas4 else pl.DataFrame()
    t4m = t4m.with_columns(
        pl.when(pl.col("relacao_orgao") != "mesmo órgão").then(pl.lit("baixa"))
          .when(pl.col("dias_desde_saida_cargo") > QUARENTENA_DIAS).then(pl.lit("fora"))
          .when(pl.col("continua_no_cadastro")).then(pl.lit("média"))
          .when(pl.col("dias_desde_saida_cargo") <= FOLGA_DIAS).then(pl.lit("alta"))
          .otherwise(pl.lit("média")).alias("forca"))
    # "baixa" também precisa estar dentro da janela nominal de 183 dias
    t4m = t4m.with_columns(pl.when((pl.col("forca") == "baixa") & (pl.col("dias_desde_saida_cargo") > QUARENTENA_DIAS))
                           .then(pl.lit("fora")).otherwise(pl.col("forca")).alias("forca"))
    rank4 = {"alta": 3, "média": 2, "baixa": 1, "fora": 0}
    t4m = t4m.with_columns(pl.col("forca").replace_strict(rank4, return_dtype=pl.Int64).alias("rk"))
    dentro = t4m.filter(pl.col("forca") != "fora")
    pessoa4 = (dentro.sort("rk", descending=True).group_by("sid", maintain_order=True)
               .agg(pl.col("forca").first(), pl.col("dias_desde_saida_cargo").min().alias("dias_min"),
                    pl.col("id").n_unique().alias("reunioes"), pl.col("cargo_alto").first(),
                    pl.col("orgao_origem").first(), pl.col("continua_no_cadastro").first()))
    dentro = dentro.join(pessoa4.select("sid", pl.col("forca").alias("forca_pessoa")), on="sid")
    alta4 = dentro.filter(pl.col("forca_pessoa") == "alta")

    def cargo_generico(c):
        c = c or ""
        if re.search(r"MINISTRO|PRESIDENTE DO BANCO|DIRETOR DO BANCO", c):
            return "cúpula (ministro ou diretoria do BC)"
        return "cargo de alto escalão (DAS 5-6, CCE/FCE 1.15+, natureza especial ou diretoria de agência)"

    # sensibilidades (não entram nos números principais)
    n_mesmo_orgao = pessoa4.filter(pl.col("forca").is_in(["alta", "média"])).height
    n_dentro_nominal_mesmo_orgao = (t4m.filter((pl.col("relacao_orgao") == "mesmo órgão")
                                               & (pl.col("dias_desde_saida_cargo") <= QUARENTENA_DIAS))
                                    ["sid"].n_unique())
    estr_prop = []
    for r in proprio.iter_rows(named=True):
        sid = r["sid"]
        if sid not in alto_sid:
            continue
        d = r["data"]
        eff = mes_efetivo(d.year * 12 + d.month - 1, meses_ok, meses_set)
        if eff in alto_sid[sid]:
            continue
        antes = [m for m in alto_sid[sid] if m < eff]
        if antes and 0 < (d - fim_do_mes(antes[-1])).days <= QUARENTENA_DIAS and \
                relacao(r["orgaos"] or r["orgao"], orgs_alto[sid]) == "mesmo órgão":
            estr_prop.append(sid)
    stats4 = {
        "regra": {"quarentena_dias": QUARENTENA_DIAS, "folga_mes_dias": FOLGA_MES, "limite_alta_dias": FOLGA_DIAS},
        "pessoas_com_alto_escalao_no_cadastro_e_reuniao_privada": len(
            {r for r in priv["sid"].unique().to_list() if r in alto_sid}),
        "por_forca": {f: pessoa4.filter(pl.col("forca") == f).height for f in ("alta", "média", "baixa")},
        "reunioes_por_forca_pessoa": {f: dentro.filter(pl.col("forca_pessoa") == f)["id"].n_unique()
                                      for f in ("alta", "média", "baixa")},
        "mesmo_orgao_dentro_de_183_dias_nominal": n_dentro_nominal_mesmo_orgao,
        "mesmo_orgao_alta_mais_media": n_mesmo_orgao,
        "continuam_no_cadastro_mesmo_orgao": int(pessoa4.filter(pl.col("forca") == "média")
                                                 .filter(pl.col("continua_no_cadastro")).height),
        "alta_por_orgao": conta(alta4, "orgao", 15),
        "alta_por_orgao_origem": conta(alta4, "orgao_origem", 15),
        "alta_por_tipo_painel": conta(alta4, "tipo_painel", 8),
        "alta_por_setor": conta(alta4, "setor", 8),
        "alta_dias_min": sorted(pessoa4.filter(pl.col("forca") == "alta")["dias_min"].to_list()),
        "por_cargo_generico": {k: v for k, v in pessoa4.filter(pl.col("forca").is_in(["alta", "média"]))
                               .with_columns(pl.col("cargo_alto").map_elements(cargo_generico, return_dtype=pl.String)
                                             .alias("c")).group_by("c").len().iter_rows()},
        "interesse_proprio_mesmo_orgao_dentro_de_183_dias": len(set(estr_prop)),
        "estimativa_anterior_porta_giratoria_md": 6,
    }

    # =====================================================================================
    casos = pl.concat([
        t3m.select(pl.lit("T3").alias("tipologia"), "id", "data", "sid", "orgao", "rotulo", "forca",
                   pl.col("explicacao").alias("detalhe")),
        dentro.select(pl.lit("T4").alias("tipologia"), "id", "data", "sid", "orgao", "rotulo", "forca",
                      pl.col("dias_desde_saida_cargo").cast(pl.String).alias("detalhe")),
    ])
    casos.write_parquet(DATA / "tipologias_3_4_casos.parquet")
    stats = {"gerado_em": str(date.today()), "tipologia_3": stats3, "tipologia_4": stats4}
    (DATA / "tipologias_3_4_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"t3": {k: v for k, v in stats3.items() if k in ("pessoas_ativas_privadas", "por_forca",
                                                                       "explicacoes_pessoas")},
                      "t4": {k: v for k, v in stats4.items() if k in ("por_forca", "alta_dias_min")}},
                     ensure_ascii=False, default=str), file=sys.stderr)


if __name__ == "__main__":
    main()
