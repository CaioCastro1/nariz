"""Baixa o cadastro mensal de servidores do Executivo federal (SIAPE, Portal da
Transparência) e guarda só as linhas que podem casar com um participante privado
do e-Agendas.

Uso: uv run scripts/servidores.py 201901 201902 ...   (ou 2019-01:2026-09)
     uv run scripts/servidores.py --bacen 2019-01:2026-09   (servidores do Banco Central,
     que ficam fora do SIAPE; grava AAAAMM_BACEN.parquet e stats_BACEN.csv)

Cada zip tem ~80 MB (Cadastro.csv descompactado ~420 MB). O zip é lido direto da
memória e apagado: em disco fica só data/servidores/AAAAMM.parquet, com as linhas
cujo nome normalizado OU cujos 6 dígitos do CPF aparecem em
data/pessoas_privadas.parquet (o "ou" permite medir colisões e homônimos depois).
Também grava data/servidores/stats.csv com contagens do mês inteiro, usadas para
estimar a taxa de colisão da chave nome + CPF parcial.
"""
import csv
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from extract import norm  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "servidores"
URL = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/servidores/{}_Servidores_{}.zip"
PAUSA = 5  # segundos entre downloads
COLS = ["Id_SERVIDOR_PORTAL", "NOME", "CPF", "DESCRICAO_CARGO", "SIGLA_FUNCAO", "NIVEL_FUNCAO",
        "FUNCAO", "ORG_LOTACAO", "ORGSUP_LOTACAO", "ORG_EXERCICIO", "ORGSUP_EXERCICIO",
        "TIPO_VINCULO", "SITUACAO_VINCULO", "DATA_INGRESSO_CARGOFUNCAO", "DATA_INGRESSO_ORGAO"]


def meses(args):
    out = []
    for a in args:
        if ":" in a:
            ini, fim = (int(x.replace("-", "")) for x in a.split(":"))
            y, m = divmod(ini, 100)
            while y * 100 + m <= fim:
                out.append(f"{y}{m:02d}")
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        else:
            out.append(a.replace("-", ""))
    return out


def chaves():
    p = pl.read_parquet(DATA / "pessoas_privadas.parquet")
    nomes = set(p["pessoa_norm"].map_elements(limpa_nome, return_dtype=pl.String).unique())
    cpfs = set(p.filter(pl.col("cpf6") != "")["cpf6"].unique())
    return nomes, cpfs


def limpa_nome(n: str) -> str:
    """Nome normalizado sem pronome de tratamento no início."""
    parts = n.split()
    while parts and parts[0] in {"SR", "SRA", "DR", "DRA", "PROF", "PROFA", "SENHOR", "SENHORA"}:
        parts = parts[1:]
    return " ".join(parts)


def baixa(url, tentativas=6):
    """O CloudFront da CGU responde 405 depois de dezenas de downloads seguidos;
    espera e tenta de novo com intervalo crescente."""
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=600) as r:
                buf = r.read()
            time.sleep(PAUSA)
            return buf
        except urllib.error.HTTPError as e:
            if e.code == 404 or i == tentativas - 1:
                raise
            espera = 60 * 2 ** i
            print("HTTP", e.code, "esperando", espera, "s", file=sys.stderr)
            time.sleep(espera)


def processa(mes, nomes, cpfs, fonte="SIAPE"):
    dest = OUT / (f"{mes}.parquet" if fonte == "SIAPE" else f"{mes}_{fonte}.parquet")
    if dest.exists():
        print(mes, "já existe", file=sys.stderr)
        return None
    buf = baixa(URL.format(mes, fonte))
    z = zipfile.ZipFile(io.BytesIO(buf))
    nome_cad = next(n for n in z.namelist() if n.endswith("Cadastro.csv"))
    df = pl.read_csv(z.read(nome_cad), separator=";", encoding="latin1", infer_schema=False,
                     columns=COLS)
    del buf, z
    df = df.with_columns(
        pl.col("CPF").str.extract(r"^\*{3}\.(\d{3})\.(\d{3})-\*{2}$", 1)
          .add(pl.col("CPF").str.extract(r"^\*{3}\.(\d{3})\.(\d{3})-\*{2}$", 2)).alias("cpf6"),
        pl.col("NOME").map_elements(norm, return_dtype=pl.String).alias("nome_norm"),
        pl.lit(mes).alias("mes"),
        pl.lit(fonte).alias("fonte"),
    ).drop("CPF")
    pessoas = df.filter(pl.col("cpf6").is_not_null()).unique(["Id_SERVIDOR_PORTAL"])
    chave = pessoas.group_by("nome_norm", "cpf6").agg(pl.col("Id_SERVIDOR_PORTAL").n_unique().alias("n"))
    nome = pessoas.group_by("nome_norm").agg(pl.col("cpf6").n_unique().alias("n"))
    stats = {
        "mes": mes,
        "linhas": df.height,
        "servidores": df["Id_SERVIDOR_PORTAL"].n_unique(),
        "sem_cpf": df.filter(pl.col("cpf6").is_null())["Id_SERVIDOR_PORTAL"].n_unique(),
        "chaves": chave.height,
        "chaves_com_2+_ids": chave.filter(pl.col("n") > 1).height,
        "nomes": nome.height,
        "nomes_com_2+_cpf6": nome.filter(pl.col("n") > 1).height,
    }
    keep = df.filter(pl.col("nome_norm").is_in(nomes) | pl.col("cpf6").is_in(cpfs))
    keep.write_parquet(dest, compression="zstd")
    stats["guardadas"] = keep.height
    return stats


def main():
    OUT.mkdir(exist_ok=True)
    args = sys.argv[1:]
    fonte = "BACEN" if "--bacen" in args else "SIAPE"
    args = [a for a in args if a != "--bacen"]
    nomes, cpfs = chaves()
    print("chaves e-Agendas: nomes", len(nomes), "cpf6", len(cpfs), file=sys.stderr)
    st_path = OUT / ("stats.csv" if fonte == "SIAPE" else f"stats_{fonte}.csv")
    novo = not st_path.exists()
    with st_path.open("a", newline="") as f:
        w = None
        for mes in meses(args):
            try:
                st = processa(mes, nomes, cpfs, fonte)
            except Exception as e:  # mês ausente no portal, timeout etc.
                print(mes, "ERRO", repr(e), file=sys.stderr)
                continue
            if st is None:
                continue
            if w is None:
                w = csv.DictWriter(f, fieldnames=list(st))
                if novo:
                    w.writeheader()
            w.writerow(st)
            f.flush()
            print(st, file=sys.stderr)


if __name__ == "__main__":
    main()
