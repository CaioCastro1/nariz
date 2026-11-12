"""Agrega as tabelas resolvidas em data/painel.json para o painel.

Unidade de contagem: reunião distinta (ID do registro). Uma reunião com
anfitriões de dois órgãos conta uma vez para cada órgão.
"""
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from classify import FORA_DO_PRIVADO, overrides, por_regra, setor_por_regra  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
N_ENT = 400

SIGLAS = {
    "Agência Nacional de Transportes Terrestres": "ANTT", "Agência Nacional de Energia Elétrica": "Aneel",
    "Agência Nacional do Petróleo, Gás Natural e Biocombustíveis": "ANP", "Agência Nacional de Vigilância Sanitária": "Anvisa",
    "Agência Nacional de Aviação Civil": "Anac", "Agência Nacional de Telecomunicações": "Anatel",
    "Comissão de Valores Mobiliários": "CVM", "Departamento Nacional de Infraestrutura de Transportes": "DNIT",
    "Banco Central do Brasil": "Banco Central", "Conselho Administrativo de Defesa Econômica": "Cade",
    "Instituto Brasileiro do Meio Ambiente e dos Recursos Naturais Renováveis": "Ibama",
    "Agência Nacional de Saúde Suplementar": "ANS", "Agência Nacional de Transportes Aquaviários": "Antaq",
    "Agência Nacional de Mineração": "ANM", "Controladoria-Geral da União": "CGU",
    "Superintendência de Seguros Privados": "Susep", "Agência Nacional de Águas e Saneamento Básico": "ANA",
    "Agência Nacional do Cinema": "Ancine", "Superintendência Nacional de Previdência Complementar": "Previc",
    "Autoridade Nacional de Proteção de Dados": "ANPD", "Agência Nacional de Proteção de Dados": "ANPD",
    "Empresa Brasileira de Correios e Telégrafos": "Correios", "Instituto Nacional da Propriedade Industrial": "INPI",
    "Ministério do Desenvolvimento, Indústria, Comércio e Serviços": "MDIC", "Ministério da Fazenda": "Fazenda",
    "Ministério de Minas e Energia": "Minas e Energia", "Ministério dos Transportes": "Transportes",
    "Ministério do Trabalho e Emprego": "Trabalho", "Ministério da Agricultura e Pecuária": "Agricultura",
    "Casa Civil da Presidência da República": "Casa Civil",
    "Ministério da Gestão e da Inovação em Serviços Públicos": "Gestão e Inovação", "Ministério da Saúde": "Saúde",
    "Ministério de Portos e Aeroportos": "Portos e Aeroportos", "Ministério do Meio Ambiente": "Meio Ambiente",
    "Secretaria de Comunicação Social da Presidência da República": "Secom",
    "Ministério das Comunicações": "Comunicações", "Ministério da Educação": "Educação",
    "Ministério das Relações Exteriores": "Itamaraty", "Ministério dos Direitos Humanos e da Cidadania": "Direitos Humanos",
    "Secretaria-Geral da Presidência da República": "Secretaria-Geral", "Ministério do Esporte": "Esporte",
    "Ministério da Ciência, Tecnologia e Inovação": "Ciência e Tecnologia",
    "Secretaria de Relações Institucionais da Presidência da República": "SRI",
    "Ministério do Desenvolvimento Agrário e Agricultura Familiar": "Desenv. Agrário", "Ministério da Cultura": "Cultura",
    "Ministério da Integração e do Desenvolvimento Regional": "Integração", "Ministério das Cidades": "Cidades",
    "Ministério do Desenvolvimento e Assistência Social, Família e Combate à Fome": "Desenv. Social",
    "Ministério do Turismo": "Turismo", "Ministério da Defesa": "Defesa", "Ministério da Justiça e Segurança Pública": "Justiça",
    "Ministério do Planejamento e Orçamento": "Planejamento", "Presidência da República": "Presidência",
    "Vice-Presidência da República": "Vice-Presidência", "Ministério da Previdência Social": "Previdência",
    "Ministério do Empreendedorismo, da Microempresa e da Empresa de Pequeno Porte": "Empreendedorismo",
    "Superintendência da Zona Franca de Manaus": "Suframa", "Gabinete de Segurança Institucional da Presidência da República": "GSI",
    "Ministério da Pesca e Aquicultura": "Pesca", "Ministério da Economia": "Economia (gov. anterior)",
    "Ministério da Agricultura, Pecuária e Abastecimento": "Agricultura (gov. anterior)",
    "Ministério da Infraestrutura": "Infraestrutura (gov. anterior)", "Ministério da Igualdade Racial": "Igualdade Racial",
    "Ministério dos Povos Indígenas": "Povos Indígenas", "Ministério das Mulheres": "Mulheres",
    "Fundo Nacional de Desenvolvimento da Educação": "FNDE", "Polícia Federal": "PF", "Instituto do Patrimônio Histórico e Artístico Nacional": "Iphan",
    "Empresa Brasileira de Hemoderivados e Biotecnologia": "Hemobrás", "Instituto Nacional do Seguro Social": "INSS",
    "Companhia de Desenvolvimento dos Vales do São Francisco e do Parnaíba": "Codevasf",
    "Instituto Nacional de Colonização e Reforma Agrária": "Incra", "Companhia Nacional de Abastecimento": "Conab",
}

