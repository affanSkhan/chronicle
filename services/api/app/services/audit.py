from sqlalchemy.orm import Session

from app.models.entities import AuditEvent


def record_audit_event(
    db: Session,
    *,
    actor_user_id: str | None,
    run_id: str | None,
    target_entity_type: str,
    target_entity_id: str,
    action: str,
    previous_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
    resolution_status: str = "recorded",
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        run_id=run_id,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        action=action,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
        resolution_status=resolution_status,
    )
    db.add(event)
    return event
