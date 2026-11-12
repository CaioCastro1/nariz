"""Porta giratória: participantes privados do e-Agendas que foram servidores federais.

Casa data/pessoas_privadas.parquet (extract.py) com os cadastros mensais do SIAPE e
do Banco Central em data/servidores/ (servidores.py) pelas DUAS chaves juntas:
nome normalizado (sem pronome de tratamento) + 6 dígitos visíveis do CPF.

Saídas (todas locais, com nomes de pessoas: não publicar):
- data/porta_giratoria.parquet: uma linha por (reunião, pessoa casada), com o
  vínculo federal, situação na data da reunião e dias desde a saída.
- data/porta_giratoria_stats.json: números agregados.

Situação na data da reunião (meses = cadastros mensais carregados):
- "ativo": aparece no cadastro do mês da reunião;
- "ex-servidor": apareceu antes e não aparece mais no mês da reunião;
- "ingressou depois": só aparece em cadastros posteriores à reunião.
A saída é estimada como o último dia do último mês em que a pessoa aparece; o
erro é de até um mês para mais.
"""
import json
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from build import classificacao  # noqa: E402
from classify import overrides  # noqa: E402
from extract import norm  # noqa: E402
from servidores import limpa_nome  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
QUARENTENA_DIAS = 183  # 6 meses, Lei 12.813/2013, art. 6º, II
# tipos de entidade que não contam como representação privada: órgão público,
# registro genérico, organismos internacionais e estatais/paraestatais (empregado
# cedido que volta à estatal não é porta giratória)
FORA = ["Órgão público", "Genérico", "Estatal e paraestatal", "Internacional"]
# estatais que as regras do painel classificam como "Empresa"
ESTATAIS_EXTRA = (r"\b(INDUSTRIAS NUCLEARES|INB|EBSERH|SERVICOS HOSPITALARES|AMAZUL|IMBEL|PRE SAL PETROLEO|"
                  r"PLANEJAMENTO E LOGISTICA|INFRA S ?A|PESQUISA ENERGETICA|CASA DA MOEDA|SERVICO GEOLOGICO|CPRM|"
                  r"EMPRESA GESTORA DE ATIVOS|EMGEA|ELETRONORTE|CHESF|FURNAS|TELEBRAS|NAV BRASIL|BB DTVM|BB ASSET|"
                  r"CAIXA (SEGURADORA|VIDA|ASSET|DTVM)|BNDESPAR)\b")