REGULADORES = re.compile(r"^(Agência Nacional|Autoridade Nacional de Proteção|Comissão de Valores|Banco Central|Conselho Administrativo de Defesa|Superintendência de Seguros|Superintendência Nacional de Previdência)")
UNIVERSIDADES = re.compile(r"(Universidade|Instituto Federal|Centro Federal de Educação|Colégio Pedro II)")
MINISTERIOS = re.compile(r"^(Ministério|Casa Civil|Secretaria-Geral da Presid|Secretaria de (Relações Institucionais|Comunicação Social|Governo) da Presid|Gabinete de Segurança Institucional|Presidência da República|Vice-Presidência|Secretaria Extraordinária da Presid)")
GRUPOS = ["Ministérios e Presidência", "Agências reguladoras", "Outros órgãos", "Universidades e institutos"]


def grupo_orgao(o: str) -> str:
    if MINISTERIOS.search(o):
        return GRUPOS[0]
    if REGULADORES.search(o):
        return GRUPOS[1]
    if UNIVERSIDADES.search(o):
        return GRUPOS[3]
    return GRUPOS[2]


def limpa_rotulo(s: str) -> str:
    s = html.unescape(s).strip(" .-–")
    if s.isupper() and len(s) > 6:
        s = s.title()
    return s


def classificacao(ent, ov):
    """Rótulo, tipo e setor por entidade resolvida (id_ent)."""
    lab = (ent.sort("n", descending=True).unique("id_ent", keep="first")
              .select("id_ent", pl.col("nome").alias("nome_top")))
    def classif(id_ent, nome):
        o = ov.get(id_ent, {})
        tipo = (o.get("tipo") or "").strip() or por_regra(nome)
        setor = (o.get("setor") or "").strip() or setor_por_regra(nome, tipo)
        if tipo in FORA_DO_PRIVADO and not (o.get("setor") or "").strip():
            setor = "Imprensa e comunicação" if tipo == "Imprensa" else "—"
        rot = (o.get("rotulo") or "").strip() or limpa_rotulo(nome)
        return tipo, setor, rot
    rows = [(i, *classif(i, n)) for i, n in lab.iter_rows()]
    return pl.DataFrame(rows, schema=["id_ent", "tipo", "setor", "rotulo"], orient="row")


