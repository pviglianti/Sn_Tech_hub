"""Auto-provision AppFileClass rows when new file types become assessment-available.

When users toggle an InstanceAppFileType to ``is_available_for_assessment=True``
or the SN data-pull discovers a new file type, this module ensures a
corresponding ``AppFileClass`` admin-config row exists so that query patterns
and assessment-type links can be defined for it.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from ..models import (
    AppFileClass,
    AssessmentTypeConfig,
    AssessmentTypeFileClass,
    InstanceAppFileType,
)

logger = logging.getLogger(__name__)


def ensure_app_file_class_for_instance_type(
    session: Session,
    instance_app_file_type: InstanceAppFileType,
    *,
    commit: bool = False,
) -> Optional[AppFileClass]:
    """Ensure an ``AppFileClass`` row exists for the given instance file type.

    If an ``AppFileClass`` with a matching ``sys_class_name`` already exists,
    the ``InstanceAppFileType.app_file_class_id`` FK is set and the existing
    row is returned.

    If no match exists, a new ``AppFileClass`` row is created with sensible
    defaults derived from the instance record, linked to **all** active
    assessment types via ``AssessmentTypeFileClass``, and then returned.

    Returns ``None`` if the instance row has no usable ``sys_class_name``.
    """
    sys_class_name = (instance_app_file_type.sys_class_name or "").strip()
    if not sys_class_name:
        return None

    # Check for existing AppFileClass
    existing = session.exec(
        select(AppFileClass).where(AppFileClass.sys_class_name == sys_class_name)
    ).first()

    if existing:
        # Link the instance row to the admin config row
        if instance_app_file_type.app_file_class_id != existing.id:
            instance_app_file_type.app_file_class_id = existing.id
            session.add(instance_app_file_type)
        if commit:
            session.commit()
        return existing

    # Create new AppFileClass from instance metadata
    label = (
        instance_app_file_type.label
        or instance_app_file_type.name
        or sys_class_name
    )
    # Derive target_table_field from instance source_field if present
    target_table_field = instance_app_file_type.source_field or None

    new_class = AppFileClass(
        sys_class_name=sys_class_name,
        label=label,
        description=f"Auto-created from instance file type '{label}'",
        target_table_field=target_table_field,
        has_script=True,  # Conservative default — admin can toggle
        is_important=False,  # Not in baseline catalog, admin decides
        display_order=900,  # Sort after seed data
        is_active=True,
    )
    session.add(new_class)
    session.flush()  # Get the new id

    # Link the instance row
    instance_app_file_type.app_file_class_id = new_class.id
    session.add(instance_app_file_type)

    # Auto-link to all active assessment types via junction table
    active_types = session.exec(
        select(AssessmentTypeConfig).where(AssessmentTypeConfig.is_active == True)
    ).all()
    for at in active_types:
        session.add(AssessmentTypeFileClass(
            assessment_type_config_id=at.id,
            app_file_class_id=new_class.id,
            is_default=False,  # Not default — admin must opt-in
            display_order=900,
        ))

    if commit:
        session.commit()

    logger.info(
        "Auto-created AppFileClass '%s' (id=%s) from instance file type, "
        "linked to %d assessment types",
        sys_class_name, new_class.id, len(active_types),
    )
    return new_class


def backfill_app_file_class_ids(session: Session) -> int:
    """One-time backfill: set app_file_class_id on InstanceAppFileType rows
    where sys_class_name matches an existing AppFileClass.

    Returns the number of rows updated.
    """
    all_classes = session.exec(select(AppFileClass)).all()
    class_map = {c.sys_class_name: c.id for c in all_classes}

    unlinked = session.exec(
        select(InstanceAppFileType)
        .where(InstanceAppFileType.app_file_class_id == None)  # noqa: E711
        .where(InstanceAppFileType.sys_class_name != None)  # noqa: E711
    ).all()

    updated = 0
    for row in unlinked:
        scn = (row.sys_class_name or "").strip()
        if scn in class_map:
            row.app_file_class_id = class_map[scn]
            session.add(row)
            updated += 1

    if updated:
        session.commit()
    return updated
