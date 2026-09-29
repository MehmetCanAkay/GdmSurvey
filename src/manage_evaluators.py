"""
Uzman ekleme, listeleme ve şifre yenileme.

Şifre yalnızca oluşturulduğu veya yenilendiği anda bir kez yazdırılır.
Liste çıktısında şifre yoktur.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import EvaluatorRepository, SessionLocal, init_db
from src.domain import default_evaluators, parse_axis, parse_role


def cmd_add(args) -> None:
    """Tek bir uzman ekler ve şifreyi bir kez gösterir."""
    role = parse_role(args.role)
    axes = [parse_axis(part).value for part in args.axes.split(",") if part.strip()]
    if not axes:
        raise SystemExit("En az bir eksen gerekli.")
    repository = EvaluatorRepository(SessionLocal)
    try:
        repository.add(args.id, args.name, role.value, axes, args.password)
    except IntegrityError as exc:
        raise SystemExit(f"Bu uzman kimliği zaten kayıtlı: {args.id}") from exc
    print(f"Uzman eklendi: {args.id} ({args.name})", flush=True)
    print("Şifre yalnızca bu kez gösterilir:", flush=True)
    print(f"  {args.password}", flush=True)


def cmd_list(_args) -> None:
    """Kayıtlı uzmanları, şifre olmadan listeler."""
    evaluators = EvaluatorRepository(SessionLocal).list_all()
    if not evaluators:
        print("Kayıtlı uzman yok.")
        return
    print(f"{'ID':<6} {'Ad':<20} {'Rol':<16} Eksenler")
    print("-" * 72)
    for evaluator in evaluators:
        axes = ", ".join(evaluator["assigned_axes"])
        print(
            f"{evaluator['evaluator_id']:<6} {evaluator['name']:<20} "
            f"{evaluator['role']:<16} {axes}"
        )


def cmd_reset_password(args) -> None:
    """Şifreyi yeniler ve yeni değeri bir kez gösterir."""
    updated = EvaluatorRepository(SessionLocal).reset_password(args.id, args.new_password)
    if not updated:
        raise SystemExit(f"Uzman bulunamadı: {args.id}")
    print(f"Şifre güncellendi: {args.id}", flush=True)
    print("Yeni şifre yalnızca bu kez gösterilir:", flush=True)
    print(f"  {args.new_password}", flush=True)


def cmd_add_sample(_args) -> None:
    """Dört uzmanlık kadroyu ekler. Var olan kayıtlara dokunmaz."""
    created = EvaluatorRepository(SessionLocal).seed_defaults(default_evaluators())
    if not created:
        print("Varsayılan uzmanlar zaten kayıtlı. Şifreler yeniden gösterilmez.")
        return
    print("Yeni uzmanlar eklendi. Şifreler yalnızca bu kez gösterilir:", flush=True)
    for seed in created:
        axes = ", ".join(axis.value for axis in seed.assigned_axes)
        print(f"  {seed.evaluator_id} — {seed.name} — {seed.role.value} — {axes}", flush=True)
        print(f"    şifre: {seed.password}", flush=True)


def main() -> None:
    """Komut satırı giriş noktası."""
    init_db()
    parser = argparse.ArgumentParser(description="GDM uzman yönetimi")
    subparsers = parser.add_subparsers(dest="command")

    add = subparsers.add_parser("add", help="Uzman ekle")
    add.add_argument("--id", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--role", required=True, help="perinatolog, endokrinolog, diyetisyen")
    add.add_argument("--axes", required=True, help="Virgülle: mutfak,oruc,lohusa,saglik_sistemi,sosyal")
    add.add_argument("--password", required=True)

    subparsers.add_parser("list", help="Uzmanları listele")

    reset = subparsers.add_parser("reset-password", help="Şifreyi yenile")
    reset.add_argument("--id", required=True)
    reset.add_argument("--new-password", required=True)

    subparsers.add_parser("add-sample", help="Dört uzmanlık kadroyu ekle")

    args = parser.parse_args()
    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "reset-password": cmd_reset_password,
        "add-sample": cmd_add_sample,
    }
    command = commands.get(args.command)
    if command is None:
        parser.print_help()
        return
    try:
        command(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