# Ministérios renomeados ou desmembrados entre 2019 e 2026: o órgão de origem conta
# como "pasta sucessora" do anfitrião, não como mesmo órgão.
SUCESSORES = {
    "ECONOMIA": {"FAZENDA", "PLANEJAMENTO E ORCAMENTO", "GESTAO E INOVACAO EM SERVICOS PUBLICOS",
                 "DESENVOLVIMENTO INDUSTRIA COMERCIO E SERVICOS", "TRABALHO E EMPREGO", "PREVIDENCIA SOCIAL",
                 "EMPREENDEDORISMO DA MICROEMPRESA E DA EMPRESA DE PEQUENO PORTE"},
    "INFRAESTRUTURA": {"TRANSPORTES", "PORTOS E AEROPORTOS"},
    "CIENCIA TECNOLOGIA INOVACOES E COMUNICACOES": {"CIENCIA TECNOLOGIA E INOVACAO", "COMUNICACOES"},
    "CIENCIA TECNOLOGIA E INOVACOES": {"CIENCIA TECNOLOGIA E INOVACAO"},
    "DESENVOLVIMENTO REGIONAL": {"INTEGRACAO E DO DESENVOLVIMENTO REGIONAL", "CIDADES"},
    "AGRICULTURA PECUARIA E ABASTECIMENTO": {"AGRICULTURA E PECUARIA", "DESENVOLVIMENTO AGRARIO E AGRICULTURA FAMILIAR",
                                             "PESCA E AQUICULTURA"},
    "MULHER DA FAMILIA E DOS DIREITOS HUMANOS": {"DIREITOS HUMANOS E DA CIDADANIA", "MULHERES"},
    "CIDADANIA": {"DESENVOLVIMENTO E ASSISTENCIA SOCIAL FAMILIA E COMBATE A FOME", "ESPORTE", "CULTURA"},
    "TURISMO": {"TURISMO"},
}
# Regras extras de setor, só para este relatório: a cauda de entidades pequenas que
# as regras do painel (classify.SETORES) deixam como "Não classificado".
SETORES_EXTRA = [
    ("Bancos e mercado financeiro", r"\b(TITULOS|VALORES MOBILIARIOS|CREDITO|FINANC\w*|FINANCE|EXCHANGE|CAMBIO|BINANCE|"
                                    r"CRIPTO|FINTECH|SICREDI|SICOOB|NU|QI TECH|ATIVOS|SEGURADORA|DPVAT|PREVIDENCIA|CAPITALIZACAO|"
                                    r"PARTICIPACOES SOCIETARIAS)\b"),
    ("Óleo, gás e combustíveis", r"\b(ENERGY|PRIO|ULTRAPAR|ULTRACARGO|LUBRIFICANTES|DISTRIBUIDORAS? DE COMBUST)\b"),
    ("Energia elétrica", r"\b(EVOLTZ|ENERG\w*)\b"),
    ("Saneamento", r"\b(ABCON|SINDCON|SANEAMENTO|AGUAS?|ESGOTO)\b"),
    ("Saúde e farmacêutico", r"\b(GENERICOS|MEDICAMENTOS?|CLINICA|ODONTO|DIAGNOSTIC)\b"),
    ("Agro e alimentos", r"\b(PESCADOS?|PROTEINA|CARNES?|FRIGORIFIC|LEITE|LATICINIO|GRAOS|TABACO)\b"),
    ("Mineração e siderurgia", r"\b(ALUMIN\w*|ALUNORTE|PARANAPANEMA|METAL\w*|MINERI\w*|COBRE|OURO)\b"),
    ("Rodovias, ferrovias e portos", r"\b(TERMINAL|NAVEGACAO|TRANSPORT\w*|CARGAS?)\b"),
    ("Telecom e radiodifusão", r"\b(GHZ|FAIXA|RADIO|TV)\b"),
    ("Construção e imobiliário", r"\b(CONSTRU\w*|IMOBILIARI\w*|EMPREENDIMENTOS|ENGENHARIA|INCORPORA\w*)\b"),
]


def setor_extra(nome: str, setor: str) -> str:
    if setor != "Não classificado" or not nome:
        return setor
    n = norm(nome)
    return next((st for st, rx in SETORES_EXTRA if re.search(rx, n)), setor)


STOP = {"DE", "DA", "DO", "DOS", "DAS", "E", "EM", "A", "O"}


def tokens(org: str):
    o = norm(org or "")
    o = re.sub(r"^MIN(ISTERIO)?\b", "MINISTERIO", o)
    return [t for t in o.split() if t not in STOP]


