"""
Benchmark de detecção pela linha de comando; o relatório sai na saída padrão:

    docker compose exec -T backend python -m app.benchmark > docs/resultados/deteccao.md
    docker compose exec -T backend python -m app.benchmark --csv > docs/resultados/deteccao.csv

`--real <machine_id>` acrescenta um cenário com as leituras gravadas daquela máquina.
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
    parser.add_argument("--user", type=int, default=None,
                        help="id do dono das máquinas efêmeras (padrão: o de menor id)")
    parser.add_argument("--real-limit", type=int, default=None,
                        help=f"teto de leituras reais reproduzidas (padrão: {benchmark.REAL_LIMIT})")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        owner = (db.query(User).filter(User.id == args.user).first() if args.user
                else db.query(User).order_by(User.id.asc()).first())
        if owner is None:
            print("Usuário não encontrado: crie uma conta ou informe --user.", file=sys.stderr)
            return 1

        result = benchmark.run(db, owner.id)
        for machine_id in args.real:
            source = db.query(Machine).filter(Machine.id == machine_id).first()
            if source is None:
                print(f"Máquina {machine_id} não encontrada; cenário real ignorado.", file=sys.stderr)
                continue
            result.scenarios.append(
                benchmark.run_real_scenario(db, machine_id, source.owner_id, minutes=args.real_minutes,
                                            limit=args.real_limit or benchmark.REAL_LIMIT)
            )
        result.metrics = benchmark.confusion(result.scenarios)

        if args.save:
            benchmark_store.save(db, owner.id, result)
        print(render(result, args.csv))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
