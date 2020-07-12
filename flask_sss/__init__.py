"""
A Flask SessionInterface implementing server-side sessions stored in SQLAlchemy
"""
import base64
import os
from datetime import datetime, timezone
from typing import Callable, Protocol, Optional, Type, Dict, Any

from flask import Flask, Response, Request, current_app
from flask.json.tag import TaggedJSONSerializer
from flask.sessions import SessionInterface, SessionMixin
from sqlalchemy.orm import Session
from werkzeug.datastructures import CallbackDict


class UserSessionTableProtocol(Protocol):
    """
    Defines the minimum set of fields necessary for a declarative SQLAlchemy model to work with the SessionInterface
    """

    id: str
    session_id: str
    expires_at: datetime
    data: str
    user_id: Optional[str]


class SerializerProtocol(Protocol):
    def dumps(self, value: Dict[Any, Any]) -> str:
        pass

    def loads(self, value: str) -> Dict[Any, Any]:
        pass


def default_mint_session_id() -> str:
    return str(base64.b32encode(os.urandom(30)), encoding="utf8")


class ServerSideSession(CallbackDict, SessionMixin):
    """Baseclass for server-side based sessions."""

    def __init__(self, sid: str, initial: Optional[Dict[Any, Any]] = None, permanent: Optional[bool] = None) -> None:
        def on_update(s: ServerSideSession) -> None:
            s.modified = True

        super().__init__(initial, on_update)
        self.sid = sid
        self.modified = False
        if permanent:
            self.permanent = permanent


class SQLAlchemySessionInterface(SessionInterface):
    session_class = ServerSideSession

    def __init__(
        self,
        orm_session: Session,
        sql_session_model: Type,
        make_id: Callable[[], str],
        make_session_id: Callable[[], str] = default_mint_session_id,
        permanent: Optional[bool] = None,
        serializer: Optional[SerializerProtocol] = None,
    ):
        self.permanent = permanent
        self.make_id = make_id
        self.make_session_id = make_session_id
        if serializer is None:
            serializer = TaggedJSONSerializer()
        self.serializer = serializer
        self.orm_session = orm_session
        self.sql_session_model = sql_session_model

    def open_session(self, app: Flask, request: Request):
        """This method has to be implemented and must either return ``None``
        in case the loading failed because of a configuration error or an
        instance of a session object which implements a dictionary like
        interface + the methods and attributes on :class:`SessionMixin`.
        """
        sid = request.cookies.get(app.session_cookie_name)
        if not sid:
            sid = self.make_session_id()
            return self.session_class(sid=sid, permanent=self.permanent)

        saved_session = (
            self.orm_session.query(self.sql_session_model).filter(self.sql_session_model.session_id == sid).first()
        )
        if saved_session and saved_session.expires_at <= datetime.now(timezone.utc):
            # delete the saved session if it has expired
            self.orm_session.delete(saved_session)
            self.orm_session.commit()
            saved_session = None

        if saved_session:
            try:
                json_data = saved_session.data
                data = self.serializer.loads(json_data)
                return self.session_class(sid=sid, initial=data)
            except Exception:
                return self.session_class(sid=self.make_session_id(), permanent=self.permanent)

        return self.session_class(sid=sid, permanent=self.permanent)

    def save_session(self, app: Flask, session: ServerSideSession, response: Response) -> None:
        """This is called for actual sessions returned by :meth:`open_session`
        at the end of the request.  This is still called during a request
        context so if you absolutely need access to the request you can do
        that.
        """
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        sid = session.sid
        saved_session = (
            self.orm_session.query(self.sql_session_model).filter(self.sql_session_model.session_id == sid).first()
        )
        if not session:
            if session.modified:
                if saved_session:
                    self.orm_session.delete(saved_session)
                    self.orm_session.commit()
                response.delete_cookie(app.session_cookie_name, domain=domain, path=path)
            return

        if not self.should_set_cookie(app, session):
            return

        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        expires = self.get_expiration_time(app, session)

        val = self.serializer.dumps(dict(session))
        if saved_session:
            saved_session.data = val
            saved_session.expiry = expires
            self.orm_session.commit()
        else:
            new_session: UserSessionTableProtocol = self.sql_session_model(
                id=self.make_id(), session_id=session.sid, data=val, expires_at=expires
            )
            self.orm_session.add(new_session)
            self.orm_session.commit()

        session_id = session.sid
        response.set_cookie(
            app.session_cookie_name,
            session_id,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=current_app.config.get("SESSION_COOKIE_SAMESITE", "Strict"),
        )
