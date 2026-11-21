"""Zdarzenia domenowe i ich asynchroniczna obsługa.

Endpoint po udanej (zatwierdzonej) operacji publikuje zdarzenie, np. „plan zarezerwowany”.
Handlery są wykonywane przez mechanizm zadań w tle FastAPI/Starlette (``BackgroundTasks``):
dopiero po wysłaniu odpowiedzi do klienta, we własnej sesji bazy danych. Dzięki temu
operacja biznesowa nie czeka na skutki uboczne, a błąd handlera jej nie wycofuje.

Obecnie jedynym subskrybentem jest dziennik zdarzeń warsztatu (``workshop_events``), ale
nowe skutki uboczne (np. powiadomienie e-mail) dodaje się kolejnym ``@subscribe`` – bez
zmiany kodu serwisów i endpointów.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import BackgroundTasks

logger = logging.getLogger("offcut.events")

ALL = "*"


@dataclass(frozen=True)
class DomainEvent:
    type: str
    workshop_id: int
    actor_user_id: int | None
    message: str
    data: dict = field(default_factory=dict)


Handler = Callable[[DomainEvent], None]
_handlers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event_type: str = ALL) -> Callable[[Handler], Handler]:
    """Rejestruje handler dla typu zdarzenia (``*`` = wszystkie)."""

    def register(handler: Handler) -> Handler:
        _handlers[event_type].append(handler)
        return handler

    return register


def _run_safely(handler: Handler, event: DomainEvent) -> None:
    try:
        handler(event)
    except Exception:  # noqa: BLE001 – błąd skutku ubocznego nie może psuć operacji
        logger.exception("Handler %s nie obsłużył zdarzenia %s", handler.__name__, event.type)


def publish(background: BackgroundTasks, event: DomainEvent) -> None:
    """Planuje asynchroniczne wykonanie wszystkich handlerów zdarzenia (po wysłaniu odpowiedzi)."""
    for handler in (*_handlers[event.type], *_handlers[ALL]):
        background.add_task(_run_safely, handler, event)


@subscribe(ALL)
def record_in_activity_log(event: DomainEvent) -> None:
    """Zapisuje zdarzenie w dzienniku warsztatu (osobna sesja – żądanie jest już zakończone)."""
    from app.db import SessionLocal
    from app.models import WorkshopEvent

    with SessionLocal() as db:
        db.add(WorkshopEvent(workshop_id=event.workshop_id, type=event.type,
                             actor_user_id=event.actor_user_id, message=event.message[:300],
                             data=event.data))
        db.commit()