def main():
    r = pl.read_parquet(DATA / "reunioes.parquet").with_columns(pl.col("data").dt.year().alias("ano"))
    pr = pl.read_parquet(DATA / "participacoes_resolvidas.parquet")
    ent = pl.read_parquet(DATA / "entidades.parquet")
    ov = overrides()

    cls = classificacao(ent, ov)

    pr = pr.join(cls, on="id_ent")
    privado = pr.filter(~pl.col("tipo").is_in(list(FORA_DO_PRIVADO) + ["Órgão público", "Genérico"]))

    hosts = r.select("id", "orgao", "ano", "autoridade", "cargo").with_columns(
        pl.col("orgao").map_elements(grupo_orgao, return_dtype=pl.String).alias("grupo"))
    m_org = hosts.unique(["id", "orgao"]).select("id", "orgao", "grupo", "ano")

    # top entidades (todo o período, todos os órgãos), sem órgãos públicos nem genéricos
    tot = privado.group_by("id_ent").agg(pl.col("id").n_unique().alias("total")).sort("total", descending=True)
    top_ids = tot.head(N_ENT)["id_ent"].to_list()
    idx = {k: i for i, k in enumerate(top_ids)}

    orgaos = (m_org.group_by("orgao", "grupo").agg(pl.col("id").n_unique().alias("reunioes_total")))
    priv_ids = privado.select("id").unique()
    org_priv = m_org.join(priv_ids, on="id").group_by("orgao").agg(pl.col("id").n_unique().alias("reunioes_privadas"))
    orgaos = orgaos.join(org_priv, on="orgao", how="left").fill_null(0).sort("reunioes_privadas", descending=True)
    org_list = orgaos.to_dicts()
    oidx = {o["orgao"]: i for i, o in enumerate(org_list)}

    # triplas entidade × órgão × ano
    sub = privado.filter(pl.col("id_ent").is_in(top_ids)).join(m_org, on="id")
    tri = sub.group_by("id_ent", "orgao", "ano").agg(pl.col("id").n_unique().alias("n"))
    triplas = [[idx[e], oidx[o], int(a), int(n)] for e, o, a, n in tri.iter_rows()]

    # contagens distintas por (entidade|setor) × ano × grupo de órgão; grupo 4 = todos
    gi = {g: i for i, g in enumerate(GRUPOS)}
    def distintas(df, chave):
        a = df.group_by(chave, "ano", "grupo").agg(pl.col("id").n_unique().alias("n"))
        b = df.group_by(chave, "ano").agg(pl.col("id").n_unique().alias("n")).with_columns(pl.lit("__todos").alias("grupo"))
        return pl.concat([a, b.select(a.columns)])
    eg = distintas(sub, "id_ent")
    ent_ano_grupo = [[idx[e], int(a), gi.get(g, 4), int(n)] for e, a, g, n in eg.iter_rows()]
    sg = distintas(privado.join(m_org, on="id"), "setor")
    setor_ano_grupo = [[s_, int(a), gi.get(g, 4), int(n)] for s_, a, g, n in sg.iter_rows()]

    # anfitriões nominais: ministros de Estado
    min_hosts = hosts.filter(pl.col("cargo").str.to_uppercase().str.contains(r"^MINISTR[O0A]"))
    mh = min_hosts.join(privado.select("id", "id_ent"), on="id")
    ministros = (mh.group_by("autoridade").agg(
        pl.col("id").n_unique().alias("reunioes_privadas"),
        pl.col("orgao").mode().first().alias("orgao"),
        pl.col("ano").min().alias("de"), pl.col("ano").max().alias("ate"))
        .sort("reunioes_privadas", descending=True))
    min_tot = min_hosts.group_by("autoridade").agg(pl.col("id").n_unique().alias("reunioes_total"))
    ministros = ministros.join(min_tot, on="autoridade").sort("reunioes_privadas", descending=True)
    min_top = (mh.filter(pl.col("id_ent").is_in(top_ids)).group_by("autoridade", "id_ent")
                 .agg(pl.col("id").n_unique().alias("n")).sort("n", descending=True)
                 .group_by("autoridade", maintain_order=True).head(8))
    mt = {}
    for a, e, n in min_top.iter_rows():
        mt.setdefault(a, []).append([idx[e], int(n)])
    min_list = [{**m, "top": mt.get(m["autoridade"], [])} for m in ministros.to_dicts()]

    # série mensal por setor (todas as entidades privadas)
    mes = r.select("id", "mes").unique("id")
    serie = (privado.select("id", "setor").unique().join(mes, on="id")
             .group_by("mes", "setor").agg(pl.len().alias("n")).sort("mes"))
    meses = sorted(r["mes"].unique().to_list())
    setores = (privado.group_by("setor").agg(pl.col("id").n_unique().alias("n")).sort("n", descending=True)["setor"].to_list())
    serie_m = {s: [0] * len(meses) for s in setores}
    mi = {m: i for i, m in enumerate(meses)}
    for m_, s, n in serie.iter_rows():
        serie_m[s][mi[m_]] = int(n)
    total_mes = r.select("id", "mes").unique("id").group_by("mes").len().sort("mes")
    priv_mes = privado.select("id").unique().join(mes, on="id").group_by("mes").len().sort("mes")

    ent_rows = (cls.filter(pl.col("id_ent").is_in(top_ids)).join(tot, on="id_ent").sort("total", descending=True))
    entidades = [{"id": e["id_ent"], "rotulo": e["rotulo"], "tipo": e["tipo"], "setor": e["setor"],
                  "cnpj": e["id_ent"][5:] if e["id_ent"].startswith("CNPJ:") else ""} for e in ent_rows.to_dicts()]
    assert [e["id"] for e in entidades] == top_ids

    out = {
        "gerado_em": date.today().isoformat(),
        "periodo": [str(r["data"].min()), str(r["data"].max())],
        "totais": {
            "reunioes": r["id"].n_unique(),
            "reunioes_com_privados": privado["id"].n_unique(),
            "entidades_privadas": privado["id_ent"].n_unique(),
            "autoridades": r["autoridade"].n_unique(),
            "orgaos": r["orgao"].n_unique(),
        },
        "grupos": GRUPOS,
        "orgaos": [{"nome": o["orgao"], "sigla": SIGLAS.get(o["orgao"], o["orgao"]), "grupo": o["grupo"],
                    "total": o["reunioes_total"], "privadas": o["reunioes_privadas"]} for o in org_list],
        "entidades": entidades,
        "triplas": triplas,
        "ent_ano_grupo": ent_ano_grupo,
        "setor_ano_grupo": setor_ano_grupo,
        "ministros": min_list,
        "meses": meses,
        "serie_setor": serie_m,
        "serie_total": dict(zip(*total_mes.to_dict(as_series=False).values())),
        "serie_privadas": dict(zip(*priv_mes.to_dict(as_series=False).values())),
    }
    (DATA / "painel.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("ok", len(entidades), "entidades", len(triplas), "triplas", len(min_list), "ministros",
          f"{(DATA / 'painel.json').stat().st_size/1e3:.0f} KB", file=sys.stderr)


if __name__ == "__main__":
    main()