def mesmo_nome_orgao(a: str, b: str) -> bool:
    """Compara nomes de órgão tolerando as abreviações do SIAPE
    ("MIN GESTAO E INOV EM SERV PUBLICOS" = "Ministério da Gestão e da Inovação em Serviços Públicos")."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb or len(ta) != len(tb):
        return False
    return all(x.startswith(y) or y.startswith(x) for x, y in zip(ta, tb))


def pasta(org: str) -> str:
    t = tokens(org)
    return " ".join(t[1:]) if t and t[0] == "MINISTERIO" else ""


def relacao_orgao(anfitriao: str, org: str, orgsup: str) -> str:
    if mesmo_nome_orgao(anfitriao, org):
        return "mesmo órgão"
    if mesmo_nome_orgao(anfitriao, orgsup):
        return "mesma pasta"
    pa, po = pasta(anfitriao), pasta(orgsup) or pasta(org)
    if pa and po:
        expande = lambda p: next((k for k in SUCESSORES if mesmo_nome_orgao("M " + k, "M " + p)), p)  # noqa: E731
        ka, ko = expande(pa), expande(po)
        if any(mesmo_nome_orgao("M " + s, "M " + pa) for s in SUCESSORES.get(ko, ())) or \
           any(mesmo_nome_orgao("M " + s, "M " + po) for s in SUCESSORES.get(ka, ())):
            return "pasta sucessora"
    return ""


def alto_escalao(sigla: str, nivel: str, cargo: str = "") -> bool:
    """DAS 5 ou superior e equivalentes (Lei 12.813/2013, art. 2º; Lei 14.204/2021):
    DAS 101/102 níveis 5-6, CCE/FCE ("CCX"/"FEX" no SIAPE) nível 1.15 ou mais,
    natureza especial e cargo de direção de agência reguladora (CCD)."""
    sigla, nivel = (sigla or "").strip(), (nivel or "").strip()
    if re.search(r"^(MINISTRO DE ESTADO|PRESIDENTE DO BANCO CENTRAL|DIRETOR DO BANCO CENTRAL)", cargo or ""):
        return True
    if sigla == "DAS":
        return nivel[-1:] in {"5", "6"}
    if sigla in {"CCX", "FEX", "CCE", "FCE"} and nivel.isdigit():
        return int(nivel[-2:]) >= 15 and nivel.startswith("01")
    return sigla in {"NE", "NES", "GNE", "CCD"}


def carrega_servidores():
    arqs = sorted((DATA / "servidores").glob("*.parquet"))
    s = pl.concat([pl.read_parquet(a) for a in arqs], how="diagonal_relaxed")
    s = s.filter(pl.col("cpf6").is_not_null()).with_columns(
        pl.col("nome_norm").map_elements(limpa_nome, return_dtype=pl.String),
        (pl.col("fonte").fill_null("SIAPE") + ":" + pl.col("Id_SERVIDOR_PORTAL")).alias("id_portal"),
        pl.struct("SIGLA_FUNCAO", "NIVEL_FUNCAO", "DESCRICAO_CARGO").map_elements(
            lambda r: alto_escalao(r["SIGLA_FUNCAO"], r["NIVEL_FUNCAO"], r["DESCRICAO_CARGO"]),
            return_dtype=pl.Boolean).alias("alto"),
    )
    # a pessoa é a chave (nome, cpf6): junta vínculos diferentes (SIAPE -> BACEN,
    # reingresso com outro Id) numa só linha do tempo
    return s.with_columns((pl.col("nome_norm") + "|" + pl.col("cpf6")).alias("sid"))


def abreviado(curto: str, longo: str) -> bool:
    """curto é o nome longo sem alguns nomes do meio (mesmo primeiro e último nome)."""
    c, lg = curto.split(), longo.split()
    if len(c) < 2 or len(c) >= len(lg) or c[0] != lg[0] or c[-1] != lg[-1]:
        return False
    it = iter(lg)
    return all(t in it for t in c)


def mes_int(m: str) -> int:
    return int(m[:4]) * 12 + int(m[4:]) - 1


def fim_do_mes(mi: int) -> date:
    y, m = divmod(mi + 1, 12)
    return date(y, m + 1, 1) - timedelta(days=1)


def rotulo_mes(mi: int) -> str:
    return f"{mi // 12}-{mi % 12 + 1:02d}"


def main():
    p = pl.read_parquet(DATA / "pessoas_privadas.parquet").with_columns(
        pl.col("pessoa_norm").map_elements(limpa_nome, return_dtype=pl.String))
    s = carrega_servidores()
    meses_ok = sorted({mes_int(m) for m in s["mes"].unique()})
    meses_set = set(meses_ok)
    print("cadastros carregados", len(meses_ok), "linhas", s.height, file=sys.stderr)

    # entidade -> id resolvido, tipo e setor (mesma lógica do painel)
    ent = pl.read_parquet(DATA / "entidades.parquet")
    cls = classificacao(ent, overrides())
    p = p.with_columns(
        pl.when(pl.col("cnpj") != "").then("CNPJ:" + pl.col("cnpj").str.slice(0, 8))
          .otherwise("NOME:" + pl.col("entidade").map_elements(norm, return_dtype=pl.String)).alias("chave"),
    ).join(ent.select("chave", "id_ent"), on="chave", how="left").join(cls, on="id_ent", how="left")
    p = p.with_columns(pl.when(pl.col("rotulo").fill_null("").map_elements(norm, return_dtype=pl.String)
                               .str.contains(ESTATAIS_EXTRA)).then(pl.lit("Estatal e paraestatal"))
                         .otherwise(pl.col("tipo")).alias("tipo"))
    p = p.with_columns(pl.struct("rotulo", "setor").map_elements(
        lambda r: setor_extra(r["rotulo"], r["setor"]), return_dtype=pl.String).alias("setor"))
    p = p.with_columns(
        pl.col("entidade").map_elements(norm, return_dtype=pl.String).is_in(["INTERESSE PROPRIO", "ND"])
          .alias("interesse_proprio"))

    com_cpf = p.filter(pl.col("cpf6") != "")
    pessoas = com_cpf.select("pessoa_norm", "cpf6").unique()

    # --- casamento pelas duas chaves -------------------------------------------------
    serv_ids = s.select("nome_norm", "cpf6", "sid").unique()
    casado = (pessoas.join(serv_ids, left_on=["pessoa_norm", "cpf6"], right_on=["nome_norm", "cpf6"])
                     .with_columns(pl.lit("exato").alias("casamento")))
    # segundo nível: nome abreviado na agenda ("PABLO RENTERIA") contido, na mesma
    # ordem, no nome completo do cadastro ("PABLO WALDEMAR RENTERIA"), com o mesmo
    # primeiro e último nome e o mesmo cpf6. Só entra se o candidato for único.
    resto = pessoas.join(casado.select("pessoa_norm", "cpf6"), on=["pessoa_norm", "cpf6"], how="anti")
    cand = resto.join(serv_ids, on="cpf6").filter(pl.struct("pessoa_norm", "nome_norm").map_elements(
        lambda r: abreviado(r["pessoa_norm"], r["nome_norm"]), return_dtype=pl.Boolean))
    cand = cand.filter(pl.col("sid").n_unique().over("pessoa_norm", "cpf6") == 1).select("pessoa_norm", "cpf6", "sid").unique()
    casado = pl.concat([casado, cand.with_columns(pl.lit("abreviado").alias("casamento"))])

    # --- taxa de colisão / falso positivo --------------------------------------------
    # (a) dentro do cadastro: chaves (nome, cpf6) que apontam para 2+ servidores
    chave_multi = (s.select("nome_norm", "cpf6", "id_portal").unique()
                    .group_by("nome_norm", "cpf6").agg(pl.col("id_portal").n_unique().alias("n")))
    colisao_cadastro = chave_multi.filter(pl.col("n") > 1).height / chave_multi.height
    # (b) acaso: mesmo nome, CPF diferente. Para cada nome em comum, embaralha os cpf6
    # dos servidores (preservando o 9º dígito, que indica a região fiscal) e conta
    # quantos "casamentos" surgem. Média de 20 rodadas = falsos positivos esperados.
    nomes_comuns = pessoas.join(serv_ids.select("nome_norm", "cpf6").unique(),
                                left_on="pessoa_norm", right_on="nome_norm", suffix="_s")
    pares_nome = nomes_comuns.height
    pares_nome_cpf_dif = nomes_comuns.filter(pl.col("cpf6") != pl.col("cpf6_s")).height
    todos_cpf = s["cpf6"].unique().to_list()
    por_regiao = {}
    for c in todos_cpf:
        por_regiao.setdefault(c[-1], []).append(c)
    rng = random.Random(42)
    alvo = {(n, c) for n, c in pessoas.iter_rows()}
    nomes_serv = serv_ids.filter(pl.col("nome_norm").is_in(pessoas["pessoa_norm"].unique().implode()))
    simul = []
    for _ in range(20):
        hits = 0
        for n, c in nomes_serv.select("nome_norm", "cpf6").unique().iter_rows():
            falso = rng.choice(por_regiao[c[-1]])
            hits += (n, falso) in alvo
        simul.append(hits)
    fp_esperado = sum(simul) / len(simul)
    # mesmo teste para o nível "abreviado": servidores com o mesmo primeiro e último
    # nome de algum participante, cpf6 sorteado na mesma região fiscal
    pu = lambda n: (n.split()[0], n.split()[-1]) if n and len(n.split()) > 1 else None  # noqa: E731
    alvo_ab = {}
    for n, c in pessoas.iter_rows():
        if pu(n):
            alvo_ab.setdefault((pu(n), c), []).append(n)
    chaves_pu = {k for k, _ in alvo_ab}
    serv_pu = [(n, c, pu(n)) for n, c in serv_ids.select("nome_norm", "cpf6").unique().iter_rows()
               if pu(n) and pu(n) in chaves_pu]
    simul_ab = []
    for _ in range(10):
        hits = set()
        for n, c, k in serv_pu:
            falso = rng.choice(por_regiao[c[-1]])
            hits.update((e, falso) for e in alvo_ab.get((k, falso), ()) if abreviado(e, n))
        simul_ab.append(len(hits))
    # (c) mesmo cpf6, nome diferente: indica quanto se perde por grafia (nome de
    # casada, abreviação), não entra no casamento
    so_cpf = pessoas.join(serv_ids.select("nome_norm", "cpf6").unique(), on="cpf6")
    so_cpf = so_cpf.filter(pl.col("pessoa_norm") != pl.col("nome_norm"))
    primeiro_ultimo = lambda n: (n.split()[0], n.split()[-1]) if n else ("", "")  # noqa: E731
    quase = so_cpf.filter(pl.struct("pessoa_norm", "nome_norm").map_elements(
        lambda r: primeiro_ultimo(r["pessoa_norm"]) == primeiro_ultimo(r["nome_norm"]), return_dtype=pl.Boolean))

    # --- linha do tempo de cada servidor casado --------------------------------------
    s_c = s.join(casado.select("sid").unique(), on="sid").with_columns(
        pl.col("mes").map_elements(mes_int, return_dtype=pl.Int64).alias("mi"))
    presenca = s_c.group_by("sid").agg(pl.col("mi").unique().sort().alias("meses"),
                                       pl.col("alto").any().alias("alto_escalao_algum_dia"))
    pres = {sid: (ms, alto) for sid, ms, alto in presenca.iter_rows()}
    # vínculo no último mês visto: cargo efetivo da linha de cargo, função da linha
    # de função (o SIAPE traz uma linha para cada)
    valido = lambda c: pl.col(c).is_not_null() & ~pl.col(c).is_in(["Sem informaç", "Sem informação", "Inválido", "-1"])  # noqa: E731
    u = s_c.filter(pl.col("mi") == pl.col("mi").max().over("sid"))
    ult = u.group_by("sid").agg(
        pl.col("mi").first().alias("mi_ultimo"),
        pl.col("fonte").first(),
        pl.col("DESCRICAO_CARGO").filter(valido("DESCRICAO_CARGO")).first(),
        pl.col("SIGLA_FUNCAO").filter(valido("SIGLA_FUNCAO")).first(),
        pl.col("NIVEL_FUNCAO").filter(valido("SIGLA_FUNCAO")).first(),
        pl.col("FUNCAO").filter(valido("SIGLA_FUNCAO")).first(),
        *[pl.col(c).sort_by(valido("SIGLA_FUNCAO"), descending=True).first()
          for c in ("ORG_LOTACAO", "ORGSUP_LOTACAO", "ORG_EXERCICIO", "ORGSUP_EXERCICIO", "SITUACAO_VINCULO")],
    )
    # último cargo de alto escalão ocupado (a quarentena conta da saída do cargo,
    # não da saída do serviço público)
    alto_f = (s_c.filter(pl.col("alto")).sort("mi").group_by("sid").agg(
        pl.col("SIGLA_FUNCAO").last().alias("alto_sigla"), pl.col("NIVEL_FUNCAO").last().alias("alto_nivel"),
        pl.col("DESCRICAO_CARGO").last().alias("alto_cargo"), pl.col("ORG_EXERCICIO").last().alias("alto_orgao"),
        pl.col("mi").max().alias("alto_mi")))
    ult = ult.join(alto_f, on="sid", how="left")
    # órgãos em que a pessoa esteve (qualquer mês), para medir "mesmo órgão"
    orgs = s_c.select("sid", "ORG_LOTACAO", "ORGSUP_LOTACAO", "ORG_EXERCICIO", "ORGSUP_EXERCICIO").unique()
    orgs_por_sid = {}
    for sid, ol, osl, oe, ose in orgs.iter_rows():
        orgs_por_sid.setdefault(sid, set()).update({(ol, osl), (oe, ose)})

    alto_mi = dict(alto_f.select("sid", "alto_mi").iter_rows())
    reun = com_cpf.join(casado, on=["pessoa_norm", "cpf6"])
    rows = []
    for r in reun.iter_rows(named=True):
        ms, alto = pres[r["sid"]]
        d = r["data"]
        mr = d.year * 12 + d.month - 1
        antes = [m for m in ms if m < mr]
        if mr in ms or (mr not in meses_set and antes and antes[-1] == max(m for m in meses_ok if m < mr)):
            sit, dias = "ativo", None
        elif antes:
            sit = "ex-servidor"
            dias = (d - fim_do_mes(antes[-1])).days
        else:
            sit, dias = "ingressou depois", None
        am = alto_mi.get(r["sid"])
        dias_alto = (d - fim_do_mes(am)).days if am is not None and am < mr and sit == "ex-servidor" else None
        rel = ""
        for org, orgsup in orgs_por_sid[r["sid"]]:
            for host in (r["orgaos"] or r["orgao"] or "").split(" ; "):
                x = relacao_orgao(host, org, orgsup)
                if x and (not rel or ["mesmo órgão", "mesma pasta", "pasta sucessora"].index(x)
                          < ["mesmo órgão", "mesma pasta", "pasta sucessora"].index(rel)):
                    rel = x
        rows.append({**{k: r[k] for k in ("id", "data", "orgao", "orgaos", "pessoa", "pessoa_norm", "cpf6",
                                          "cargo_declarado", "entidade", "cnpj", "id_ent", "rotulo", "tipo",
                                          "setor", "interesse_proprio", "sid", "casamento")},
                     "situacao": sit, "dias_desde_saida": dias, "dias_desde_alto_escalao": dias_alto, "relacao_orgao": rel,
                     "alto_escalao_algum_dia": alto,
                     "ultimo_mes_cadastro": rotulo_mes(ms[-1]), "primeiro_mes_cadastro": rotulo_mes(ms[0])})
    out = pl.DataFrame(rows).join(ult, on="sid", how="left")
    out.write_parquet(DATA / "porta_giratoria.parquet")

    # --- números para o relatório ------------------------------------------------------
    priv = out.filter(~pl.col("interesse_proprio") & ~pl.col("tipo").is_in(FORA).fill_null(False))
    ex = priv.filter(pl.col("situacao") == "ex-servidor")
    # pessoa casada = pessoa do cadastro (sid): a mesma pessoa pode aparecer na agenda
    # com duas grafias ("JOAO P NASCIMENTO" e "JOAO PEDRO BARROSO DO NASCIMENTO")
    pessoa_k = ["sid"]
    pp = com_cpf.filter(~pl.col("interesse_proprio") & ~pl.col("tipo").is_in(FORA).fill_null(False))

    def n_p(df):
        return df.select(pessoa_k if "sid" in df.columns else ["pessoa_norm", "cpf6"]).n_unique()

    # por pessoa: primeira reunião como ex-servidor e menor intervalo
    ex_p = ex.group_by(pessoa_k).agg(
        pl.col("dias_desde_saida").min().alias("dias_min"),
        pl.col("relacao_orgao").is_in(["mesmo órgão"]).any().alias("mesmo_orgao"),
        pl.col("relacao_orgao").is_in(["mesmo órgão", "mesma pasta"]).any().alias("mesmo_ou_pasta"),
        pl.col("relacao_orgao").is_in(["mesmo órgão", "mesma pasta", "pasta sucessora"]).any().alias("qualquer"),
        pl.col("alto_escalao_algum_dia").any().alias("alto"),
        pl.col("id").n_unique().alias("reunioes"),
    )
    mesmo = ex.filter(pl.col("relacao_orgao") == "mesmo órgão")
    quar = mesmo.filter(pl.col("dias_desde_alto_escalao") <= QUARENTENA_DIAS)
    mesmo_p = mesmo.group_by(pessoa_k).agg(pl.col("dias_desde_saida").min().alias("dias_min"),
                                           pl.col("alto_escalao_algum_dia").any().alias("alto"))

    def faixas(df, col="dias_min"):
        v = df[col].drop_nulls()
        return {"n": len(v), "ate_6m": int((v <= QUARENTENA_DIAS).sum()),
                "6m_1a": int(((v > QUARENTENA_DIAS) & (v <= 365)).sum()),
                "1a_2a": int(((v > 365) & (v <= 730)).sum()), "mais_2a": int((v > 730).sum()),
                "mediana_dias": float(v.median()) if len(v) else None}

    def top(df, col, k=15):
        return [list(x) for x in df.filter(pl.col(col).is_not_null()).group_by(col)
                .agg(pl.struct(pessoa_k).n_unique().alias("pessoas"), pl.col("id").n_unique().alias("reunioes"))
                .sort(["pessoas", "reunioes"], descending=True).head(k).iter_rows()]

    stats = {
        "cadastros": {"meses": len(meses_ok), "de": min(s["mes"]), "ate": max(s["mes"]),
                      "fontes": sorted(s["fonte"].fill_null("SIAPE").unique().to_list())},
        "eagendas": {"linhas_pessoa": p.height, "linhas_com_cpf": com_cpf.height,
                     "pessoas_com_cpf": n_p(com_cpf), "pessoas_privadas_com_cpf": n_p(pp),
                     "periodo_com_cpf": [str(com_cpf["data"].min()), str(com_cpf["data"].max())],
                     "pct_cpf_por_ano": {str(a): round(v, 3) for a, v in p.group_by(pl.col("data").dt.year())
                                         .agg((pl.col("cpf6") != "").mean()).iter_rows()}},
        "colisao": {"chaves_cadastro": chave_multi.height,
                    "taxa_colisao_cadastro": colisao_cadastro,
                    "pares_mesmo_nome": pares_nome, "pares_mesmo_nome_cpf_diferente": pares_nome_cpf_dif,
                    "fp_esperado_por_acaso": fp_esperado, "simulacoes": simul,
                    "fp_esperado_abreviado": sum(simul_ab) / len(simul_ab), "simulacoes_abreviado": simul_ab,
                    "pessoas_casadas": casado.select(pessoa_k).n_unique(),
                    "pessoas_casadas_por_nivel": dict(casado.group_by("casamento").len().iter_rows()),
                    "mesmo_cpf6_nome_diferente": so_cpf.height,
                    "mesmo_cpf6_mesmo_primeiro_e_ultimo_nome": quase.height},
        "resultado": {
            "pessoas_casadas_privadas": n_p(priv),
            "pessoas_casadas_privadas_so_exato": n_p(priv.filter(pl.col("casamento") == "exato")),
            "ex_servidores_so_exato": ex.filter(pl.col("casamento") == "exato").select(pessoa_k).n_unique(),
            "por_situacao": {k: v for k, v in priv.group_by("situacao").agg(pl.struct(pessoa_k).n_unique())
                             .iter_rows()},
            "ex_servidores": ex_p.height,
            "ex_alto_escalao": int(ex_p["alto"].sum()),
            "ex_mesmo_orgao": int(ex_p["mesmo_orgao"].sum()),
            "ex_mesmo_orgao_ou_pasta": int(ex_p["mesmo_ou_pasta"].sum()),
            "ex_mesmo_orgao_pasta_ou_sucessora": int(ex_p["qualquer"].sum()),
            "reunioes_ex": ex["id"].n_unique(),
            "reunioes_ex_mesmo_orgao": mesmo["id"].n_unique(),
            "tempo_ex_qualquer_orgao": faixas(ex_p),
            "tempo_ex_mesmo_orgao": faixas(mesmo_p),
            "tempo_ex_mesmo_orgao_alto": faixas(mesmo_p.filter(pl.col("alto"))),
            "alto_mesmo_orgao_ate_6m_do_cargo": {"pessoas": quar.select(pessoa_k).n_unique(),
                                                  "reunioes": quar["id"].n_unique()},
            "ingressou_depois": priv.filter(pl.col("situacao") == "ingressou depois").select(pessoa_k).n_unique(),
            "top_setores_ex": top(ex, "setor"),
            "top_tipos_ex": top(ex, "tipo"),
            "top_setores_mesmo_orgao": top(mesmo, "setor"),
            "top_anfitrioes_mesmo_orgao": top(mesmo, "orgao"),
            "top_cargos_origem_ex": top(ex, "DESCRICAO_CARGO"),
        },
    }
    (DATA / "porta_giratoria_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(stats["colisao"], ensure_ascii=False, default=str), file=sys.stderr)
    print(json.dumps({k: v for k, v in stats["resultado"].items() if not k.startswith("top")},
                     ensure_ascii=False, default=str), file=sys.stderr)


if __name__ == "__main__":
    main()
