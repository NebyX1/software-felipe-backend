from sqlalchemy import text

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    db.create_all()
    db.session.execute(
        text(
            "ALTER TABLE units ADD COLUMN IF NOT EXISTS emoji "
            "VARCHAR(16) NOT NULL DEFAULT '🏛️'"
        )
    )
    db.session.execute(
        text("UPDATE units SET emoji='🏛️' WHERE emoji IS NULL OR emoji=''"),
    )
    db.session.commit()

print('schema-synced')
