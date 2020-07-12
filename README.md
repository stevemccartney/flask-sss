# Flask-SSS

Server-Side Sessions for Flask implemented as a SessionInterface.

## Data model

The user_id field allows for users to either list their open sessions and close other sessions they have open.  It also enables administrators to log out all sessions for a user that needs to be suspended or deleted.

## Usage

```python
from flask import Flask
from flask_sss import SQLAlchemySessionInterface
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, String, DateTime, Text
from datetime import datetime
import uuid

app = Flask(__name__)
db = SQLAlchemy(app)

class UserSession(db.Model):
    __tablename__ = "user_session"

    id = Column(String(length=255), primary_key=True)
    session_id = Column(String(length=255), unique=True)
    user_id = Column(String(length=255), nullable=True)
    created_at = Column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime(), nullable=False)
    data = Column(Text(), nullable=False)

def make_id():
    return str(uuid.uuid4())

app.session_interface = SQLAlchemySessionInterface(
    orm_session=db.session,
    sql_session_model=UserSession,
    make_id=make_id
)
```
## Notes

A daily process to remove expired sessions is recommended to stop the session list expanding over time.