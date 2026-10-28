import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from sqlmodel import Session

from database import engine
from services.admin_service import seed_initial_admin


def main() -> None:
    load_dotenv()

    with Session(engine) as db:
        try:
            admin = seed_initial_admin(db, email_verified=True)
            print(f"Successfully created admin user: {admin.email}")
        except (ValueError, RuntimeError) as exc:
            print(f"Error: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    main()