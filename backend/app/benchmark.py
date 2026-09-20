"""
Benchmark de detecção pela linha de comando.

Imprime o relatório na saída padrão, para o destino ser escolhido por
redirecionamento em vez de um caminho configurável — que dependeria de qual
pasta do projeto está montada dentro do contêiner:

    docker compose exec -T backend python -m app.benchmark > docs/resultados/deteccao.md
    docker compose exec -T backend python -m app.benchmark --csv > docs/resultados/deteccao.csv

`--real <machine_id>` acrescenta um cenário com as leituras já gravadas
daquela máquina: o falso positivo medido em uso de verdade.
"""
import argparse
import sys

from app.database import SessionLocal
from app.models.machine import Machine
from app.models.user import User
from app.services import benchmark, benchmark_store


def render(result: benchmark.BenchmarkResult, as_csv: bool) -> str:
    return benchmark.to_csv(result) if as_csv else benchmark.to_markdown(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de detecção do AnomalyDetect")
    parser.add_argument("--csv", action="store_true", help="imprime CSV em vez de Markdown")
    parser.add_argument("--real", type=int, action="append", default=[],
                        help="id de máquina cujas leituras reais viram cenário (pode repetir)")
    parser.add_argument("--real-minutes", type=int, default=240,
                        help="janela de leituras reais a reproduzir (padrão: 240)")
    parser.add_argument("--save", action="store_true", help="grava a rodada para o painel")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        dono = db.query(User).order_by(User.id.asc()).first()
        if dono is None:
            print("Nenhum usuário cadastrado: crie uma conta antes de rodar o benchmark.", file=sys.stderr)
            return 1

        resultado = benchmark.run(db, dono.id)
        for machine_id in args.real:
            origem = db.query(Machine).filter(Machine.id == machine_id).first()
            if origem is None:
                print(f"Máquina {machine_id} não encontrada; cenário real ignorado.", file=sys.stderr)
                continue
            resultado.scenarios.append(
                benchmark.run_real_scenario(db, machine_id, origem.owner_id, minutes=args.real_minutes)
            )
        resultado.metrics = benchmark.confusion(resultado.scenarios)

        if args.save:
            benchmark_store.save(db, dono.id, resultado)
        print(render(resultado, args.csv))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
